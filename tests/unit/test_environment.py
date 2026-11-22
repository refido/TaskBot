import os

import pytest

from src.config import Config
from src.infrastructure.config import environment
from src.infrastructure.config.settings import AppSettings
from src.infrastructure.database.operator_store import (
    DatabaseConfig,
    OperatorDatabaseManager,
    OperatorTargets,
)


@pytest.fixture
def env_file(monkeypatch, tmp_path):
    # Reject unsafe writes on every platform, even if the host OS permits them.
    class GuardedEnvironment(dict):
        def setdefault(self, key, value):
            assert not key.startswith("NIK")
            if len(value.encode("utf-16-le")) // 2 > 32_767:
                raise ValueError("the environment variable is longer than 32767 characters")
            return super().setdefault(key, value)

    monkeypatch.setattr(os, "environ", GuardedEnvironment())
    path = tmp_path / ".env"
    monkeypatch.setattr(environment, "DOTENV_PATH", path)
    return path


def test_full_nik_values_reach_all_configuration_consumers(env_file):
    nik_1 = ",".join(f"{number:016d}" for number in range(2147))
    nik_2 = ",".join(f"{number:016d}" for number in range(2146))
    assert (len(nik_1), len(nik_2)) == (36_498, 36_481)
    env_file.write_text(
        "URL_APPLICATION=https://example.test/app\n"
        "HEADLESS=0\nLOG_LEVEL=WARNING\n"
        "EMAIL_1=first@example.test\nPIN_1=111111\nNAME_OPERATORS_1=First\n"
        "EMAIL_2=second@example.test\nPIN_2=222222\nNAME_OPERATORS_2=Second\n"
        "DB_HOST=localhost\nDB_PORT=5432\nDB_NAME=test\n"
        "DB_USER=test\nDB_PASSWORD=test-only\n"
        f'NIK_1="{nik_1}"\nNIK_2="{nik_2}"\n',
        encoding="utf-8",
    )
    original = env_file.read_bytes()

    values = environment.load_environment()
    assert values["NIK_1"] == nik_1
    assert values["NIK_2"] == nik_2
    config = Config()
    assert [",".join(account.nik) for account in config.accounts] == [nik_1, nik_2]
    assert config.headless is False
    assert config.url_application == "https://example.test/app"
    assert os.getenv("LOG_LEVEL") == "WARNING"
    assert DatabaseConfig.from_env().password == "test-only"
    assert len(OperatorTargets.from_env().targets) == 2
    manager = OperatorDatabaseManager.from_env()
    assert len(manager.targets.targets) == 2
    assert os.getenv("NIK_1") is None
    assert os.getenv("NIK_2") is None
    assert env_file.read_bytes() == original


def test_manager_keeps_in_memory_nik_for_operator_detection(env_file):
    env_file.write_text(
        "DB_HOST=localhost\nDB_PORT=5432\nDB_NAME=test\n"
        "DB_USER=test\nDB_PASSWORD=test-only\nNIK_2=" + "1" * 36_481,
        encoding="utf-8",
    )
    # The manager must forward the full mapping when its next reader skips I/O.
    with pytest.raises(ValueError, match="Missing NAME_OPERATORS_2"):
        OperatorDatabaseManager.from_env()


def test_environment_precedence_and_dotenv_syntax_are_preserved(env_file):
    os.environ.update(BASE="process", NIK_1="process-nik", EMPTY="")
    env_file.write_text(
        "BASE=file\nEXPANDED=${BASE}/suffix\nEMPTY=file\nBARE\n"
        "NIK_1=file-nik\nNIK_2='  001, 002  '\n"
        "NIK=single\nNIK_10=numbered\nMULTILINE=\"first\nsecond\"\n",
        encoding="utf-8",
    )
    values = environment.load_environment()
    assert values["BASE"] == "process"
    assert values["EXPANDED"] == "process/suffix"
    assert values["EMPTY"] == ""
    assert "BARE" not in values
    assert values["NIK_1"] == "process-nik"
    assert values["NIK_2"] == "  001, 002  "
    assert values["MULTILINE"] == "first\nsecond"
    for key in ("NIK", "NIK_2", "NIK_10"):
        assert key in values
        assert key not in os.environ


@pytest.mark.parametrize(
    "value", ["x" * 32_768, "\U0001f600" * 16_384], ids=["ascii", "utf16"]
)
def test_other_oversized_values_remain_in_memory(env_file, value):
    env_file.write_text(f"OTHER={value}\nSMALL=works\n", encoding="utf-8")
    values = environment.load_environment()
    assert values["OTHER"] == value
    assert "OTHER" not in os.environ
    assert os.getenv("SMALL") == "works"


def test_value_at_windows_limit_is_exported(env_file):
    env_file.write_text("AT_LIMIT=" + "x" * 32_767, encoding="utf-8")
    values = environment.load_environment()
    assert values["AT_LIMIT"] == os.getenv("AT_LIMIT") == "x" * 32_767


def test_explicit_mapping_and_disabled_loading(env_file):
    env_file.write_text("HEADLESS=0\n", encoding="utf-8")
    assert environment.load_environment({}, load_env_file=False) == {}
    assert environment.load_environment(load_env_file=False) == dict(os.environ)
    assert "HEADLESS" not in os.environ
    assert AppSettings.from_env({}, load_env_file=False).headless is True
    os.environ["PYTHON_DOTENV_DISABLED"] = "true"
    assert "HEADLESS" not in environment.load_environment()
    del os.environ["PYTHON_DOTENV_DISABLED"]
    assert AppSettings.from_env({}).headless is True
    assert os.getenv("HEADLESS") == "0"


def test_missing_file_uses_process_environment(env_file):
    os.environ["LOG_LEVEL"] = "DEBUG"
    assert environment.load_environment() == dict(os.environ)
