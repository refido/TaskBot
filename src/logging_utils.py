import inspect
import os
import sys
import traceback
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger as _base_logger

from src.path_utils import build_dated_dir
from src.privacy import sanitize_log_value, sanitize_text

_ASCII_LEVEL_ICONS = {
    "TRACE": "T",
    "DEBUG": "D",
    "INFO": "I",
    "SUCCESS": "S",
    "WARNING": "W",
    "ERROR": "E",
    "CRITICAL": "C",
}
_DB_LOG_EVENT_PREFIXES = (
    "database.",
    "report.db_sync.",
    "report.batch_sync.",
    "db_management.",
)
_DB_LOG_EVENTS = {"account.report_db_sync_error"}
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_active_run_id = ""
_operator_id_context: ContextVar[str] = ContextVar("operator_id", default="")


def _apply_ascii_level_icons() -> None:
    for level_name, ascii_icon in _ASCII_LEVEL_ICONS.items():
        level = logger.level(level_name)
        logger.level(
            level_name,
            color=level.color,
            icon=ascii_icon,
        )


def _inject_default_event(record: dict[str, Any]) -> None:
    record["message"] = sanitize_text(record["message"])
    exception = record.get("exception")
    if exception is not None:
        exception_type = getattr(exception, "type", None)
        exception_value = getattr(exception, "value", None)
        exception_traceback = getattr(exception, "traceback", None)
        exception_name = getattr(exception_type, "__name__", "Exception")
        sanitized_exception = sanitize_text(exception_value)
        try:
            formatted_traceback = "".join(
                traceback.format_exception(
                    exception_type,
                    exception_value,
                    exception_traceback,
                )
            )
        except (TypeError, ValueError):
            formatted_traceback = f"{exception_name}: {exception_value}"
        record["message"] = sanitize_text(
            f"{record['message']} | {exception_name}: {sanitized_exception}"
        )
        record["extra"].setdefault("exception_type", exception_name)
        record["extra"].setdefault(
            "exception_traceback", sanitize_text(formatted_traceback)
        )
        # Prevent Loguru from serializing the original unsanitized exception.
        record["exception"] = None
    for key, value in tuple(record["extra"].items()):
        record["extra"][key] = sanitize_log_value(key, value)
    record["extra"].setdefault("event", "application.log")
    record["extra"].setdefault("run_id", _active_run_id)
    record["extra"].setdefault("operator_id", _operator_id_context.get())
    record["extra"].setdefault(
        "timestamp_iso", record["time"].isoformat(timespec="seconds")
    )


def _is_db_log_record(record: dict[str, Any]) -> bool:
    event = str(record["extra"].get("event", ""))
    return event in _DB_LOG_EVENTS or event.startswith(_DB_LOG_EVENT_PREFIXES)


def _is_application_log_record(record: dict[str, Any]) -> bool:
    return not _is_db_log_record(record)


logger = _base_logger.patch(_inject_default_event)


@contextmanager
def operator_logging_context(operator_id: str):
    """Bind one safe operator ID to all logs emitted by the current thread/context."""
    token = _operator_id_context.set(operator_id)
    try:
        yield
    finally:
        _operator_id_context.reset(token)


