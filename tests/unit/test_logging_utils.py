import json
from pathlib import Path

from src import logging_utils
from src.logging_utils import configure_logging, logger, operator_logging_context
from src.privacy import register_private_values, set_nik_masking


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

    with operator_logging_context("operator_01"):
        logger.bind(event="application.event").info("application event")
    logger.bind(event="database.ensure.started").info("database event")
    logger.bind(event="report.db_sync.failed").error("report db event")
    logger.bind(event="report.batch_sync.deferred").error("deferred db event")
    logger.bind(event="account.report_db_sync_error").error("account db event")
    logger.complete()

    app_log_path = Path(metadata["json_log_path"])
    db_log_path = Path(metadata["db_json_log_path"])

    assert app_log_path.name == "application.jsonl"
    assert Path(metadata["application_log_path"]).name == "application.log"
    assert db_log_path.name == "database_events.jsonl"
    assert db_log_path.parent == app_log_path.parent / "database"

    app_events = _jsonl_events(app_log_path)
    db_events = _jsonl_events(db_log_path)

    assert "application.event" in app_events
    assert "database.ensure.started" not in app_events
    assert "report.db_sync.failed" not in app_events
    assert "report.batch_sync.deferred" not in app_events
    assert "account.report_db_sync_error" not in app_events

    assert "database.ensure.started" in db_events
    assert "report.db_sync.failed" in db_events
    assert "report.batch_sync.deferred" in db_events
    assert "account.report_db_sync_error" in db_events
    assert "application.event" not in db_events

    app_records = [
        json.loads(line)["record"]
        for line in app_log_path.read_text(encoding="utf-8").splitlines()
    ]
    application_record = next(
        record
        for record in app_records
        if record["extra"]["event"] == "application.event"
    )
    assert application_record["extra"]["run_id"] == "run-1"
    assert application_record["extra"]["operator_id"] == "operator_01"


def test_logs_obey_mask_and_always_redact_credentials(tmp_path):
    try:
        set_nik_masking(False)
        metadata = configure_logging(
            log_dir=str(tmp_path), app_name="privacy", run_id="run-2"
        )
        logger.bind(
            event="privacy.test",
            nik="3573051108720003",
            operator="tester@example.com",
            operator_id="operator_01",
            pin="123456",
            session_cookie="private-cookie-value",
        ).info("NIK 3573051108720003 for tester@example.com")
        logger.complete()
        payload = json.loads(
            Path(metadata["json_log_path"]).read_text(encoding="utf-8").splitlines()[-1]
        )["record"]
        assert payload["extra"]["nik"] == "3573051108720003"
        assert payload["extra"]["operator"] == "<redacted-email>"
        assert payload["extra"]["pin"] == "<redacted>"
        assert payload["extra"]["session_cookie"] == "<redacted>"
        assert payload["extra"]["operator_id"] == "operator_01"
        assert "tester@example.com" not in payload["message"]
        assert "3573051108720003" in payload["message"]
    finally:
        set_nik_masking(True)


def test_relative_log_directory_is_anchored_to_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_utils, "_PROJECT_ROOT", tmp_path)

    metadata = configure_logging(
        log_dir="reports/logs",
        app_name="anchored",
        run_id="run-3",
    )
    logger.complete()

    app_log_path = Path(metadata["json_log_path"])
    assert app_log_path.is_absolute()
    assert app_log_path.is_relative_to(tmp_path / "reports" / "logs")
    assert app_log_path.exists()


def test_exception_and_nested_context_are_sanitized_before_serialization(tmp_path):
    pin = "private-pin-2468"
    token = "private-token-1357"
    register_private_values(pin, token)
    metadata = configure_logging(log_dir=str(tmp_path), run_id="private-run")

    try:
        raise RuntimeError(f"PIN={pin}; token={token}")
    except RuntimeError:
        logger.bind(
            event="privacy.exception",
            context={"pin": pin, "nested": {"token": token}},
        ).exception("Credential-bearing failure")
    logger.complete()

    persisted = Path(metadata["json_log_path"]).read_text(encoding="utf-8")
    assert pin not in persisted
    assert token not in persisted
    assert "<redacted>" in persisted
