import csv
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main as taskbot_main
import src.web.reporter as reporter_module
from src.privacy import register_private_values, set_nik_masking


@pytest.mark.parametrize("summary_failure", ["write", "analytics"])
def test_summary_failure_preserves_terminal_row_and_db_queue(
    monkeypatch, tmp_path, request, summary_failure
):
    reporter = reporter_module.TransactionReporter(
        out_dir=str(tmp_path), operator_id="operator_01"
    )
    synced_batches = []
    reporter.configure_batch_sync(synced_batches.append, batch_size=10)
    failure = RuntimeError(f"summary {summary_failure} failed")
    failing_summary = Mock(side_effect=failure)
    if summary_failure == "write":
        monkeypatch.setattr(reporter.file_writer, "write_json", failing_summary)
    else:
        monkeypatch.setattr(
            reporter_module.MetricsCalculator, "get_analytics", failing_summary
        )

    records = []
    sink_id = reporter_module.logger.add(lambda message: records.append(message.record))
    request.addfinalizer(lambda: reporter_module.logger.remove(sink_id))
    reporter.complete("3174", reporter.start_item("3174"), puzzle_solved=True)

    failing_summary.assert_called_once()
    assert len(reporter.rows) == 1
    assert reporter.rows[0].status == "completed"
    expected = reporter.file_writer.public_row_payload(reporter.rows[0])
    assert json.loads(reporter.jsonl_path.read_text(encoding="utf-8")) == expected
    with reporter.csv_path.open(newline="", encoding="utf-8") as stream:
        csv_rows = list(csv.DictReader(stream))
    assert len(csv_rows) == 1
    assert csv_rows[0]["nik"] == expected["nik"]
    assert csv_rows[0]["status"] == "completed"
    # Originally both failures left this queue empty despite persisted files.
    assert reporter._pending_batch_rows == [reporter.rows[0]]
    assert any(
        record["extra"].get("event") == "report.summary_failed"
        for record in records
    )
    reporter.flush_pending_batches()
    reporter.flush_pending_batches()
    assert synced_batches == [(reporter.rows[0],)]
    assert reporter._pending_batch_rows == []


@pytest.fixture
def durable_reporter(tmp_path):
    return reporter_module.TransactionReporter(
        out_dir=str(tmp_path), operator_id="operator_01"
    )


def test_terminal_row_persists_then_syncs_before_summary(
    monkeypatch, request, durable_reporter
):
    reporter = durable_reporter
    events = []
    batches = []

    def sync(batch):
        events.append("db_sync")
        batches.append(batch)

    reporter.configure_batch_sync(sync, batch_size=1)

    def trace(target, attribute, event):
        original = getattr(target, attribute)

        def call(*args, **kwargs):
            if event == "csv":
                assert reporter.rows == [args[0]]
            events.append(event)
            return original(*args, **kwargs)

        monkeypatch.setattr(target, attribute, call)

    trace(reporter.file_writer, "_append_to_csv", "csv")
    trace(reporter.file_writer, "_append_to_jsonl", "jsonl")
    trace(reporter, "_queue_row_for_batch_sync", "enqueue")
    trace(reporter, "_write_meta", "summary")
    sink_id = reporter_module.logger.add(
        lambda message: events.append("row_recorded"),
        filter=lambda record: record["extra"].get("event") == "report.row_recorded",
    )
    request.addfinalizer(lambda: reporter_module.logger.remove(sink_id))

    reporter.complete("3174", reporter.start_item("3174"), puzzle_solved=True)
    reporter.flush_pending_batches()
    reporter.flush_pending_batches()

    assert events == ["csv", "jsonl", "enqueue", "db_sync", "summary", "row_recorded"]
    assert batches == [(reporter.rows[0],)]
    assert reporter._pending_batch_rows == []
    assert json.loads(reporter.jsonl_path.read_text(encoding="utf-8")) == (
        reporter.file_writer.public_row_payload(batches[0][0])
    )
    summary = json.loads(reporter.meta_path.read_text(encoding="utf-8"))
    assert summary["counts"] == {"completed": 1, "total": 1}


