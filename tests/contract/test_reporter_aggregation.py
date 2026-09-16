"""Stage 5: frozen legacy outputs and deterministic traversal instrumentation."""

import hashlib
import json
import random
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import src.infrastructure.reporting.analytics as analytics_module
import src.web.reporter as reporting
from src.privacy import set_nik_masking

START = "2026-08-20T12:00:00+00:00"
END = "2026-08-20T12:02:00+00:00"
GOLDEN = Path(__file__).with_name("reporter_aggregation_legacy.json")


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls.fromisoformat(END)


class VisitedList(list):
    """Count actual history elements yielded, independent of wall-clock speed."""

    visits = 0

    def __iter__(self):
        for value in super().__iter__():
            self.visits += 1
            yield value


@pytest.fixture
def frozen_reports(monkeypatch):
    monkeypatch.setattr(reporting, "now_iso", lambda: END)
    monkeypatch.setattr(analytics_module, "datetime", FrozenDatetime)
    monkeypatch.setattr(reporting, "log_print", lambda *a, **kw: None)
    yield
    set_nik_masking(True)


def make_reporter(tmp_path, operator="operator_01"):
    return reporting.TransactionReporter(
        operator_id=operator,
        run_context=SimpleNamespace(
            run_id="fixed_run", started_at=START, run_dir=tmp_path / "fixed_run"
        ),
    )


def dataset(name):
    def row(status="completed", index=0, **kw):
        return reporting.TransactionRow(
            nik=f"357305{index:04d}720003", status=status,
            operator_id="operator_01", run_id="fixed_run",
            started_at=START, finished_at=END, **kw,
        )

    if name == "empty":
        return []
    if name == "single":
        return [row(duration_seconds=1.2345)]
    if name == "completed":
        return [row(index=i, duration_seconds=i / 10, puzzle_solved=True,
                    puzzle_attempts=i + 1, puzzle_retry_count=i) for i in range(5)]
    if name == "mixed":
        return [row(duration_seconds=2), row("error", 1, reason=" first\ntrace",
                error_label="Network", duration_seconds=3),
                row("error", 2, reason="second", duration_seconds=-1),
                row("error", 3, reason=" first\nother trace"), row(index=4)]
    if name == "puzzle":
        return [row(puzzle_solved=True, duration_seconds=1.0005, puzzle_attempts=2),
                row("failed_puzzle_solve", 1, puzzle_solved=False,
                    puzzle_attempts=5, puzzle_retry_count=2, duration_seconds=4.0015),
                row("failed_puzzle_solve", 2, reason="   ", puzzle_solved=False)]
    if name == "skipped":
        return [row("skipped_quota", reason="quota"),
                row("skipped_not_registered", 1, reason="Pelanggan Tidak Terdaftar"),
                row("skipped_nik_parsing_failed", 2, reason="bad NIK"),
                row("skipped_nik_parsing_failed", 2, reason="bad NIK"),
                row("skipped_nik_parsing_failed", 3, reason="bad NIK"),
                row("skipped_nik_parsing_failed", 4)]
    if name == "stock":
        return [row(), row("skipped_out_of_stock", 1, reason="stock exhausted")]
    if name == "edges":
        return [row(), row(), row("error", reason="Pelanggan Tidak Terdaftar"),
                row("pending", 1), row("skipped_skipped_quota", 2),
                row("error", 3), row("error", 4, reason="\n"),
                row(puzzle_solved=True, puzzle_attempts=1),
                row("failed_puzzle_solve", puzzle_solved=False, puzzle_attempts=4)]
    if name == "many":
        return [row("error" if i % 3 else "completed", i,
                    reason=f"reason {i % 13}", duration_seconds=(i % 7) / 10,
                    puzzle_solved=i % 2 == 0, puzzle_attempts=i % 5,
                    puzzle_retry_count=i % 3) for i in range(64)]
    raise AssertionError(name)


def normalized(text, root):
    return text.replace(str(root).replace("\\", "\\\\"), "<ROOT>").replace(
        str(root), "<ROOT>"
    ).replace("\\\\", "/")


