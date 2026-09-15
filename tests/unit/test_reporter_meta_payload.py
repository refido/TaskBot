"""Metadata acquisition, schema and failure contracts around Reporter writes."""

import json
from collections import Counter
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import src.web.reporter as reporting
from src.infrastructure.reporting import analytics
from src.infrastructure.reporting.meta_payload import build_metadata_payload
from src.privacy import display_nik, nik_masking_enabled, set_nik_masking

START = "2026-08-20T12:00:00+00:00"
END = "2026-08-20T12:02:00+00:00"
NIK = "3573050101720003"
KEYS = (
    "run_id", "operator", "operator_id", "started_at", "ended_at", "total_niks",
    "completed", "skipped", "failed", "customer_updates", "consent_encounters",
    "retries", "run_started_at", "run_ended_at", "counts", "analytics",
    "retry_report", "workflow_summary", "nik_parsing_failures", "mapping_report",
    "mapping_error_report", "mapping_failed_puzzle_report", "nik_lists", "files", "paths",
)


@pytest.fixture
def reporter_factory(tmp_path, monkeypatch):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromisoformat(END)

    previous = nik_masking_enabled()
    monkeypatch.setattr(reporting, "now_iso", lambda: END)
    monkeypatch.setattr(analytics, "datetime", FrozenDatetime)

    def make(operator="operator_01"):
        return reporting.TransactionReporter(
            operator_id=operator,
            run_context=SimpleNamespace(
                run_id="fixed_run", started_at=START, run_dir=tmp_path / "fixed_run",
            ),
        )

    yield make
    set_nik_masking(previous)


def add_history(reporter):
    for status, reason in (
        ("completed", ""), ("error", "beta\ntrace"), ("error", "alpha"),
        ("error", "beta\nother"), ("failed_puzzle_solve", ""),
        ("skipped_out_of_stock", "stock"),
        ("skipped_nik_parsing_failed", "bad region"),
        ("skipped_nik_parsing_failed", "bad region"), ("custom", ""),
    ):
        reporter._record_row(reporting.TransactionRow(
            NIK, status, reason=reason, started_at=START, finished_at=END,
            duration_seconds=1.2345, error_label="Network" if reason == "alpha" else "",
        ))
    for _ in range(2):
        reporter.record_retry(
            NIK, process="sale", trigger="network", attempt_number=2,
            retry_number=1, max_retries=2,
        )
        reporter.record_workflow_event(NIK, event="customer_update_success")


def capture_payload(reporter, monkeypatch):
    writer = Mock()
    monkeypatch.setattr(reporter.file_writer, "write_json", writer)
    reporter._write_meta()
    writer.assert_called_once()
    assert writer.call_args.args[0] == reporter.meta_path
    return writer.call_args.args[1]


