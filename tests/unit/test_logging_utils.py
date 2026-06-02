import json
from pathlib import Path

from src.logging_utils import configure_logging, logger


def _jsonl_events(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8") as file_handle:
        return [
            json.loads(line)["record"]["extra"]["event"]
            for line in file_handle
            if line.strip()
        ]


def test_configure_logging_writes_db_events_to_separate_jsonl(tmp_path):
    metadata = configure_logging(
        log_dir=str(tmp_path),
        app_name="unit",
        run_id="run-1",
    )

    logger.bind(event="application.event").info("application event")
    logger.bind(event="database.ensure.started").info("database event")
    logger.bind(event="report.db_sync.failed").error("report db event")
    logger.bind(event="account.report_db_sync_error").error("account db event")
    logger.complete()

    app_log_path = Path(metadata["json_log_path"])
    db_log_path = Path(metadata["db_json_log_path"])

    assert app_log_path.name == "unit_run-1.jsonl"
    assert db_log_path.name == "dblog_run-1.jsonl"
    assert db_log_path.parent == app_log_path.parent

    app_events = _jsonl_events(app_log_path)
    db_events = _jsonl_events(db_log_path)

    assert "application.event" in app_events
    assert "database.ensure.started" not in app_events
    assert "report.db_sync.failed" not in app_events
    assert "account.report_db_sync_error" not in app_events

    assert "database.ensure.started" in db_events
    assert "report.db_sync.failed" in db_events
    assert "account.report_db_sync_error" in db_events
    assert "application.event" not in db_events
