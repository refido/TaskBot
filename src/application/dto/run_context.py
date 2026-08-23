from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.infrastructure.config.settings import AccountSettings, AppSettings

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_RUN_SUFFIX_PATTERN = re.compile(r"^[0-9a-fA-F]{4}$")


@dataclass(frozen=True, slots=True)
class AccountRunContext:
    url_application: str
    email_user: str
    pin_user: str
    nik: tuple[str, ...]
    headless: bool = True
    mask_nik: bool = True
    operator_id: str = "operator_01"

    @classmethod
    def from_settings(
        cls, app_settings: AppSettings, account_settings: AccountSettings
    ) -> AccountRunContext:
        return cls(
            url_application=app_settings.url_application,
            email_user=account_settings.email_user,
            pin_user=account_settings.pin_user,
            nik=account_settings.nik,
            headless=app_settings.headless,
            mask_nik=app_settings.mask_nik,
            operator_id=account_settings.operator_id,
        )

    def to_settings(self) -> AppSettings:
        return AppSettings(
            url_application=self.url_application,
            headless=self.headless,
            accounts=(
                AccountSettings(
                    email_user=self.email_user,
                    pin_user=self.pin_user,
                    nik=self.nik,
                    operator_id=self.operator_id,
                ),
            ),
            mask_nik=self.mask_nik,
        )


@dataclass(frozen=True, slots=True)
class RunContext:
    settings: AppSettings
    accounts: tuple[AccountRunContext, ...]
    run_id: str
    started_at: str
    run_dir: Path

    @classmethod
    def from_settings(
        cls,
        settings: AppSettings,
        *,
        now: datetime | None = None,
        suffix: str | None = None,
        reports_root: str | Path | None = None,
    ) -> RunContext:
        timestamp = now or datetime.now().astimezone()
        if timestamp.tzinfo is None:
            timestamp = timestamp.astimezone()

        resolved_suffix = suffix or uuid.uuid4().hex[:4]
        if _RUN_SUFFIX_PATTERN.fullmatch(resolved_suffix) is None:
            raise ValueError(
                "Run suffix must contain exactly four hexadecimal characters."
            )
        resolved_suffix = resolved_suffix.casefold()

        run_id = f"{timestamp:%Y%m%d_%H%M%S}_{resolved_suffix}"
        root = (
            Path(reports_root).expanduser()
            if reports_root
            else _PROJECT_ROOT / "reports"
        )
        if not root.is_absolute():
            root = _PROJECT_ROOT / root
        root = root.resolve()
        run_dir = (
            root
            / timestamp.strftime("%Y")
            / timestamp.strftime("%m")
            / timestamp.strftime("%d")
            / run_id
        )

        accounts = tuple(
            AccountRunContext.from_settings(settings, account)
            for account in settings.accounts
        )
        return cls(
            settings=settings,
            accounts=accounts,
            run_id=run_id,
            started_at=timestamp.isoformat(timespec="seconds"),
            run_dir=run_dir,
        )

    def primary_account(self) -> AccountRunContext | None:
        if not self.accounts:
            return None
        return self.accounts[0]
