from dataclasses import dataclass

from src.application.dto.run_context import AccountRunContext, RunContext
from src.infrastructure.config.settings import AppSettings


@dataclass(frozen=True)
class AccountConfig:
    email_user: str
    pin_user: str
    nik: list[str]

    @classmethod
    def from_settings(
        cls, email_user: str, pin_user: str, nik: tuple[str, ...]
    ) -> AccountConfig:
        return cls(
            email_user=email_user,
            pin_user=pin_user,
            nik=list(nik),
        )


class Config:
    def __init__(self, settings: AppSettings | None = None):
        self._settings = settings or AppSettings.from_env()
        self.run_context = RunContext.from_settings(self._settings)

        self.url_application: str = self._settings.url_application
        self.headless: bool = self._settings.headless
        self.accounts: list[AccountConfig] = [
            AccountConfig.from_settings(
                account.email_user,
                account.pin_user,
                account.nik,
            )
            for account in self._settings.accounts
        ]

        primary_account = (
            self.accounts[0] if self.accounts else AccountConfig("", "", [])
        )
        self.email_user: str = primary_account.email_user
        self.pin_user: str = primary_account.pin_user
        self.nik: list[str] = list(primary_account.nik)

    @property
    def settings(self) -> AppSettings:
        return self._settings

    def account_configs(self) -> list[Config]:
        """Build one Config object per account for isolated threaded execution."""
        if not self._settings.accounts:
            return []

        return [
            Config(settings=self._settings.for_account(account))
            for account in self._settings.accounts
        ]

    def account_run_contexts(self) -> tuple[AccountRunContext, ...]:
        return self.run_context.accounts
