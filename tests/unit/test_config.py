from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.application.dto.run_context import RunContext
from src.config import AccountConfig, Config
from src.infrastructure.config.settings import AppSettings


def test_app_settings_loads_single_account_format():
    settings = AppSettings.from_env(
        {
            "URL_APPLICATION": "https://example.test/app",
            "EMAIL": "first@example.com",
            "PIN": "123456",
            "NIK": "111, 222 ,333",
        },
        load_env_file=False,
    )

    assert settings.url_application == "https://example.test/app"
    assert len(settings.accounts) == 1
    assert settings.accounts[0].email_user == "first@example.com"
    assert settings.accounts[0].pin_user == "123456"
    assert settings.accounts[0].nik == ("111", "222", "333")
    assert settings.accounts[0].operator_id == "operator_01"
    assert settings.headless is True


def test_app_settings_uses_explicit_single_operator_id():
    settings = AppSettings.from_env(
        {
            "EMAIL": "first@example.com",
            "PIN": "123456",
            "OPERATOR_ID": "operator_primary",
        },
        load_env_file=False,
    )

    assert settings.accounts[0].operator_id == "operator_primary"


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("TRUE", True),
        ("True", True),
        ("1", True),
        (" false ", False),
        ("FALSE", False),
        ("0", False),
    ],
)
def test_app_settings_parses_headless_environment_values(
    raw_value: str, expected: bool
):
    settings = AppSettings.from_env(
        {"HEADLESS": raw_value},
        load_env_file=False,
    )

    assert settings.headless is expected


def test_app_settings_rejects_invalid_headless_environment_value():
    with pytest.raises(ValueError, match="HEADLESS"):
        AppSettings.from_env({"HEADLESS": "sometimes"}, load_env_file=False)


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("", True),
        ("TRUE", True),
        ("on", True),
        ("yes", True),
        ("0", False),
        ("false", False),
        ("OFF", False),
        ("no", False),
    ],
)
def test_app_settings_parses_mask_environment_values(raw_value: str, expected: bool):
    settings = AppSettings.from_env({"MASK": raw_value}, load_env_file=False)
    assert settings.mask_nik is expected


def test_app_settings_loads_numbered_accounts_in_numeric_order():
    settings = AppSettings.from_env(
        {
            "URL_APPLICATION": "https://example.test/app",
            "EMAIL_10": "tenth@example.com",
            "PIN_10": "101010",
            "NIK_10": "101",
            "EMAIL_2": "second@example.com",
            "PIN_2": "222222",
            "NIK_2": "201,202",
        },
        load_env_file=False,
    )

    assert [account.email_user for account in settings.accounts] == [
        "second@example.com",
        "tenth@example.com",
    ]
    assert settings.accounts[0].nik == ("201", "202")
    assert settings.accounts[1].nik == ("101",)
    assert [account.operator_id for account in settings.accounts] == [
        "operator_02",
        "operator_10",
    ]


def test_app_settings_uses_explicit_numbered_operator_ids():
    settings = AppSettings.from_env(
        {
            "EMAIL_1": "first@example.com",
            "PIN_1": "111111",
            "OPERATOR_1_ID": "operator_west",
            "EMAIL_2": "second@example.com",
            "PIN_2": "222222",
            "OPERATOR_2_ID": "operator-east",
        },
        load_env_file=False,
    )

    assert [account.operator_id for account in settings.accounts] == [
        "operator_west",
        "operator-east",
    ]


@pytest.mark.parametrize(
    "operator_id",
    ["../escape", "contains space", "first@example.com", "_operator"],
)
def test_app_settings_rejects_unsafe_operator_ids(operator_id: str):
    with pytest.raises(ValueError, match="OPERATOR_1_ID"):
        AppSettings.from_env(
            {
                "EMAIL_1": "first@example.com",
                "PIN_1": "111111",
                "OPERATOR_1_ID": operator_id,
            },
            load_env_file=False,
        )


def test_app_settings_rejects_operator_id_that_matches_a_credential():
    with pytest.raises(ValueError, match="credential"):
        AppSettings.from_env(
            {
                "EMAIL_1": "first@example.com",
                "PIN_1": "operator_secret",
                "OPERATOR_1_ID": "operator_secret",
            },
            load_env_file=False,
        )


