from dataclasses import dataclass

from src.application.dto.run_context import AccountRunContext, RunContext
from src.infrastructure.config.settings import AppSettings
from src.privacy import register_private_values, set_nik_masking


@dataclass(frozen=True)
class AccountConfig:
    email_user: str
    pin_user: str
    nik: list[str]
    operator_id: str = "operator_01"

    @classmethod
    def from_settings(
        cls,
        email_user: str,
        pin_user: str,
        nik: tuple[str, ...],
        operator_id: str = "operator_01",
    ) -> AccountConfig:
        return cls(
            email_user=email_user,
            pin_user=pin_user,
            nik=list(nik),
            operator_id=operator_id,
        )


class Config:
    def __init__(
        self,
        settings: AppSettings | None = None,
        run_context: RunContext | None = None,
    ):
        self._settings = settings or (
            run_context.settings if run_context is not None else AppSettings.from_env()
        )
        set_nik_masking(self._settings.mask_nik)
        register_private_values(
            *(
                credential
                for account in self._settings.accounts
                for credential in (account.email_user, account.pin_user)
            )
        )
        self.run_context = run_context or RunContext.from_settings(self._settings)

        self.url_application: str = self._settings.url_application
        self.headless: bool = self._settings.headless
        self.mask_nik: bool = self._settings.mask_nik
        self.accounts: list[AccountConfig] = [
            AccountConfig.from_settings(
                account.email_user,
                account.pin_user,
                account.nik,
                account.operator_id,
            )
            for account in self._settings.accounts
        ]

        primary_account = (
            self.accounts[0]
            if self.accounts
            else AccountConfig("", "", [], operator_id="operator_01")
        )
        self.operator_id: str = primary_account.operator_id
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
            Config(
                settings=self._settings.for_account(account),
                run_context=self.run_context,
            )
            for account in self._settings.accounts
        ]

    def account_run_contexts(self) -> tuple[AccountRunContext, ...]:
        return self.run_context.accounts
