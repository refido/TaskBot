from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class AccountSettings:
    email_user: str
    pin_user: str
    nik: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AppSettings:
    url_application: str
    accounts: tuple[AccountSettings, ...]

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        load_env_file: bool = True,
    ) -> "AppSettings":
        if load_env_file:
            load_dotenv()

        source = os.environ if environ is None else environ
        url_application = source.get("URL_APPLICATION", "").strip()
        accounts = tuple(cls._load_accounts(source))
        return cls(url_application=url_application, accounts=accounts)

    def primary_account(self) -> AccountSettings | None:
        if not self.accounts:
            return None
        return self.accounts[0]

    def for_account(self, account: AccountSettings) -> "AppSettings":
        return AppSettings(
            url_application=self.url_application,
            accounts=(account,),
        )

    @classmethod
    def _load_accounts(cls, environ: Mapping[str, str]) -> list[AccountSettings]:
        numbered_accounts = cls._load_numbered_accounts(environ)
        if numbered_accounts:
            return numbered_accounts

        single_email = environ.get("EMAIL", "").strip()
        single_pin = environ.get("PIN", "").strip()
        single_nik = cls._parse_nik_list(environ.get("NIK", ""))

        if single_email or single_pin or single_nik:
            return [
                AccountSettings(
                    email_user=single_email,
                    pin_user=single_pin,
                    nik=single_nik,
                )
            ]

        return []

    @classmethod
    def _load_numbered_accounts(
        cls, environ: Mapping[str, str]
    ) -> list[AccountSettings]:
        suffixes = cls._collect_numbered_suffixes(environ)
        accounts: list[AccountSettings] = []

        for suffix in suffixes:
            email = environ.get(f"EMAIL_{suffix}", "").strip()
            pin = environ.get(f"PIN_{suffix}", "").strip()
            nik = cls._parse_nik_list(environ.get(f"NIK_{suffix}", ""))

            if not email and not pin and not nik:
                continue

            if not email or not pin:
                raise ValueError(
                    f"Account {suffix} must define both EMAIL_{suffix} and PIN_{suffix}."
                )

            accounts.append(
                AccountSettings(
                    email_user=email,
                    pin_user=pin,
                    nik=nik,
                )
            )

        return accounts

    @staticmethod
    def _collect_numbered_suffixes(environ: Mapping[str, str]) -> list[str]:
        pattern = re.compile(r"^(EMAIL|PIN|NIK)_(\d+)$")
        suffixes = {
            match.group(2)
            for key in environ
            if (match := pattern.match(key))
        }
        return sorted(suffixes, key=lambda value: int(value))

    @staticmethod
    def _parse_nik_list(raw_nik: str) -> tuple[str, ...]:
        return tuple(nik.strip() for nik in raw_nik.split(",") if nik.strip())
