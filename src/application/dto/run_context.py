from __future__ import annotations

from dataclasses import dataclass

from src.infrastructure.config.settings import AccountSettings, AppSettings


@dataclass(frozen=True, slots=True)
class AccountRunContext:
    url_application: str
    email_user: str
    pin_user: str
    nik: tuple[str, ...]

    @classmethod
    def from_settings(
        cls, app_settings: AppSettings, account_settings: AccountSettings
    ) -> "AccountRunContext":
        return cls(
            url_application=app_settings.url_application,
            email_user=account_settings.email_user,
            pin_user=account_settings.pin_user,
            nik=account_settings.nik,
        )

    def to_settings(self) -> AppSettings:
        return AppSettings(
            url_application=self.url_application,
            accounts=(
                AccountSettings(
                    email_user=self.email_user,
                    pin_user=self.pin_user,
                    nik=self.nik,
                ),
            ),
        )


@dataclass(frozen=True, slots=True)
class RunContext:
    settings: AppSettings
    accounts: tuple[AccountRunContext, ...]

    @classmethod
    def from_settings(cls, settings: AppSettings) -> "RunContext":
        accounts = tuple(
            AccountRunContext.from_settings(settings, account)
            for account in settings.accounts
        )
        return cls(settings=settings, accounts=accounts)

    def primary_account(self) -> AccountRunContext | None:
        if not self.accounts:
            return None
        return self.accounts[0]
