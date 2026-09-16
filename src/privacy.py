from __future__ import annotations

import re
from collections.abc import Mapping
from threading import Lock
from typing import Any

_NIK_PATTERN = re.compile(r"(?<!\d)(\d{6})\d{4}(\d{6})(?!\d)")
_EMAIL_PATTERN = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_LABELED_SECRET_PATTERN = re.compile(
    r"(?i)\b(pin|password|token|cookie|authorization|secret)\b"
    r"\s*[:=]\s*([^\s,;]+)"
)
_mask_nik = True
_private_values: set[str] = set()
_private_values_lock = Lock()


def set_nik_masking(enabled: bool) -> None:
    if not isinstance(enabled, bool):
        raise TypeError("NIK masking mode must be boolean")
    global _mask_nik
    _mask_nik = enabled


def nik_masking_enabled() -> bool:
    return _mask_nik


def register_private_values(*values: object) -> None:
    """Register runtime credentials that must never appear in public output."""
    normalized = {
        str(value) for value in values if value is not None and str(value)
    }
    if not normalized:
        return
    with _private_values_lock:
        _private_values.update(normalized)


def display_nik(value: object) -> str:
    text = str(value)
    if not _mask_nik:
        return text
    match = re.fullmatch(r"(\d{6})\d{4}(\d{6})", text)
    if match is None:
        return text
    return f"{match.group(1)}****{match.group(2)}"


def artifact_nik(value: object) -> str:
    """Render a NIK for a cross-platform artifact filename."""
    return display_nik(value).replace("*", "x")


def sanitize_text(value: object) -> str:
    text = str(value)
    text = _EMAIL_PATTERN.sub("<redacted-email>", text)
    text = _LABELED_SECRET_PATTERN.sub(r"\1=<redacted>", text)
    with _private_values_lock:
        private_values = sorted(_private_values, key=len, reverse=True)
    for private_value in private_values:
        text = text.replace(private_value, "<redacted>")
    if _mask_nik:
        text = _NIK_PATTERN.sub(r"\1****\2", text)
    return text


def sanitize_log_value(key: str, value: Any) -> Any:
    normalized_key = key.casefold()
    if any(
        marker in normalized_key
        for marker in (
            "pin",
            "password",
            "token",
            "secret",
            "cookie",
            "authorization",
            "credential",
            "session_value",
        )
    ):
        return "<redacted>"
    if "email" in normalized_key or normalized_key in {"operator", "username"}:
        return "<redacted-email>" if "@" in str(value) else value
    if "nik" in normalized_key:
        if isinstance(value, (list, tuple, set)):
            return [display_nik(item) for item in value]
        return display_nik(value)
    if isinstance(value, Mapping):
        return {
            str(nested_key): sanitize_log_value(str(nested_key), nested_value)
            for nested_key, nested_value in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [sanitize_log_value(key, item) for item in value]
    if isinstance(value, str):
        return sanitize_text(value)
    return value


def sanitize_public_value(value: Any, *, key: str = "") -> Any:
    """Recursively sanitize report payload values and dictionary keys."""
    if isinstance(value, Mapping):
        return {
            sanitize_text(nested_key): sanitize_public_value(
                nested_value,
                key=str(nested_key),
            )
            for nested_key, nested_value in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [sanitize_public_value(item, key=key) for item in value]
    return sanitize_log_value(key, value)


def public_operator(value: str) -> str:
    return "<redacted-email>" if "@" in value else value


def operator_folder(value: str) -> str:
    """Compatibility helper that never derives folder identity from credentials."""
    return "operator_01" if "@" in value else (value or "unknown_operator")
