from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from nik_parser import NIKResult, normalise_nik


class PrecheckAction(StrEnum):
    CONTINUE = "continue"
    SKIP = "skip"
    RESTART_AFTER_UPDATE = "restart_after_update"


class CustomerState(StrEnum):
    SESSION_EXPIRED = "session_expired"
    UNDER_17 = "under_17"
    CUSTOMER_TYPE = "customer_type"
    NIB_REMINDER = "nib_reminder"
    CONSENT = "consent"
    UPDATE_REQUIRED = "update_required"
    UPDATE_FORM = "update_form"
    UPDATE_CONFIRMATION = "update_confirmation"
    UPDATE_SUCCESS = "update_success"
    TRANSACTION_READY = "transaction_ready"
    NOT_REGISTERED = "not_registered"
    REGISTRATION_REQUEST_LIMITED = "registration_request_limited"
    INVALID_REGISTERED_NIK = "invalid_registered_nik"
    CANNOT_TRANSACT_AT_BASE = "cannot_transact_at_base"
    UNUSUAL_TRANSACTION = "unusual_transaction"
    UNKNOWN = "unknown"


class CustomerUpdateFailedError(RuntimeError):
    pass


class CustomerUpdateLoopError(CustomerUpdateFailedError):
    pass


class UnexpectedCustomerStateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CustomerUpdateData:
    nik: str
    city: str
    birth_day: int
    birth_month: int
    birth_year: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "nik", normalise_nik(self.nik))
        if not isinstance(self.city, str) or not self.city.strip():
            raise ValueError("Customer city is required")
        object.__setattr__(self, "city", self.city.strip())
        try:
            date(self.birth_year, self.birth_month, self.birth_day)
        except (TypeError, ValueError) as exc:
            raise ValueError("Customer birth date is invalid") from exc


def customer_update_data_from_nik(result: NIKResult) -> CustomerUpdateData:
    return CustomerUpdateData(
        nik=result.original_nik,
        city=result.kota_kabupaten,
        birth_day=result.birth_date.day,
        birth_month=result.birth_date.month,
        birth_year=result.birth_date.year,
    )


def indonesian_month_name(month: int) -> str:
    names = (
        "Januari",
        "Februari",
        "Maret",
        "April",
        "Mei",
        "Juni",
        "Juli",
        "Agustus",
        "September",
        "Oktober",
        "November",
        "Desember",
    )
    if isinstance(month, bool) or not isinstance(month, int) or not 1 <= month <= 12:
        raise ValueError("Birth month must be between 1 and 12")
    return names[month - 1]
