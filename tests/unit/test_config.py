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
    assert settings.headless is True


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
        ),
        AccountConfig(
            email_user="second@example.com",
            pin_user="222222",
            nik=["2001"],
        ),
    ]

    account_configs = config.account_configs()
    assert len(account_configs) == 2
    assert [account_config.email_user for account_config in account_configs] == [
        "first@example.com",
        "second@example.com",
    ]
    assert [account_config.nik for account_config in account_configs] == [
        ["1001", "1002"],
        ["2001"],
    ]
    assert [account_config.headless for account_config in account_configs] == [
        False,
        False,
    ]


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

    config = Config(settings=settings)
    run_context = RunContext.from_settings(settings)

    assert config.run_context == run_context
    assert config.account_run_contexts() == run_context.accounts
    assert run_context.primary_account() is not None
    assert run_context.primary_account().url_application == "https://example.test/app"
    assert run_context.primary_account().nik == ("1001", "1002")
    assert run_context.primary_account().headless is False
    assert run_context.primary_account().to_settings().headless is False
