from __future__ import annotations

from src.infrastructure.reporting.models import TransactionRow

_UNREGISTERED_SKIP_TYPE = "not_registered"
_UNREGISTERED_STATUS = f"skipped_{_UNREGISTERED_SKIP_TYPE}"
_UNREGISTERED_REASON_MARKERS = ("pelanggan tidak terdaftar", "not registered")
_FAILED_PUZZLE_SOLVE_STATUS = "failed_puzzle_solve"
_FAILED_PUZZLE_SOLVE_REASON = "CAPTCHA solving failed"
_FAILED_PUZZLE_SOLVE_REASON_MARKERS = ("captcha solving failed",)
_APPLICATION_ERROR_LABEL = "application_level_error"
_NETWORK_ERROR_LABEL = "network_level_error"
_NETWORK_ERROR_MARKERS = (
    "net::",
    "networkerror",
    "network error",
    "internet disconnected",
    "connection reset",
    "connection refused",
    "connection aborted",
    "connection closed",
    "connection timeout",
    "connection timed out",
    "dns",
    "name not resolved",
    "proxy error",
    "econnreset",
    "econnrefused",
    "enotfound",
    "etimedout",
    "err_connection",
    "err_internet_disconnected",
    "err_name_not_resolved",
    "ns_error_net_timeout",
)
_NEEDS_UPDATE_SKIP_TYPE = "need updated customer data"
_NEEDS_UPDATE_STATUS = f"skipped_{_NEEDS_UPDATE_SKIP_TYPE}"
_NEEDS_UPDATE_REASON = "Need updated customer data"
_NEEDS_UPDATE_REASON_MARKERS = (
    "perbarui data pelanggan",
    "needs data update",
    "need updated customer data",
    "close_perbarui_data_pelanggan_if_needed",
)
_UNDER_17_SKIP_TYPE = "nik is not yet 17 years old"
_UNDER_17_STATUS = f"skipped_{_UNDER_17_SKIP_TYPE}"
_UNDER_17_REASON = "NIK is not yet 17 years old"
_UNDER_17_REASON_MARKERS = (
    "nik belum 17 tahun",
    "not yet 17 years old",
)
_INVALID_REGISTERED_NIK_SKIP_TYPE = "The registered customer's NIK is invalid"
_INVALID_REGISTERED_NIK_STATUS = f"skipped_{_INVALID_REGISTERED_NIK_SKIP_TYPE}"
_INVALID_REGISTERED_NIK_REASON = "The registered customer's NIK is invalid"
_INVALID_REGISTERED_NIK_REASON_MARKERS = (
    "nik pelanggan yang didaftarkan tidak valid",
    "the registered customer's nik is invalid",
)
_CANNOT_TRANSACT_AT_BASE_SKIP_TYPE = "Customers Cannot Transact at This Base"
_CANNOT_TRANSACT_AT_BASE_STATUS = f"skipped_{_CANNOT_TRANSACT_AT_BASE_SKIP_TYPE}"
_CANNOT_TRANSACT_AT_BASE_REASON = "Customers Cannot Transact at This Base"
_CANNOT_TRANSACT_AT_BASE_REASON_MARKERS = (
    "pelanggan tidak dapat transaksi di pangkalan ini",
    "customers cannot transact at this base",
)
_UNUSUAL_TRANSACTION_OTHER_BASE_SKIP_TYPE = (
    "The customer's NIK indicates an unusual transaction at another base with an unusual distance and close time."
)
_UNUSUAL_TRANSACTION_OTHER_BASE_STATUS = (
    f"skipped_{_UNUSUAL_TRANSACTION_OTHER_BASE_SKIP_TYPE}"
)
_UNUSUAL_TRANSACTION_OTHER_BASE_REASON = (
    "The customer's NIK indicates an unusual transaction at another base with an unusual distance and close time."
)
_UNUSUAL_TRANSACTION_OTHER_BASE_REASON_MARKERS = (
    "nik pelanggan terindikasi transaksi tidak wajar di pangkalan lain dengan jarak tidak wajar dan waktu berdekatan",
    "the customer's nik indicates an unusual transaction at another base with an unusual distance and close time",
)


def normalize_error_reason(reason: str) -> str:
    """Build a short stable key for grouping errors."""
    if not reason:
        return "unknown_error"
    first_line = reason.splitlines()[0].strip()
    return first_line if first_line else "unknown_error"


def classify_error_label(exc: Exception, reason: str, error_details: str) -> str:
    """Classify whether an error came from the app layer or the network layer."""
    combined = "\n".join(
        part for part in (type(exc).__name__, reason, error_details) if part
    ).casefold()
    if any(marker in combined for marker in _NETWORK_ERROR_MARKERS):
        return _NETWORK_ERROR_LABEL
    return _APPLICATION_ERROR_LABEL


def reason_indicates_unregistered(reason: str) -> bool:
    normalized = reason.casefold() if reason else ""
    return any(marker in normalized for marker in _UNREGISTERED_REASON_MARKERS)


def reason_indicates_failed_puzzle_solve(reason: str) -> bool:
    normalized = reason.casefold() if reason else ""
    return any(marker in normalized for marker in _FAILED_PUZZLE_SOLVE_REASON_MARKERS)


def reason_indicates_needs_update(reason: str) -> bool:
    normalized = reason.casefold() if reason else ""
    return any(marker in normalized for marker in _NEEDS_UPDATE_REASON_MARKERS)


def reason_indicates_under_17(reason: str) -> bool:
    normalized = reason.casefold() if reason else ""
    return any(marker in normalized for marker in _UNDER_17_REASON_MARKERS)


def reason_indicates_invalid_registered_nik(reason: str) -> bool:
    normalized = reason.casefold() if reason else ""
    return any(
        marker in normalized for marker in _INVALID_REGISTERED_NIK_REASON_MARKERS
    )


def reason_indicates_cannot_transact_at_base(reason: str) -> bool:
    normalized = reason.casefold() if reason else ""
    return any(
        marker in normalized for marker in _CANNOT_TRANSACT_AT_BASE_REASON_MARKERS
    )


def reason_indicates_unusual_transaction_at_other_base(reason: str) -> bool:
    normalized = reason.casefold() if reason else ""
    return any(
        marker in normalized
        for marker in _UNUSUAL_TRANSACTION_OTHER_BASE_REASON_MARKERS
    )


def is_unregistered_row(row: TransactionRow) -> bool:
    if row.status == _UNREGISTERED_STATUS:
        return True
    if row.status != "error":
        return False
    return reason_indicates_unregistered(row.reason)