@pytest.mark.parametrize("summary_fails", [False, True])
def test_terminal_reporting_without_db_sync(monkeypatch, durable_reporter, summary_fails):
    reporter = durable_reporter
    summary = Mock(
        wraps=reporter._write_meta,
        side_effect=RuntimeError("summary unavailable") if summary_fails else None,
    )
    monkeypatch.setattr(reporter, "_write_meta", summary)
    sync = Mock(side_effect=AssertionError("disabled DB sync must not run"))
    monkeypatch.setattr(reporter, "_sync_complete_batches", sync)

    reporter.complete("3174", reporter.start_item("3174"))
    reporter.flush_pending_batches()

    summary.assert_called_once()
    sync.assert_not_called()
    assert reporter._batch_sync_callback is None
    assert reporter._pending_batch_rows == []
    assert len(reporter.rows) == 1
    assert json.loads(reporter.jsonl_path.read_text(encoding="utf-8"))["status"] == "completed"


@pytest.mark.parametrize("summary_fails", [False, True])
@pytest.mark.parametrize("enqueue_before_failure", [False, True])
def test_enqueue_failure_propagates_without_reenqueue_and_still_attempts_summary(
    monkeypatch, durable_reporter, summary_fails, enqueue_before_failure
):
    reporter = durable_reporter
    batches = []
    reporter.configure_batch_sync(batches.append, batch_size=10)
    failure = RuntimeError("DB enqueue failed")

    def fail_enqueue(row):
        if enqueue_before_failure:
            reporter._pending_batch_rows.append(row)
        raise failure

    enqueue = Mock(side_effect=fail_enqueue)
    summary = Mock(
        wraps=reporter._write_meta,
        side_effect=RuntimeError("summary also failed") if summary_fails else None,
    )
    monkeypatch.setattr(reporter, "_queue_row_for_batch_sync", enqueue)
    monkeypatch.setattr(reporter, "_write_meta", summary)

    with pytest.raises(RuntimeError) as caught:
        reporter.complete("3174", reporter.start_item("3174"))

    assert caught.value is failure
    enqueue.assert_called_once_with(reporter.rows[0])
    summary.assert_called_once()
    assert len(reporter.rows) == 1
    assert json.loads(reporter.jsonl_path.read_text(encoding="utf-8"))["status"] == "completed"
    assert reporter._pending_batch_rows == (reporter.rows if enqueue_before_failure else [])
    reporter.flush_pending_batches()
    reporter.flush_pending_batches()
    assert batches == ([(reporter.rows[0],)] if enqueue_before_failure else [])


def test_db_callback_failure_retains_queue_even_when_summary_also_fails(
    monkeypatch, durable_reporter
):
    reporter = durable_reporter
    sync = Mock(side_effect=[RuntimeError("DB offline"), None, None])
    reporter.configure_batch_sync(sync, batch_size=1)
    summary = Mock(side_effect=RuntimeError("summary unavailable"))
    monkeypatch.setattr(reporter.file_writer, "write_json", summary)

    for nik in ("3174", "3275"):
        reporter.complete(nik, reporter.start_item(nik))

    assert summary.call_count == 2
    assert reporter._batch_sync_failed is True
    assert reporter._pending_batch_rows == reporter.rows
    sync.assert_called_once_with((reporter.rows[0],))
    reporter.flush_pending_batches()
    reporter.flush_pending_batches()
    assert [call.args[0] for call in sync.call_args_list] == [
        (reporter.rows[0],), (reporter.rows[0],), (reporter.rows[1],),
    ]
    assert reporter._pending_batch_rows == []
    assert reporter._batch_sync_failed is False


@pytest.mark.parametrize("file_format", ["csv", "jsonl"])
def test_terminal_file_failure_propagates_and_does_not_enqueue(
    monkeypatch, durable_reporter, file_format
):
    reporter = durable_reporter
    sync = Mock()
    reporter.configure_batch_sync(sync, batch_size=1)
    previous_summary = reporter.meta_path.read_bytes()
    failure = OSError(f"{file_format} persistence failed")
    monkeypatch.setattr(
        reporter.file_writer, f"_append_to_{file_format}", Mock(side_effect=failure)
    )
    summary = Mock(wraps=reporter._write_meta)
    enqueue = Mock(wraps=reporter._queue_row_for_batch_sync)
    monkeypatch.setattr(reporter, "_write_meta", summary)
    monkeypatch.setattr(reporter, "_queue_row_for_batch_sync", enqueue)

    with pytest.raises(OSError) as caught:
        reporter.complete("3174", reporter.start_item("3174"))

    assert caught.value is failure
    assert len(reporter.rows) == 1  # Existing memory-first behavior is preserved.
    assert reporter._pending_batch_rows == []
    enqueue.assert_not_called()
    summary.assert_not_called()
    reporter.flush_pending_batches()
    sync.assert_not_called()
    assert reporter.meta_path.read_bytes() == previous_summary
    assert reporter.jsonl_path.read_text(encoding="utf-8") == ""
    with reporter.csv_path.open(newline="", encoding="utf-8") as stream:
        csv_rows = list(csv.DictReader(stream))
    # CSV and JSONL are sequential writes, not an atomic pair.
    assert len(csv_rows) == (1 if file_format == "jsonl" else 0)


