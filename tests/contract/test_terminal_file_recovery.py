import json
import os
from unittest.mock import Mock

import pytest

from src.infrastructure.reporting.file_writer import FileWriter
from src.infrastructure.reporting.models import TransactionRow
from src.web.reporter import TransactionReporter


def make_writer(folder):
    folder.mkdir()
    writer = FileWriter(folder / "items.csv", folder / "items.jsonl")
    writer.init_csv()
    writer.jsonl_path.touch()
    return writer


@pytest.mark.parametrize("file_format", ["csv", "jsonl"])
@pytest.mark.parametrize("interruption", ["before", "partial", "after"])
def test_interrupted_append_matches_clean_bytes(tmp_path, monkeypatch, file_format, interruption):
    reference = make_writer(tmp_path / "reference")
    current = make_writer(tmp_path / "current")
    first = TransactionRow("fixture-a", "completed")
    second = TransactionRow("fixture-b", "completed", reason='café, "quoted"\nnext line')
    for writer in (reference, current):
        writer.append_row(first)
    reference.append_row(second)

    path = getattr(current, f"{file_format}_path")
    expected = getattr(reference, f"{file_format}_path").read_bytes()[path.stat().st_size:]
    # Split a UTF-8 character, not just a Python string or line.
    cut = {"before": 0, "partial": expected.index("é".encode()) + 1, "after": len(expected)}
    method = f"_append_to_{file_format}"
    original = getattr(current, method)
    attempts = 0

    def interrupted(row):
        nonlocal attempts
        attempts += 1
        if attempts > 1:
            return original(row)
        with path.open("ab") as stream:
            stream.write(expected[:cut[interruption]])
        raise OSError("injected append interruption")

    monkeypatch.setattr(current, method, interrupted)
    current.append_row(second)
    assert current.csv_path.read_bytes() == reference.csv_path.read_bytes()
    assert current.jsonl_path.read_bytes() == reference.jsonl_path.read_bytes()
    assert attempts == (2 if interruption == "before" else 1)


def test_unrecognized_partial_row_is_preserved(tmp_path, monkeypatch):
    writer = make_writer(tmp_path / "operator")
    row = TransactionRow("fixture", "completed")

    def damaged(_row):
        with writer.jsonl_path.open("ab") as stream:
            stream.write(b"unrecognized")
        raise OSError("interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(writer, "_append_to_jsonl", damaged)
        with pytest.raises(OSError, match="unexpected bytes"):
            writer.append_row(row)
    with pytest.raises(OSError, match="Unresolved partial write"):
        writer.append_row(TransactionRow("following", "completed"))
    assert writer.jsonl_path.read_bytes() == b"unrecognized"


@pytest.mark.parametrize("following_row", [False, True])
def test_unwritable_report_preserves_quota_order_and_fails_finalization(
    tmp_path, monkeypatch, following_row
):
    reporter = TransactionReporter(out_dir=str(tmp_path), operator_id="operator_01")
    batches = []
    reporter.configure_batch_sync(batches.append, batch_size=1)
    with monkeypatch.context() as patch:
        patch.setattr(reporter.file_writer, "_append_to_jsonl", Mock(side_effect=OSError("disk full")))
        with pytest.raises(OSError, match="disk full"):
            reporter.complete("fixture", reporter.start_item("fixture"))
    if following_row:
        reporter.skip("fixture", reporter.start_item("fixture"), skip_type="quota")

    for _ in range(2):
        with pytest.raises(OSError, match="Terminal file persistence failed for 1 row"):
            reporter.write_files()
        reporter.flush_pending_batches()
    assert [row for batch in batches for row in batch] == reporter.rows
    expected = ["completed", "skipped_quota"] if following_row else ["completed"]
    snapshot = json.loads(reporter.final_json_path.read_bytes())
    assert [row["status"] for row in snapshot["items"]] == expected


@pytest.mark.parametrize("persistent", [False, True])
def test_fsync_failure_must_be_resolved_before_reporting_success(tmp_path, monkeypatch, persistent):
    reporter = TransactionReporter(out_dir=str(tmp_path), operator_id="operator_01")
    healthy_sync = os.fsync
    calls = 0

    def fail_jsonl_sync(fd):
        nonlocal calls
        calls += 1
        if calls == 2 or (persistent and calls > 2):
            raise OSError("injected disk sync failure")
        healthy_sync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fail_jsonl_sync)
        if persistent:
            with pytest.raises(OSError, match="injected disk sync failure"):
                reporter.complete("fixture", reporter.start_item("fixture"))
        else:
            reporter.complete("fixture", reporter.start_item("fixture"))
    assert len(reporter.jsonl_path.read_bytes().splitlines()) == 1
    if persistent:
        with pytest.raises(OSError, match="Terminal file persistence failed"):
            reporter.write_files()
    else:
        reporter.write_files()
    assert calls == 3
