from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

from dotenv import load_dotenv

_OPERATOR_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


@dataclass(frozen=True, slots=True)
class AccountSettings:
    email_user: str
    pin_user: str
    nik: tuple[str, ...]
    operator_id: str = "operator_01"


@dataclass(frozen=True, slots=True)
class AppSettings:
    url_application: str
    accounts: tuple[AccountSettings, ...]
    headless: bool = True
    mask_nik: bool = True

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        load_env_file: bool = True,
    ) -> AppSettings:
        if load_env_file:
            load_dotenv()

        source = os.environ if environ is None else environ
        url_application = source.get("URL_APPLICATION", "").strip()
        accounts = tuple(cls._load_accounts(source))
        cls._validate_unique_operator_ids(accounts)
        return cls(
            url_application=url_application,
            accounts=accounts,
            headless=cls._parse_headless(source.get("HEADLESS", "")),
            mask_nik=cls._parse_mask(source.get("MASK", "")),
        )

    def primary_account(self) -> AccountSettings | None:
        if not self.accounts:
            return None
        return self.accounts[0]

    def for_account(self, account: AccountSettings) -> AppSettings:
        return AppSettings(
            url_application=self.url_application,
            accounts=(account,),
            headless=self.headless,
            mask_nik=self.mask_nik,
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
            operator_id = cls._validated_operator_id(
                environ.get("OPERATOR_ID", "").strip() or "operator_01",
                email=single_email,
                pin=single_pin,
                nik=single_nik,
                setting_name="OPERATOR_ID",
            )
            return [
                AccountSettings(
                    email_user=single_email,
                    pin_user=single_pin,
                    nik=single_nik,
                    operator_id=operator_id,
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

            operator_setting = f"OPERATOR_{suffix}_ID"
            operator_id = cls._validated_operator_id(
                environ.get(operator_setting, "").strip()
                or f"operator_{int(suffix):02d}",
                email=email,
                pin=pin,
                nik=nik,
                setting_name=operator_setting,
            )

            accounts.append(
                AccountSettings(
                    email_user=email,
                    pin_user=pin,
                    nik=nik,
                    operator_id=operator_id,
                )
            )

        return accounts

    @staticmethod
    def _collect_numbered_suffixes(environ: Mapping[str, str]) -> list[str]:
        account_pattern = re.compile(r"^(?:EMAIL|PIN|NIK)_(\d+)$")
        operator_pattern = re.compile(r"^OPERATOR_(\d+)_ID$")
        suffixes: set[str] = set()
        for key in environ:
            match = account_pattern.match(key) or operator_pattern.match(key)
            if match is not None:
                suffixes.add(match.group(1))
        return sorted(suffixes, key=lambda value: int(value))

    @staticmethod
    def _validated_operator_id(
        operator_id: str,
        *,
        email: str,
        pin: str,
        nik: tuple[str, ...],
        setting_name: str,
    ) -> str:
        if _OPERATOR_ID_PATTERN.fullmatch(operator_id) is None:
            raise ValueError(
                f"{setting_name} must start with a letter and contain only "
                "letters, numbers, underscores, or hyphens (maximum 64 characters)."
            )

        normalized_id = operator_id.casefold()
        private_values = {
            value.casefold() for value in (email, pin, *nik) if value.strip()
        }
        if normalized_id in private_values:
            raise ValueError(f"{setting_name} must not contain a credential value.")
        return operator_id

    @staticmethod
    def _validate_unique_operator_ids(accounts: tuple[AccountSettings, ...]) -> None:
        operator_ids = [account.operator_id.casefold() for account in accounts]
        if len(operator_ids) != len(set(operator_ids)):
            raise ValueError("Configured operator IDs must be unique.")

    @staticmethod
    def _parse_nik_list(raw_nik: str) -> tuple[str, ...]:
        return tuple(nik.strip() for nik in raw_nik.split(",") if nik.strip())

    @staticmethod
    def _parse_headless(raw_headless: str) -> bool:
        normalized = raw_headless.strip().casefold()
        if not normalized:
            return True
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
        raise ValueError("HEADLESS must be TRUE, FALSE, 1, or 0.")

    @staticmethod
    def _parse_mask(raw_mask: str) -> bool:
        normalized = raw_mask.strip().casefold()
        if not normalized:
            return True
        if normalized in {"1", "true", "on", "yes"}:
            return True
        if normalized in {"0", "false", "off", "no"}:
            return False
        raise ValueError("MASK must be true/1/on/yes or false/0/off/no.")