def test_app_settings_rejects_duplicate_operator_ids():
    with pytest.raises(ValueError, match="unique"):
        AppSettings.from_env(
            {
                "EMAIL_1": "first@example.com",
                "PIN_1": "111111",
                "OPERATOR_1_ID": "operator_shared",
                "EMAIL_2": "second@example.com",
                "PIN_2": "222222",
                "OPERATOR_2_ID": "OPERATOR_SHARED",
            },
            load_env_file=False,
        )


def test_app_settings_rejects_partial_numbered_account():
    try:
        AppSettings.from_env(
            {
                "EMAIL_1": "broken@example.com",
                "NIK_1": "111",
            },
            load_env_file=False,
        )
    except ValueError as exc:
        assert "EMAIL_1" in str(exc)
        assert "PIN_1" in str(exc)
    else:
        raise AssertionError(
            "Expected AppSettings.from_env() to reject partial account settings"
        )


def test_config_wrapper_exposes_compatibility_fields_and_account_configs():
    settings = AppSettings.from_env(
        {
            "URL_APPLICATION": "https://example.test/app",
            "HEADLESS": "0",
            "EMAIL_1": "first@example.com",
            "PIN_1": "111111",
            "NIK_1": "1001,1002",
            "EMAIL_2": "second@example.com",
            "PIN_2": "222222",
            "NIK_2": "2001",
        },
        load_env_file=False,
    )

    config = Config(settings=settings)

    assert config.url_application == "https://example.test/app"
    assert config.email_user == "first@example.com"
    assert config.pin_user == "111111"
    assert config.nik == ["1001", "1002"]
    assert config.headless is False
    assert config.accounts == [
        AccountConfig(
            email_user="first@example.com",
            pin_user="111111",
            nik=["1001", "1002"],
            operator_id="operator_01",
        ),
        AccountConfig(
            email_user="second@example.com",
            pin_user="222222",
            nik=["2001"],
            operator_id="operator_02",
        ),
    ]

    account_configs = config.account_configs()
    assert len(account_configs) == 2
    assert [account_config.email_user for account_config in account_configs] == [
        "first@example.com",
        "second@example.com",
    ]
    assert [account_config.operator_id for account_config in account_configs] == [
        "operator_01",
        "operator_02",
    ]
    assert [account_config.nik for account_config in account_configs] == [
        ["1001", "1002"],
        ["2001"],
    ]
    assert [account_config.headless for account_config in account_configs] == [
        False,
        False,
    ]
    assert all(
        account_config.run_context is config.run_context
        for account_config in account_configs
    )


def test_config_exposes_typed_run_contexts_for_later_phases():
    settings = AppSettings.from_env(
        {
            "URL_APPLICATION": "https://example.test/app",
            "HEADLESS": "FALSE",
            "EMAIL_1": "first@example.com",
            "PIN_1": "111111",
            "NIK_1": "1001,1002",
        },
        load_env_file=False,
    )

    run_context = RunContext.from_settings(
        settings,
        now=datetime(2026, 8, 20, 20, 21, 15, tzinfo=UTC),
        suffix="482A",
    )
    config = Config(settings=settings, run_context=run_context)

    assert config.run_context is run_context
    assert config.account_run_contexts() == run_context.accounts
    assert run_context.run_id == "20260820_202115_482a"
    assert run_context.started_at == "2026-08-20T20:21:15+00:00"
    project_root = Path(__file__).resolve().parents[2]
    assert run_context.run_dir == (
        project_root / "reports" / "2026" / "08" / "20" / "20260820_202115_482a"
    )
    assert run_context.primary_account() is not None
    assert run_context.primary_account().operator_id == "operator_01"
    assert run_context.primary_account().url_application == "https://example.test/app"
    assert run_context.primary_account().nik == ("1001", "1002")
    assert run_context.primary_account().headless is False
    assert run_context.primary_account().to_settings().headless is False
    assert (
        run_context.primary_account().to_settings().accounts[0].operator_id
        == "operator_01"
    )


def test_run_context_generates_required_run_id_shape():
    settings = AppSettings.from_env({}, load_env_file=False)

    run_context = RunContext.from_settings(settings)

    assert run_context.run_id[:8].isdigit()
    assert run_context.run_id[8] == "_"
    assert run_context.run_id[9:15].isdigit()
    assert run_context.run_id[15] == "_"
    assert len(run_context.run_id[16:]) == 4
    assert all(character in "0123456789abcdef" for character in run_context.run_id[16:])
    assert run_context.run_dir.is_absolute()