def capture(reporter, root):
    observables = {
        "summary": reporter.summary(), "analytics": reporter.get_analytics_with_niks(),
        "parsing": reporter.get_nik_parsing_failure_report(),
        "skipped_including_unregistered": reporter.get_skipped_niks_by_type(True),
        "workflow": reporter.get_workflow_event_report(),
    }
    reporter.write_files()
    files = {}
    for attr in ("csv_path", "jsonl_path", "meta_path", "final_json_path",
                 "analytics_path", "workflow_events_path", "retries_path"):
        # Decode bytes without universal-newline conversion: retain CSV CRLF.
        content = normalized(getattr(reporter, attr).read_bytes().decode("utf-8"), root)
        files[attr] = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return {"observables": observables, "file_sha256": files}


@pytest.mark.parametrize("masked", [False, True])
@pytest.mark.parametrize("name", ["empty", "single", "completed", "mixed", "puzzle",
                                 "skipped", "stock", "edges", "many"])
def test_legacy_outputs(frozen_reports, tmp_path, name, masked):
    set_nik_masking(masked)
    reporter = make_reporter(tmp_path)
    steps = []
    for row in dataset(name):
        reporter._record_row(row)
        steps.append(hashlib.sha256(normalized(
            reporter.meta_path.read_text(encoding="utf-8"), tmp_path
        ).encode("utf-8")).hexdigest())
    actual = {**capture(reporter, tmp_path), "meta_after_each_row": steps}
    key = f"{name}_{masked}"
    assert actual == json.loads(GOLDEN.read_text(encoding="utf-8"))[key]


def test_two_operator_event_outputs(frozen_reports, tmp_path):
    first, second = make_reporter(tmp_path), make_reporter(tmp_path, "operator_02")
    for i in (0, 1, 0, 2):
        first.record_retry(str(i), process=f"process{i % 2}", trigger=f"trigger{i % 2}",
                           attempt_number=2, retry_number=1, max_retries=3)
        first.record_workflow_event(str(i), event="customer_update_success")
        first.record_workflow_event(str(i), event="consent_detected")
    first._record_row(dataset("single")[0])
    second._record_row(reporting.TransactionRow("other", "error", "operator_02"))
    actual = [capture(first, tmp_path), capture(second, tmp_path)]
    key = "two_operators_events"
    assert actual == json.loads(GOLDEN.read_text(encoding="utf-8"))[key]


@pytest.mark.parametrize("count", [8, 32, 128])
def test_terminal_history_visits(frozen_reports, tmp_path, monkeypatch, count):
    reporter = make_reporter(tmp_path)
    reporter.rows = VisitedList()
    reporter._meta_calculator.rows = VisitedList()
    add_row = Mock(wraps=reporter._meta_calculator.add_row)
    monkeypatch.setattr(reporter._meta_calculator, "add_row", add_row)
    write = Mock()
    monkeypatch.setattr(reporter.file_writer, "write_json", write)
    for i in range(count):
        reporter._record_row(reporting.TransactionRow(str(i), "completed"))
    # Measured before implementation: 19 * N * (N + 1) / 2 history visits.
    assert reporter.rows.visits == 0
    assert reporter._meta_calculator.rows.visits == 0
    assert add_row.call_count == count
    assert write.call_count == count  # Summary frequency stays unchanged.
    assert write.call_args.args[1]["counts"] == {"completed": count, "total": count}


@pytest.mark.parametrize("failure_stage", ["write", "analytics", "aggregate", "enqueue"])
def test_failure_then_more_rows_keeps_cache_and_durable_history_consistent(
    frozen_reports, tmp_path, monkeypatch, failure_stage
):
    reporter = make_reporter(tmp_path)
    batches = []
    reporter.configure_batch_sync(batches.append, batch_size=10)
    failure = RuntimeError(failure_stage)
    if failure_stage == "write":
        target, attribute = reporter.file_writer, "write_json"
    elif failure_stage == "analytics":
        target, attribute = reporter._meta_calculator, "get_analytics"
    elif failure_stage == "aggregate":
        target, attribute = reporter._meta_calculator, "_accumulate"
    else:
        target, attribute = reporter, "_queue_row_for_batch_sync"
    original = getattr(target, attribute)

    def fail_after_work(*args, **kwargs):
        # Include a partially updated cache / enqueued row, not only early failure.
        original(*args, **kwargs)
        raise failure

    monkeypatch.setattr(target, attribute, fail_after_work)
    rows = dataset("mixed")
    if failure_stage == "enqueue":
        with pytest.raises(RuntimeError) as caught:
            reporter._record_row(rows[0])
        assert caught.value is failure
    else:
        reporter._record_row(rows[0])
    monkeypatch.setattr(target, attribute, original)
    for row in rows[1:]:
        reporter._record_row(row)
    reporter.flush_pending_batches()
    reporter.flush_pending_batches()
    assert [row for batch in batches for row in batch] == rows
    meta = json.loads(reporter.meta_path.read_text(encoding="utf-8"))
    assert meta["counts"] == reporter.summary()
    assert meta["analytics"] == reporter.get_analytics()
    assert meta["mapping_report"] == reporter.get_mapping_report()
    assert len(reporter.jsonl_path.read_text(encoding="utf-8").splitlines()) == len(rows)
    reporter.write_files()
    snapshot = json.loads(reporter.final_json_path.read_text(encoding="utf-8"))
    assert snapshot["counts"] == meta["counts"]