@pytest.mark.parametrize("primary_type", [None, RuntimeError, KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("log_stage", ["bind", "exception"])
def test_summary_error_logging_preserves_terminal_boundary(reporter_factory, monkeypatch, primary_type, log_stage):
    reporter = reporter_factory()
    primary = primary_type("queue failed") if primary_type else None
    monkeypatch.setattr(reporter, "_queue_row_for_batch_sync", Mock(side_effect=primary))
    monkeypatch.setattr(reporter, "_write_meta", Mock(side_effect=OSError("summary failed")))
    log = Mock()
    failure = RuntimeError("logger failed")
    if log_stage == "bind":
        def bind(**context):
            if context.get("event") == "report.summary_failed":
                raise failure
            return Mock()
        log.bind.side_effect = bind
    else:
        log.bind.return_value.exception.side_effect = failure
    monkeypatch.setattr(reporting, "logger", log)
    if primary:
        with pytest.raises(type(primary)) as caught:
            reporter.complete(NIK, START)
        assert caught.value is primary
    else:
        reporter.complete(NIK, START)
    assert len(reporter.rows) == 1
    assert reporter.rows[0].status == "completed"
    assert reporter.jsonl_path.read_text(encoding="utf-8").count("\n") == 1
    reporter._queue_row_for_batch_sync.assert_called_once()


@pytest.mark.parametrize("fatal_type", [KeyboardInterrupt, SystemExit])
def test_summary_logger_fatal_interruption_still_propagates(reporter_factory, monkeypatch, fatal_type):
    reporter = reporter_factory()
    monkeypatch.setattr(reporter, "_write_meta", Mock(side_effect=OSError("summary failed")))
    interruption = fatal_type("logging interrupted")
    log = Mock()
    log.bind.return_value.exception.side_effect = interruption
    monkeypatch.setattr(reporting, "logger", log)
    with pytest.raises(fatal_type) as caught:
        reporter.complete(NIK, START)
    assert caught.value is interruption
    assert len(reporter.rows) == 1


@pytest.mark.parametrize("operator", ["operator_01", "operator_02"])
@pytest.mark.parametrize("masked", [False, True])
@pytest.mark.parametrize("cached", [False, True])
def test_metadata_schema_and_cached_fallback_parity(
    reporter_factory, monkeypatch, operator, masked, cached,
):
    reporter = reporter_factory(operator)
    add_history(reporter)
    set_nik_masking(masked)
    if not cached:
        reporter.rows = list(reporter.rows)
    payload = capture_payload(reporter, monkeypatch)
    assert tuple(payload) == KEYS
    assert payload["run_id"] == "fixed_run"
    assert payload["operator"] == payload["operator_id"] == operator
    assert payload["started_at"] == payload["run_started_at"] == START
    assert payload["ended_at"] == payload["run_ended_at"] == END
    assert (payload["total_niks"], payload["completed"], payload["skipped"], payload["failed"]) == (9, 1, 3, 4)
    assert payload["customer_updates"] == 1
    assert payload["retries"] == 2
    assert payload["nik_parsing_failures"] == {"total": 2, "by_reason": {"bad region": [display_nik(NIK)]}}
    assert tuple(payload["mapping_error_report"]) == ("beta", "alpha")
    assert payload["mapping_error_report"]["beta"] == [display_nik(NIK)] * 2
    assert "events" not in payload["retry_report"]
    assert payload["retry_report"]["retried_niks"] == [reporter.retry_events[0].nik]
    assert payload["workflow_summary"]["total_events"] == 2
    assert payload["mapping_error_report"] is payload["nik_lists"]["errors_by_reason"]
    assert payload["mapping_failed_puzzle_report"] is payload["nik_lists"]["mapping_failed_puzzle_report"]
    assert tuple(payload["nik_lists"]) == (
        "failed", "failed_puzzle_solve", "successful", "skipped", "unregistered",
        "mapping_error_report", "mapping_failed_puzzle_report", "errors_by_label",
        "errors_by_reason", "other_statuses", "retried",
    )
    assert tuple(payload["files"]) == ("csv", "jsonl", "final_snapshot", "analytics", "workflow_events", "retries")
    assert payload["files"]["csv"] == str(reporter.csv_path)
    assert payload["paths"] == {
        "application_run_dir": str(reporter.application_run_dir), "run_dir": str(reporter.run_dir),
    }
    # Force the independent history path and compare exact ordered serialization.
    reporter._meta_cache_valid = False
    fallback = capture_payload(reporter, monkeypatch)
    assert json.dumps(payload) == json.dumps(fallback)


@pytest.mark.parametrize("mode", ["cached", "invalid", "replaced"])
def test_projection_counts_and_write_boundary(reporter_factory, monkeypatch, mode):
    reporter = reporter_factory()
    add_history(reporter)
    if mode == "invalid":
        reporter._meta_cache_valid = False
    elif mode == "replaced":
        reporter.rows = list(reporter.rows)
    calls = []

    def trace(target, name, label=None):
        original = getattr(target, name)

        def invoke(*args, **kwargs):
            calls.append(label or name)
            return original(*args, **kwargs)

        monkeypatch.setattr(target, name, invoke)

    for name in (
        "_meta_row_reports", "get_mapping_report", "get_mapping_error_report",
        "get_mapping_failed_puzzle_report", "_compact_retry_report", "_meta_workflow_report",
        "get_nik_parsing_failure_report", "get_error_niks_by_label", "get_other_status_niks_by_status",
    ):
        trace(reporter, name)
    trace(reporting.MetricsCalculator, "get_summary")
    trace(reporting.MetricsCalculator, "get_analytics")
    trace(reporting, "now_iso", "clock")
    trace(reporter.file_writer, "write_json", "write")
    reporter._write_meta()
    expected = ["_meta_row_reports"] if mode == "cached" else [
        "get_mapping_report", "get_mapping_error_report", "get_mapping_failed_puzzle_report",
    ]
    # get_analytics itself asks the calculator for its summary once more.
    expected += ["_compact_retry_report", "get_summary", "_meta_workflow_report", "clock", "get_analytics", "get_summary"]
    if mode != "cached":
        expected += ["get_nik_parsing_failure_report", "get_error_niks_by_label", "get_other_status_niks_by_status"]
    assert Counter(calls) == Counter(expected + ["write"])
    assert calls[-1] == "write"  # All projections finish before serialization starts.


@pytest.mark.parametrize("entry", ["direct", "compatibility", "terminal"])
@pytest.mark.parametrize("failure_stage", ["analytics", "write", "builder"])
def test_metadata_failure_boundaries(reporter_factory, monkeypatch, entry, failure_stage):
    reporter = reporter_factory()
    batches = []
    reporter.configure_batch_sync(batches.append, batch_size=10)
    failure = RuntimeError("metadata unavailable")
    target, name = {
        "analytics": (reporting.MetricsCalculator, "get_analytics"),
        "write": (reporter.file_writer, "write_json"),
        "builder": (reporting.meta_payload, "build_metadata_payload"),
    }[failure_stage]
    with monkeypatch.context() as patch:
        patch.setattr(target, name, Mock(side_effect=failure))
        if entry == "terminal":
            reporter.complete(NIK, START, puzzle_solved=True)
            assert len(reporter.rows) == 1
            assert reporter._pending_batch_rows == reporter.rows
            assert json.loads(reporter.jsonl_path.read_text())["status"] == "completed"
            assert len(reporter.csv_path.read_text().splitlines()) == 2
        else:
            call = reporter._write_meta if entry == "direct" else reporter._write_operator_summary
            with pytest.raises(RuntimeError) as caught:
                call()
            assert caught.value is failure
    if entry == "terminal":
        reporter.complete(NIK, START, puzzle_solved=True)
        reporter.flush_pending_batches()
        reporter.flush_pending_batches()
        assert batches == [(reporter.rows[0], reporter.rows[1])]
        assert json.loads(reporter.meta_path.read_text())["completed"] == 2


def test_summary_field_failure_precedes_analytics(reporter_factory, monkeypatch):
    reporter = reporter_factory()
    monkeypatch.setattr(reporter, "_meta_workflow_report", dict)
    calculator = Mock(side_effect=RuntimeError("later analytics failure"))
    monkeypatch.setattr(reporting.MetricsCalculator, "get_analytics", calculator)
    with pytest.raises(KeyError, match="updated_niks"):
        reporter._write_meta()
    calculator.assert_not_called()


@pytest.mark.parametrize("case", ["empty", "completed", "mixed"])
def test_builder_order_values_and_read_only_composition(case):
    completed, skipped, failed = {
        "empty": (0, 0, 0), "completed": (1, 0, 0), "mixed": (2, 3, 2),
    }[case]
    errors = {"second": [NIK, NIK], "first": ["other"]} if failed else {}
    mapping = {
        "failed": [NIK] if failed else [], "failed_puzzle_solve": [],
        "successful": [NIK] if completed else [], "skipped": [], "unregistered": [],
    }
    values = dict(
        run_id="run", operator_id="operator", run_started_at=START, ended_at=END,
        total_niks=completed + skipped + failed, completed=completed, skipped=skipped,
        failed=failed, customer_updates=0, consent_encounters=0, retries=0,
        counts={"completed": completed, "error": failed},
        analytics={"duration": 1.2345, "optional": None, "signed_zero": -0.0},
        retry_report={"total_retry_events": 0, "retried_niks": []},
        workflow_summary={"total_events": 0},
        nik_parsing_failures={"total": 2 if skipped else 0, "by_reason": {"bad": [NIK]} if skipped else {}},
        mapping_report=mapping, mapping_error_report=errors,
        mapping_failed_puzzle_report={}, errors_by_label={}, other_statuses={},
        retried_niks=[], files={"csv": "items.csv", "jsonl": "items.jsonl"},
        paths={"application_run_dir": "run", "run_dir": "run/operator"},
    )
    before = deepcopy(values)
    result = build_metadata_payload(**values)
    expected = dict(zip(KEYS, (
        "run", "operator", "operator", START, END, completed + skipped + failed,
        completed, skipped, failed, 0, 0, 0, START, END, values["counts"],
        values["analytics"], values["retry_report"], values["workflow_summary"],
        values["nik_parsing_failures"], mapping, errors, {},
        {**mapping, "mapping_error_report": errors, "mapping_failed_puzzle_report": {},
         "errors_by_label": {}, "errors_by_reason": errors, "other_statuses": {}, "retried": []},
        values["files"], values["paths"],
    ), strict=True))
    assert json.dumps(result) == json.dumps(expected)
    assert values == before
    for section in ("counts", "analytics", "retry_report", "workflow_summary", "mapping_report"):
        assert result[section] is values[section]
    assert result["nik_lists"]["errors_by_reason"] is errors
    again = build_metadata_payload(**values)
    assert again is not result
    assert again["nik_lists"] is not result["nik_lists"]


def test_initial_metadata_builder_failure_propagates(reporter_factory, monkeypatch):
    failure = RuntimeError("initial metadata unavailable")
    builder = Mock(side_effect=failure)
    monkeypatch.setattr(reporting.meta_payload, "build_metadata_payload", builder)
    with pytest.raises(RuntimeError) as caught:
        reporter_factory()
    assert caught.value is failure
    builder.assert_called_once()


def test_operator_summary_keeps_reporter_write_boundary(reporter_factory, monkeypatch):
    reporter = reporter_factory()
    write = Mock()
    monkeypatch.setattr(reporter, "_write_meta", write)
    reporter._write_operator_summary()
    write.assert_called_once_with()
