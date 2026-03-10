import os
import re
from dataclasses import dataclass
from typing import List

from dotenv import load_dotenv


@dataclass(frozen=True)
class AccountConfig:
    email_user: str
    pin_user: str
    nik: List[str]


class Config:
    def __init__(self):
        load_dotenv()
        self.url_application: str = os.getenv("URL_APPLICATION", "").strip()

        self.accounts: List[AccountConfig] = self._load_accounts()

        # Backward-compatible attributes used by existing workflow classes.
        primary_account = (
            self.accounts[0] if self.accounts else AccountConfig("", "", [])
        )
        self.email_user: str = primary_account.email_user
        self.pin_user: str = primary_account.pin_user
        self.nik: List[str] = list(primary_account.nik)

    def account_configs(self) -> List["Config"]:
        """Build one Config object per account for isolated threaded execution."""
        if not self.accounts:
            return []

        return [self._build_account_config(account) for account in self.accounts]

    def _build_account_config(self, account: AccountConfig) -> "Config":
        config = Config.__new__(Config)
        config.url_application = self.url_application
        config.accounts = [account]
        config.email_user = account.email_user
        config.pin_user = account.pin_user
        config.nik = list(account.nik)
        return config

    def _load_accounts(self) -> List[AccountConfig]:
        numbered_accounts = self._load_numbered_accounts()
        if numbered_accounts:
            return numbered_accounts

        # Backward-compatible single-account format.
        single_email = os.getenv("EMAIL", "").strip()
        single_pin = os.getenv("PIN", "").strip()
        single_nik = self._parse_nik_list(os.getenv("NIK", ""))

        if single_email or single_pin or single_nik:
            return [
                AccountConfig(
                    email_user=single_email,
                    pin_user=single_pin,
                    nik=single_nik,
                )
            ]

        return []

    def _load_numbered_accounts(self) -> List[AccountConfig]:
        suffixes = self._collect_numbered_suffixes()
        accounts: List[AccountConfig] = []

        for suffix in suffixes:
            email = os.getenv(f"EMAIL_{suffix}", "").strip()
            pin = os.getenv(f"PIN_{suffix}", "").strip()
            nik = self._parse_nik_list(os.getenv(f"NIK_{suffix}", ""))

            # Ignore fully empty entries (e.g., skipped index).
            if not email and not pin and not nik:
                continue

            if not email or not pin:
                raise ValueError(
                    f"Account {suffix} must define both EMAIL_{suffix} and PIN_{suffix}."
                )

            accounts.append(AccountConfig(email_user=email, pin_user=pin, nik=nik))

        return accounts

    @staticmethod
    def _collect_numbered_suffixes() -> List[str]:
        pattern = re.compile(r"^(EMAIL|PIN|NIK)_(\d+)$")
        suffixes = set()

        for key in os.environ:
            match = pattern.match(key)
            if match:
                suffixes.add(match.group(2))

        return sorted(suffixes, key=lambda value: int(value))

    @staticmethod
    def _parse_nik_list(raw_nik: str) -> List[str]:
        return [n.strip() for n in raw_nik.split(",") if n.strip()]