@pytest.mark.parametrize("file_format", ["csv", "jsonl"])
def test_file_failure_does_not_advance_cache(frozen_reports, tmp_path, monkeypatch, file_format):
    reporter = make_reporter(tmp_path)
    reporter._record_row(dataset("single")[0])
    before = reporter._meta_calculator.get_summary()
    failure = OSError("terminal persistence failed")
    with monkeypatch.context() as patch:
        patch.setattr(reporter.file_writer, f"_append_to_{file_format}", Mock(side_effect=failure))
        with pytest.raises(OSError) as caught:
            reporter._record_row(dataset("mixed")[1])
        assert caught.value is failure
    assert reporter._meta_calculator.get_summary() == before
    assert reporter._meta_row_count == 1
    assert reporter._meta_cache_valid is False
    assert len(reporter.rows) == 2  # Existing memory-first semantics.
    reporter._record_row(dataset("single")[0])
    meta = json.loads(reporter.meta_path.read_text(encoding="utf-8"))
    # Preserve the legacy history-based summary on this exceptional path;
    # summary counts are outcomes, never proof of terminal file durability.
    assert meta["counts"] == reporter.summary()


def test_event_indexing_is_incremental(frozen_reports, tmp_path, monkeypatch):
    reporter = make_reporter(tmp_path)

    class IndexedEvents(VisitedList):
        reads = 0

        def __getitem__(self, key):
            self.reads += 1
            return super().__getitem__(key)

    reporter.retry_events, reporter.workflow_events = IndexedEvents(), IndexedEvents()
    # A compact summary must not serialize full retry events just to discard them.
    original_asdict = reporting.asdict
    serializations = Mock(wraps=original_asdict)
    monkeypatch.setattr(reporting, "asdict", serializations)
    for i in range(20):
        reporter.record_retry(str(i % 7), process="process", trigger="trigger",
                              attempt_number=2, retry_number=1, max_retries=3)
        reporter.record_workflow_event(str(i % 7), event="consent_detected")
        reporter._record_row(reporting.TransactionRow(str(i), "completed"))
    assert reporter.retry_events.reads == 20
    assert reporter.workflow_events.reads == 20
    assert reporter.retry_events.visits == reporter.workflow_events.visits == 0
    assert serializations.call_count == 40  # Only immediate JSONL event writes.
    assert reporter._compact_retry_report() == {
        key: value for key, value in reporter.get_retry_report().items() if key != "events"
    }
    assert reporter._meta_workflow_report() == reporter.get_workflow_event_report()


def test_privacy_projection_and_caller_mutation_do_not_corrupt_cache(frozen_reports, tmp_path):
    reporter = make_reporter(tmp_path)
    set_nik_masking(False)
    for row in dataset("skipped") + dataset("edges"):
        reporter._record_row(row)
    for masked in (True, False, True):
        set_nik_masking(masked)
        reports = reporter._meta_row_reports()
        assert reports["mapping"] == reporter.get_mapping_report()
        assert reports["parsing"] == reporter.get_nik_parsing_failure_report()
        reports["mapping"]["successful"].append("caller mutation")
        reports["errors"].clear()
        assert reporter._meta_row_reports()["mapping"] == reporter.get_mapping_report()


def test_incremental_metrics_match_full_history_at_every_prefix(frozen_reports):
    generator = random.Random(2026)
    durations = [0.0, -1.0, 1.2345, 0.0005, 1e16, 1.0, 1.0, 0.1] + [
        generator.random() * 100 for _ in range(100)
    ]
    calculator = reporting.MetricsCalculator([], incremental=True)
    rows = []
    for i, duration in enumerate(durations):
        row = reporting.TransactionRow(
            str(i % 5), ("completed", "error", "skipped_quota", "failed_puzzle_solve")[i % 4],
            duration_seconds=duration, puzzle_solved=(True, False, None)[i % 3],
            puzzle_attempts=i % 7, puzzle_retry_count=i % 4, reason=f"reason {i % 13}",
        )
        rows.append(row)
        calculator.add_row(row)
        legacy = reporting.MetricsCalculator(rows)
        assert calculator.get_summary() == legacy.get_summary()
        assert calculator.get_analytics(START) == legacy.get_analytics(START)