def test_sequential_terminal_rows_rebuild_summary_without_duplicate_enqueue(
    monkeypatch, durable_reporter
):
    reporter = durable_reporter
    batches = []
    reporter.configure_batch_sync(batches.append, batch_size=2)
    original_write = reporter.file_writer.write_json
    writes = 0

    def write_summary(path, payload):
        nonlocal writes
        writes += 1
        if writes == 1:
            raise OSError("first summary write failed")
        return original_write(path, payload)

    monkeypatch.setattr(reporter.file_writer, "write_json", write_summary)
    enqueue = Mock(wraps=reporter._queue_row_for_batch_sync)
    monkeypatch.setattr(reporter, "_queue_row_for_batch_sync", enqueue)

    reporter.complete("3174", reporter.start_item("3174"))
    reporter.skip("3275", reporter.start_item("3275"), skip_type="quota")
    reporter.error("3376", reporter.start_item("3376"), exc=RuntimeError("failed sale"))
    reporter.flush_pending_batches()
    reporter.flush_pending_batches()

    assert writes == 3
    assert enqueue.call_count == 3
    assert [call.args[0] for call in enqueue.call_args_list] == reporter.rows
    assert [len(batch) for batch in batches] == [2, 1]
    assert [row for batch in batches for row in batch] == reporter.rows
    assert reporter._pending_batch_rows == []
    persisted = [
        json.loads(line)
        for line in reporter.jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    assert persisted == [reporter.file_writer.public_row_payload(row) for row in reporter.rows]
    with reporter.csv_path.open(newline="", encoding="utf-8") as stream:
        assert len(list(csv.DictReader(stream))) == 3
    summary = json.loads(reporter.meta_path.read_text(encoding="utf-8"))
    assert summary["counts"] == {"completed": 1, "skipped_quota": 1, "error": 1, "total": 3}
    assert summary["analytics"]["summary"]["total_transactions"] == 3


def test_reporter_labels_network_and_application_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(reporter_module, "log_print", lambda *args, **kwargs: None)
    reporter = reporter_module.TransactionReporter(
        out_dir=str(tmp_path),
        operator_id="operator_01",
    )
    reporter._record_row = reporter.rows.append

    network_started_at = reporter.start_item("nik-network")
    try:
        raise RuntimeError("Page.goto: net::ERR_CONNECTION_RESET")
    except RuntimeError as exc:
        reporter.error("nik-network", network_started_at, exc=exc, url="https://app")

    application_started_at = reporter.start_item("nik-application")
    try:
        raise RuntimeError("Puzzle background image not found on the page.")
    except RuntimeError as exc:
        reporter.error(
            "nik-application",
            application_started_at,
            exc=exc,
            url="https://app",
        )

    rows_by_nik = {row.nik: row for row in reporter.rows}
    assert (
        rows_by_nik["nik-network"].error_label == reporter_module._NETWORK_ERROR_LABEL
    )
    assert (
        rows_by_nik["nik-application"].error_label
        == reporter_module._APPLICATION_ERROR_LABEL
    )

    analytics = reporter.get_analytics()
    assert analytics["error_analysis"]["error_labels"] == {
        reporter_module._APPLICATION_ERROR_LABEL: 1,
        reporter_module._NETWORK_ERROR_LABEL: 1,
    }
    assert reporter.get_error_niks_by_label() == {
        reporter_module._NETWORK_ERROR_LABEL: ["nik-network"],
        reporter_module._APPLICATION_ERROR_LABEL: ["nik-application"],
    }


def test_reporter_records_retry_report_without_bursting_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(reporter_module, "log_print", lambda *args, **kwargs: None)
    reporter = reporter_module.TransactionReporter(
        out_dir=str(tmp_path),
        operator_id="operator_01",
    )

    try:
        raise RuntimeError("Page.goto: net::ERR_CONNECTION_RESET")
    except RuntimeError as exc:
        reporter.record_retry(
            "3174",
            process="process_single_nik",
            trigger="general_error",
            attempt_number=1,
            retry_number=1,
            max_retries=2,
            exc=exc,
            url="https://app",
        )

    retry_report = reporter.get_retry_report()
    assert reporter.rows == []
    assert retry_report["operator"] == "operator_01"
    assert retry_report["operator_id"] == "operator_01"
    assert retry_report["run_id"] == reporter.run_id
    assert retry_report["total_retry_events"] == 1
    assert retry_report["total_retried_niks"] == 1
    assert retry_report["retried_niks"] == ["3174"]
    assert retry_report["by_process"] == {"process_single_nik": ["3174"]}
    assert retry_report["by_trigger"] == {"general_error": ["3174"]}
    assert retry_report["events"][0]["retry_number"] == 1
    assert retry_report["events"][0]["max_retries"] == 2
    assert (
        retry_report["events"][0]["error_label"] == reporter_module._NETWORK_ERROR_LABEL
    )
    persisted_retry = json.loads(
        reporter.retries_path.read_text(encoding="utf-8").splitlines()[0]
    )
    assert persisted_retry["run_id"] == reporter.run_id
    assert persisted_retry["operator_id"] == "operator_01"


def test_reporter_syncs_each_full_batch_and_flushes_the_final_remainder(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(reporter_module, "log_print", lambda *args, **kwargs: None)
    reporter = reporter_module.TransactionReporter(
        out_dir=str(tmp_path),
        operator_id="operator_01",
    )
    synced_batches: list[tuple[reporter_module.TransactionRow, ...]] = []
    reporter.configure_batch_sync(synced_batches.append, batch_size=100)

    for index in range(101):
        nik = str(index + 1)
        reporter.complete(nik, reporter.start_item(nik))

    assert [len(batch) for batch in synced_batches] == [100]
    assert [row.nik for row in synced_batches[0]] == [
        str(index) for index in range(1, 101)
    ]

    reporter.flush_pending_batches()

    assert [len(batch) for batch in synced_batches] == [100, 1]
    assert [row.nik for row in synced_batches[1]] == ["101"]


def test_run_account_uses_configured_skip_rate_limiter(monkeypatch):
    limiter_kwargs = {}

    class DummyLogger:
        def bind(self, **kwargs):
            return self

        def info(self, *args, **kwargs) -> None:
            return None

        def exception(self, *args, **kwargs) -> None:
            return None

    class FakeLimiter:
        def __init__(self, **kwargs) -> None:
            limiter_kwargs.update(kwargs)

    class FakeReporter:
        def __init__(self, operator: str) -> None:
            self.operator = operator

        def write_files(self) -> None:
            return None

        def print_summary(self) -> None:
            return None

    class FakeSession:
        def __init__(self, config) -> None:
            self.config = config

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def initialize_session(self) -> None:
            return None

        def require_page(self):
            return object()

    class FakeProcessor:
        def __init__(self, config, page, reporter, limiter) -> None:
            self.config = config
            self.page = page
            self.reporter = reporter
            self.limiter = limiter

        def process_all_niks(self) -> None:
            return None

    monkeypatch.setattr(taskbot_main, "logger", DummyLogger())
    monkeypatch.setattr(taskbot_main, "SkipRateLimiter", FakeLimiter)
    monkeypatch.setattr(taskbot_main, "TransactionReporter", FakeReporter)
    monkeypatch.setattr(taskbot_main, "BrowserSession", FakeSession)
    monkeypatch.setattr(taskbot_main, "TransactionProcessor", FakeProcessor)

    operator_id, is_successful = taskbot_main.run_account(
        SimpleNamespace(
            operator_id="operator_01",
            email_user="tester@example.com",
            nik=["3174"],
        )
    )

    assert operator_id == "operator_01"
    assert is_successful is True
    assert limiter_kwargs["max_skips"] == 8
    assert limiter_kwargs["window_seconds"] == 48
    assert limiter_kwargs["min_cooldown"] == 48
    assert limiter_kwargs["jitter_seconds"] == 5
    assert limiter_kwargs["customer_update_rate_limiter"] is None


def test_main_builds_configurable_shared_customer_update_limiter(monkeypatch):
    monkeypatch.setenv("CUSTOMER_UPDATE_MIN_INTERVAL_SECONDS", "1.75")
    monkeypatch.setenv("CUSTOMER_UPDATE_JITTER_SECONDS", "0.4")

    limiter = taskbot_main._build_customer_update_rate_limiter()

    assert limiter.min_interval_seconds == 1.75
    assert limiter.jitter_seconds == 0.4


def test_main_rejects_invalid_customer_update_rate(monkeypatch):
    monkeypatch.setenv("CUSTOMER_UPDATE_MIN_INTERVAL_SECONDS", "-1")

    with pytest.raises(ValueError, match="finite and non-negative"):
        taskbot_main._build_customer_update_rate_limiter()


def test_main_delegates_account_fanout_to_process_accounts(monkeypatch, tmp_path):
    calls = {"order": [], "logger_events": [], "complete": 0}

    class DummyLogger:
        def __init__(self):
            self.fields = {}

        def bind(self, **kwargs):
            self.fields = kwargs
            calls["logger_events"].append(kwargs.get("event"))
            return self

        def info(self, *args, **kwargs) -> None:
            return None

        def exception(self, *args, **kwargs) -> None:
            return None

        def complete(self) -> None:
            calls["complete"] += 1

    class FakeConfig:
        def __init__(self):
            calls["order"].append("config")
            self.run_context = SimpleNamespace(
                run_id="20260820_202115_4821",
                started_at="2026-08-20T20:21:15+07:00",
                run_dir=tmp_path / "20260820_202115_4821",
                settings=SimpleNamespace(mask_nik=True),
            )

        def account_configs(self):
            return [
                SimpleNamespace(
                    operator_id="operator_01",
                    email_user="tester@example.com",
                    nik=["3174"],
                    run_context=self.run_context,
                )
            ]

    def fake_configure_logging(*, run_context):
        calls["order"].append("logging")
        assert run_context.run_id == "20260820_202115_4821"
        return {
            "run_id": run_context.run_id,
            "json_log_path": str(run_context.run_dir / "application.jsonl"),
            "db_json_log_path": str(
                run_context.run_dir / "database" / "database_events.jsonl"
            ),
        }

    def fake_load_dotenv(*, dotenv_path):
        calls["order"].append("dotenv")
        calls["dotenv_path"] = dotenv_path

    def fake_process_accounts(
        account_configs, *, run_account, log, outcomes=None, max_concurrent_accounts=None
    ):
        calls["account_configs"] = account_configs
        calls["run_account"] = run_account
        calls["log"] = log
        assert outcomes == {"operator_01": {}}
        assert max_concurrent_accounts is None
        assert run_account.keywords["outcomes"] is outcomes
        return [("operator_01", True)]

    monkeypatch.setattr(taskbot_main, "configure_logging", fake_configure_logging)
    monkeypatch.setattr(taskbot_main, "load_dotenv", fake_load_dotenv)
    monkeypatch.setattr(taskbot_main, "logger", DummyLogger())
    monkeypatch.setattr(taskbot_main, "Config", FakeConfig)
    monkeypatch.setattr(taskbot_main, "process_accounts", fake_process_accounts)
    monkeypatch.setattr(taskbot_main, "_build_customer_update_rate_limiter", object)

    taskbot_main.main()

    assert len(calls["account_configs"]) == 1
    assert calls["account_configs"][0].email_user == "tester@example.com"
    assert calls["run_account"].func is taskbot_main.run_account
    assert calls["log"] is taskbot_main.logger
    assert calls["order"] == ["dotenv", "config", "logging"]
    assert calls["dotenv_path"].name == ".env"
    assert "run.started" in calls["logger_events"]
    assert "run.completed" in calls["logger_events"]
    assert calls["complete"] == 1
    run_meta = json.loads(
        (tmp_path / "20260820_202115_4821" / "run_meta.json").read_text(
            encoding="utf-8"
        )
    )
    assert run_meta["operators"] == ["operator_01"]
    assert "tester@example.com" not in json.dumps(run_meta)


def test_main_drains_queued_logs_when_startup_fails(monkeypatch, tmp_path):
    calls = {"complete": 0, "events": []}

    class DummyLogger:
        def bind(self, **kwargs):
            calls["events"].append(kwargs.get("event"))
            return self

        def info(self, *_args, **_kwargs) -> None:
            return None

        def exception(self, *_args, **_kwargs) -> None:
            return None

        def complete(self) -> None:
            calls["complete"] += 1

    class FailingConfig:
        def __init__(self):
            raise RuntimeError("configuration failed")

    monkeypatch.setattr(taskbot_main, "load_dotenv", lambda **_kwargs: None)
    monkeypatch.setattr(
        taskbot_main,
        "configure_logging",
        lambda: {
            "run_id": "20260820_202115_dead",
            "run_dir": str(tmp_path / "20260820_202115_dead"),
            "json_log_path": str(tmp_path / "application.jsonl"),
        },
    )
    monkeypatch.setattr(taskbot_main, "logger", DummyLogger())
    monkeypatch.setattr(taskbot_main, "Config", FailingConfig)

    with pytest.raises(RuntimeError, match="configuration failed"):
        taskbot_main.main()

    assert "run.failed" in calls["events"]
    assert calls["complete"] == 1
    run_meta = json.loads(
        (tmp_path / "20260820_202115_dead" / "run_meta.json").read_text(
            encoding="utf-8"
        )
    )
    assert run_meta["status"] == "failed"
    assert run_meta["operators"] == []


def test_reporter_write_files_preserves_snapshot_and_meta_schema(monkeypatch, tmp_path):
    monkeypatch.setattr(reporter_module, "log_print", lambda *args, **kwargs: None)

    reporter = reporter_module.TransactionReporter(
        out_dir=str(tmp_path),
        operator_id="operator_01",
    )
    started_at = reporter.start_item("3174")
    reporter.complete(
        "3174",
        started_at,
        url="https://example.test/app",
        puzzle_solved=True,
        puzzle_attempts=1,
    )

    reporter.write_files()

    assert reporter.csv_path.exists()
    assert reporter.jsonl_path.exists()
    assert reporter.meta_path.exists()
    assert reporter.final_json_path.exists()
    assert reporter.analytics_path.exists()

    snapshot_payload = json.loads(reporter.final_json_path.read_text(encoding="utf-8"))
    assert {
        "run_id",
        "operator",
        "operator_id",
        "run_started_at",
        "run_ended_at",
        "counts",
        "analytics",
        "retry_report",
        "workflow_summary",
        "items",
        "mapping_report",
        "mapping_error_report",
        "mapping_failed_puzzle_report",
        "nik_lists",
        "puzzle_stats_by_nik",
    } <= set(snapshot_payload)
    assert snapshot_payload["operator_id"] == "operator_01"
    assert snapshot_payload["counts"]["completed"] == 1
    assert snapshot_payload["mapping_report"]["successful"] == ["3174"]
    assert snapshot_payload["retry_report"]["total_retry_events"] == 0
    assert snapshot_payload["nik_lists"]["retried"] == []

    analytics_payload = json.loads(reporter.analytics_path.read_text(encoding="utf-8"))
    assert set(analytics_payload) == {
        "run_id",
        "operator_id",
        "summary",
        "performance",
        "puzzle_metrics",
        "breakdown_by_status",
        "skip_reasons",
        "error_analysis",
    }

    meta_payload = json.loads(reporter.meta_path.read_text(encoding="utf-8"))
    assert {
        "run_id",
        "operator",
        "operator_id",
        "started_at",
        "ended_at",
        "total_niks",
        "completed",
        "skipped",
        "failed",
        "customer_updates",
        "consent_encounters",
        "retries",
        "run_started_at",
        "run_ended_at",
        "counts",
        "analytics",
        "retry_report",
        "workflow_summary",
        "mapping_report",
        "mapping_error_report",
        "mapping_failed_puzzle_report",
        "nik_lists",
        "files",
        "paths",
    } <= set(meta_payload)
    assert meta_payload["files"]["csv"].endswith("items.csv")
    assert meta_payload["files"]["workflow_events"].endswith("workflow_events.jsonl")
    assert meta_payload["paths"]["run_dir"] == str(reporter.run_dir)
    assert meta_payload["retry_report"]["total_retry_events"] == 0
    assert "events" not in meta_payload["retry_report"]


def test_customer_identity_fields_follow_nik_through_reports_and_db_payload(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(reporter_module, "log_print", lambda *args, **kwargs: None)
    reporter = reporter_module.TransactionReporter(
        out_dir=str(tmp_path), operator_id="operator_01"
    )

    reporter.complete(
        "3174",
        reporter.start_item("3174"),
        nama_pengguna="John Doe",
        jenis_pengguna="Rumah Tangga",
    )

    row = reporter.rows[0]
    assert row.nama_pengguna == "John Doe"
    assert row.jenis_pengguna == "Rumah Tangga"

    jsonl_payload = json.loads(reporter.jsonl_path.read_text(encoding="utf-8"))
    jsonl_keys = list(jsonl_payload)
    nik_index = jsonl_keys.index("nik")
    assert jsonl_keys[nik_index : nik_index + 3] == [
        "nik",
        "nama_pengguna",
        "jenis_pengguna",
    ]
    assert jsonl_payload["nama_pengguna"] == "John Doe"
    assert jsonl_payload["jenis_pengguna"] == "Rumah Tangga"

    with reporter.csv_path.open(newline="", encoding="utf-8") as file_handle:
        csv_rows = list(csv.DictReader(file_handle))
        csv_fields = list(csv_rows[0])
    csv_nik_index = csv_fields.index("nik")
    assert csv_fields[csv_nik_index : csv_nik_index + 3] == [
        "nik",
        "nama_pengguna",
        "jenis_pengguna",
    ]
    assert csv_rows[0]["nama_pengguna"] == "John Doe"
    assert csv_rows[0]["jenis_pengguna"] == "Rumah Tangga"

    reporter.write_files()
    snapshot = json.loads(reporter.final_json_path.read_text(encoding="utf-8"))
    assert snapshot["items"][0]["nama_pengguna"] == "John Doe"
    assert snapshot["items"][0]["jenis_pengguna"] == "Rumah Tangga"

    db_payload = taskbot_main._database_report_payload(row)
    assert db_payload["nama_pengguna"] == "John Doe"
    assert db_payload["jenis_pengguna"] == "Rumah Tangga"

    reporter.skip_max_kuota(
        "3175",
        reporter.start_item("3175"),
        nama_pengguna="Jane Doe",
        jenis_pengguna="Usaha Mikro",
    )
    assert reporter.rows[-1].nama_pengguna == "Jane Doe"
    assert reporter.rows[-1].jenis_pengguna == "Usaha Mikro"

    reporter.complete("3176", reporter.start_item("3176"))
    assert reporter.rows[-1].nama_pengguna == ""
    assert reporter.rows[-1].jenis_pengguna == ""

    legacy_row = reporter_module.TransactionRow("3177", "completed", "operator_legacy")
    assert legacy_row.operator == "operator_legacy"
    assert legacy_row.nama_pengguna == ""
    assert legacy_row.jenis_pengguna == ""


def test_workflow_events_append_immediately_without_creating_terminal_rows(tmp_path):
    set_nik_masking(True)
    reporter = reporter_module.TransactionReporter(
        out_dir=str(tmp_path), operator_id="operator_01"
    )
    nik = "3573051108720003"
    reporter.record_workflow_event(nik, event="consent_detected", stage="precheck")
    reporter.record_workflow_event(
        nik, event="customer_update_success", stage="precheck"
    )
    reporter.record_workflow_event(
        nik, event="same_nik_restart_after_update", stage="transaction"
    )

    assert reporter.rows == []
    events = [
        json.loads(line)
        for line in reporter.workflow_events_path.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert [event["event"] for event in events] == [
        "consent_detected",
        "customer_update_success",
        "same_nik_restart_after_update",
    ]
    assert {event["nik"] for event in events} == {"357305****720003"}
    assert {event["operator"] for event in events} == {"operator_01"}
    assert {event["operator_id"] for event in events} == {"operator_01"}
    assert {event["run_id"] for event in events} == {reporter.run_id}
    summary = reporter.get_workflow_event_report()
    assert summary["total_events"] == 3
    assert summary["same_nik_restarts"] == 1


def test_mask_setting_controls_reported_nik_but_never_exposes_email(tmp_path):
    nik = "3573051108720003"
    try:
        set_nik_masking(False)
        reporter = reporter_module.TransactionReporter(
            out_dir=str(tmp_path / "raw"), operator_id="operator_01"
        )
        reporter.complete(nik, reporter.start_item(nik))
        raw_item = json.loads(reporter.jsonl_path.read_text(encoding="utf-8"))
        assert raw_item["nik"] == nik
        assert raw_item["operator"] == "operator_01"
        assert raw_item["operator_id"] == "operator_01"

        set_nik_masking(True)
        reporter = reporter_module.TransactionReporter(
            out_dir=str(tmp_path / "masked"), operator_id="operator_01"
        )
        reporter.complete(nik, reporter.start_item(nik))
        masked_item = json.loads(reporter.jsonl_path.read_text(encoding="utf-8"))
        assert masked_item["nik"] == "357305****720003"
        assert masked_item["operator"] == "operator_01"
        assert masked_item["operator_id"] == "operator_01"
    finally:
        set_nik_masking(True)


def test_two_operators_share_one_run_root_and_keep_distinct_safe_ids(tmp_path):
    run_context = SimpleNamespace(
        run_id="20260820_202115_4821",
        started_at="2026-08-20T20:21:15+07:00",
        run_dir=tmp_path / "2026" / "08" / "20" / "20260820_202115_4821",
    )
    first = reporter_module.TransactionReporter(
        run_context=run_context,
        operator_id="operator_01",
    )
    second = reporter_module.TransactionReporter(
        run_context=run_context,
        operator_id="operator_02",
    )

    assert (
        first.application_run_dir == second.application_run_dir == run_context.run_dir
    )
    assert first.run_id == second.run_id == run_context.run_id
    assert first.run_dir == run_context.run_dir / "operators" / "operator_01"
    assert second.run_dir == run_context.run_dir / "operators" / "operator_02"
    assert "@" not in str(first.run_dir)
    assert "@" not in str(second.run_dir)


def test_legacy_email_operator_never_becomes_report_identity_or_folder(tmp_path):
    reporter = reporter_module.TransactionReporter(
        out_dir=str(tmp_path),
        operator="tester@example.com",
    )

    assert reporter.operator_id == "operator_01"
    assert reporter.operator == "operator_01"
    assert "tester@example.com" not in str(reporter.run_dir)


def test_report_text_never_persists_registered_credentials(tmp_path):
    email = "private.operator@example.com"
    pin = "pin-987654"
    token = "token-value-123"
    register_private_values(email, pin, token)
    reporter = reporter_module.TransactionReporter(
        out_dir=str(tmp_path),
        operator_id="operator_01",
    )
    nik = "3573051108720003"

    try:
        raise RuntimeError(f"login failed for {email}; PIN={pin}; token={token}")
    except RuntimeError as exc:
        reporter.record_retry(
            nik,
            process="process_single_nik",
            trigger="general_error",
            attempt_number=1,
            retry_number=1,
            max_retries=2,
            exc=exc,
            url=f"https://example.test/?token={token}",
        )
        reporter.error(
            nik,
            reporter.start_item(nik),
            exc=exc,
            url=f"https://example.test/?pin={pin}",
        )
    reporter.write_files()

    persisted_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in reporter.run_dir.iterdir()
        if path.is_file()
    )
    assert email not in persisted_text
    assert pin not in persisted_text
    assert token not in persisted_text
    assert "operator_01" in persisted_text


def test_database_sync_rejects_a_skipped_per_nik_row(tmp_path):
    class FakeConnection:
        closed = False

        def close(self) -> None:
            self.closed = True

    class FakeManager:
        def sync_report_payloads(self, payloads, *, source, connection):
            payload_list = list(payloads)
            assert len(payload_list) == 1
            assert payload_list[0]["nik"] == "3573051108720003"
            assert "db-private-pin" not in payload_list[0]["reason"]
            assert connection is not None
            return SimpleNamespace(
                source=source,
                processed=1,
                inserted_or_updated=0,
                skipped=1,
            )

    syncer = taskbot_main.DatabaseReportSyncer()
    syncer._manager = FakeManager()
    syncer._database_ready = True
    syncer._connection = FakeConnection()
    reporter = SimpleNamespace(jsonl_path=tmp_path / "items.jsonl")
    row = reporter_module.TransactionRow(
        nik="3573051108720003",
        status="completed",
        run_id="20260820_202115_4821",
        operator_id="operator_01",
        reason="PIN=db-private-pin",
    )
    register_private_values("db-private-pin")

    with pytest.raises(RuntimeError, match="did not persist every terminal row"):
        syncer(reporter, [row])