def configure_logging(
    log_dir: str = "reports",
    app_name: str = "taskbot",
    run_id: str | None = None,
    *,
    run_context: Any | None = None,
    run_dir: str | Path | None = None,
) -> dict[str, str]:
    """
    Configure production-ready logging:
    - Human-readable console output
    - Structured JSON lines output for storage/search/analytics
    """
    now_local = datetime.now().astimezone()
    context_run_id = str(getattr(run_context, "run_id", "") or "")
    resolved_run_id = (
        run_id
        or context_run_id
        or f"{now_local:%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:4]}"
    )

    context_run_dir = getattr(run_context, "run_dir", None)
    if run_dir is not None or context_run_dir is not None:
        root = Path(run_dir or context_run_dir).expanduser()
        if not root.is_absolute():
            root = _PROJECT_ROOT / root
        root = root.resolve()
    else:
        log_root = Path(log_dir).expanduser()
        if not log_root.is_absolute():
            log_root = _PROJECT_ROOT / log_root
        root = build_dated_dir(log_root.resolve(), now_local) / resolved_run_id
    root.mkdir(parents=True, exist_ok=True)
    database_dir = root / "database"
    database_dir.mkdir(parents=True, exist_ok=True)
    application_log_path = root / "application.log"
    json_log_path = root / "application.jsonl"
    db_json_log_path = database_dir / "database_events.jsonl"

    console_level = os.getenv("LOG_LEVEL", "INFO").upper()
    file_level = os.getenv("LOG_FILE_LEVEL", "DEBUG").upper()
    rotation = os.getenv("LOG_ROTATION", "25 MB")
    retention = os.getenv("LOG_RETENTION", "30 days")
    compression = os.getenv("LOG_COMPRESSION", "gz")
    log_line_format = (
        "{extra[timestamp_iso]} | {level:<8} | {extra[event]} | "
        "run_id={extra[run_id]} | operator_id={extra[operator_id]} | {message}"
    )

    global _active_run_id
    _active_run_id = resolved_run_id
    _apply_ascii_level_icons()
    logger.remove()
    logger.add(
        sys.stderr,
        level=console_level,
        enqueue=False,
        backtrace=False,
        diagnose=False,
        colorize=False,
        format=log_line_format,
    )
    logger.add(
        str(application_log_path),
        level=file_level,
        enqueue=True,
        backtrace=False,
        diagnose=False,
        colorize=False,
        format=log_line_format,
        rotation=rotation,
        retention=retention,
        compression=compression,
        filter=_is_application_log_record,
    )
    logger.add(
        str(json_log_path),
        level=file_level,
        enqueue=True,
        backtrace=False,
        diagnose=False,
        serialize=True,
        format=log_line_format,
        rotation=rotation,
        retention=retention,
        compression=compression,
        filter=_is_application_log_record,
    )
    logger.add(
        str(db_json_log_path),
        level=file_level,
        enqueue=True,
        backtrace=False,
        diagnose=False,
        serialize=True,
        format=log_line_format,
        rotation=rotation,
        retention=retention,
        compression=compression,
        filter=_is_db_log_record,
    )

    logger.bind(
        event="logging.configured",
        run_id=resolved_run_id,
        application_log_file=str(application_log_path),
        log_file=str(json_log_path),
        db_log_file=str(db_json_log_path),
        console_level=console_level,
        file_level=file_level,
    ).info(f"Structured logging is configured: {json_log_path}")

    return {
        "run_id": resolved_run_id,
        "run_dir": str(root),
        "application_log_path": str(application_log_path),
        "json_log_path": str(json_log_path),
        "db_json_log_path": str(db_json_log_path),
    }


def log_print(
    *values: Any,
    sep: str = " ",
    end: str = "\n",
    file: Any = None,
    flush: bool = False,
    level: str = "INFO",
    event: str = "application.log",
    **fields: Any,
) -> None:
    """
    Compatibility bridge for legacy print-style calls during migration.
    """
    del file, flush  # kept for print-signature compatibility

    message = sep.join(str(value) for value in values)
    if end and end != "\n":
        message += end

    caller = inspect.currentframe().f_back
    source_module = caller.f_globals.get("__name__", "unknown") if caller else "unknown"
    source_function = caller.f_code.co_name if caller else "unknown"
    source_line = caller.f_lineno if caller else -1

    enriched_fields = {
        "source_module": source_module,
        "source_function": source_function,
        "source_line": source_line,
    }
    enriched_fields.update(fields)

    logger.bind(event=event, **enriched_fields).log(level.upper(), message)
    del caller