def test_external_history_append_uses_legacy_fallback(frozen_reports, tmp_path):
    reporter = make_reporter(tmp_path)
    reporter.rows.extend(dataset("mixed"))
    reporter._write_meta()
    meta = json.loads(reporter.meta_path.read_text(encoding="utf-8"))
    assert meta["counts"] == reporter.summary()
    assert meta["analytics"] == reporter.get_analytics()
    reporter._record_row(dataset("single")[0])
    assert reporter._meta_cache_valid is False
    assert json.loads(reporter.meta_path.read_text(encoding="utf-8"))["counts"] == reporter.summary()


def test_error_top_ten_never_scans_all_error_types(frozen_reports):
    class NoTraversal(dict):
        def __iter__(self):
            pytest.fail("full error-type traversal")

        def items(self):
            pytest.fail("full error-type traversal")

        def values(self):
            pytest.fail("full error-type traversal")

        def __missing__(self, key):
            return 0

    calculator = reporting.MetricsCalculator([], incremental=True)
    calculator._error_types = NoTraversal()
    rows = []
    # Ties, candidates entering/leaving the top ten, and repeated older types.
    for i in [*range(100), *reversed(range(100)), *range(50, 100), *range(100)]:
        row = reporting.TransactionRow(str(i), "error", reason=f"type {i}")
        rows.append(row)
        calculator.add_row(row)
        assert calculator._get_error_analysis() == reporting.MetricsCalculator(rows)._get_error_analysis()


def test_same_length_history_replacement_uses_legacy_fallback(frozen_reports, tmp_path):
    reporter = make_reporter(tmp_path)
    reporter._record_row(dataset("single")[0])
    reporter.rows = [dataset("mixed")[1]]
    reporter._write_meta()
    assert json.loads(reporter.meta_path.read_text(encoding="utf-8"))["counts"] == reporter.summary()


@pytest.mark.parametrize("durations", [
    [float("inf"), 1.0], [1e308, 1e308], [float("nan"), 1.0],
    [float("-inf"), 1.0], [0.0005, 0.0015, 0.0025],
])
def test_nonfinite_and_rounding_durations_match_legacy(frozen_reports, durations):
    rows = [reporting.TransactionRow(str(i), "completed", duration_seconds=value,
                                    puzzle_solved=True)
            for i, value in enumerate(durations)]
    cached = reporting.MetricsCalculator([], incremental=True)
    for row in rows:
        cached.add_row(row)
    assert cached.get_analytics(START) == reporting.MetricsCalculator(rows).get_analytics(START)


def test_cache_update_occurs_after_persistence_and_enqueue(frozen_reports, tmp_path, monkeypatch):
    reporter = make_reporter(tmp_path)
    queued = []

    def sync(batch):
        assert reporter._meta_calculator.get_summary()["total"] == len(queued)
        lines = reporter.jsonl_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == len(queued) + 1
        queued.extend(batch)

    reporter.configure_batch_sync(sync, batch_size=1)
    original = reporter.file_writer.write_json

    def write(path, payload):
        assert payload["counts"]["total"] == len(queued)
        return original(path, payload)

    monkeypatch.setattr(reporter.file_writer, "write_json", write)
    row = dataset("single")[0]
    reporter._record_row(row)
    reporter._record_row(row)  # Existing API records occurrences, not unique NIKs.
    reporter.flush_pending_batches()
    assert queued == [row, row]
    assert reporter._meta_calculator.get_summary() == {"completed": 2, "total": 2}


def test_incremental_calculator_initialization_scans_once(frozen_reports):
    rows = VisitedList(dataset("many"))
    calculator = reporting.MetricsCalculator(rows, incremental=True)
    assert rows.visits == len(rows)
    expected = reporting.MetricsCalculator(list(rows)).get_analytics(START)
    rows.visits = 0
    assert calculator.get_analytics(START) == expected
    assert calculator.get_summary()["total"] == len(rows)
    assert rows.visits == 0
