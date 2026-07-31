import inspect
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from loguru import logger as _base_logger

from src.path_utils import build_timestamped_run_dir

_ASCII_LEVEL_ICONS = {
    "TRACE": "T",
    "DEBUG": "D",
    "INFO": "I",
    "SUCCESS": "S",
    "WARNING": "W",
    "ERROR": "E",
    "CRITICAL": "C",
}
_DB_LOG_EVENT_PREFIXES = ("database.", "report.db_sync.", "db_management.")
_DB_LOG_EVENTS = {"account.report_db_sync_error"}


def _apply_ascii_level_icons() -> None:
    for level_name, ascii_icon in _ASCII_LEVEL_ICONS.items():
        level = logger.level(level_name)
        logger.level(
            level_name,
            color=level.color,
            icon=ascii_icon,
        )


def _inject_default_event(record: Dict[str, Any]) -> None:
    record["extra"].setdefault("event", "application.log")
    record["extra"].setdefault(
        "timestamp_iso", record["time"].isoformat(timespec="seconds")
    )


def _is_db_log_record(record: Dict[str, Any]) -> bool:
    event = str(record["extra"].get("event", ""))
    return event in _DB_LOG_EVENTS or event.startswith(_DB_LOG_EVENT_PREFIXES)


def _is_application_log_record(record: Dict[str, Any]) -> bool:
    return not _is_db_log_record(record)


logger = _base_logger.patch(_inject_default_event)


def configure_logging(
    log_dir: str = "reports/logs",
    app_name: str = "taskbot",
    run_id: str | None = None,
) -> Dict[str, str]:
    """
    Configure production-ready logging:
    - Human-readable console output
    - Structured JSON lines output for storage/search/analytics
    """
    resolved_run_id = run_id or os.getenv("RUN_ID") or uuid.uuid4().hex[:12]
    now_local = datetime.now().astimezone()

    root = build_timestamped_run_dir(Path(log_dir), now_local)
    root.mkdir(parents=True, exist_ok=True)
    json_log_path = root / f"{app_name}_{resolved_run_id}.jsonl"
    db_json_log_path = root / f"dblog_{resolved_run_id}.jsonl"

    console_level = os.getenv("LOG_LEVEL", "INFO").upper()
    file_level = os.getenv("LOG_FILE_LEVEL", "DEBUG").upper()
    rotation = os.getenv("LOG_ROTATION", "25 MB")
    retention = os.getenv("LOG_RETENTION", "30 days")
    compression = os.getenv("LOG_COMPRESSION", "gz")
    log_line_format = "{extra[timestamp_iso]} | {level:<8} | {extra[event]} | {message}"

    _apply_ascii_level_icons()
    logger.remove()
    logger.add(
        sys.stderr,
        level=console_level,
        enqueue=True,
        backtrace=False,
        diagnose=False,
        colorize=False,
        format=log_line_format,
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
        log_file=str(json_log_path),
        db_log_file=str(db_json_log_path),
        console_level=console_level,
        file_level=file_level,
    ).info("Structured logging is configured")

    return {
        "run_id": resolved_run_id,
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
