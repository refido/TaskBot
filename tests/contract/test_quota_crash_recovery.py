"""Crash boundaries for the private quota journal (no network or shop required)."""

import json
import os
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from src.infrastructure.database.quota_journal import QuotaJournal
from src.infrastructure.database.recover_quota import receipt_time


DEST = ("fixture", 1, "test", "OPERATOR_1", "operator_01")
START = "2026-11-30T23:59:59+07:00"
END = "2026-12-01T00:00:01+07:00"


def open_journal(root):
    return QuotaJournal(root, DEST, "operator_01")


def sale(nik="fixture"):
    return {"operator_id": "operator_01", "nik": nik, "status": "completed", "finished_at": END}


@pytest.mark.parametrize("checkpoint", ["begin", "confirm", "stage"])
def test_journal_survives_abrupt_process_exit(tmp_path, checkpoint):
    # os._exit bypasses Python finalizers and releases the writer's OS lock.
    script = """
import json, os, sys
from pathlib import Path
from src.infrastructure.database.quota_journal import QuotaJournal
path, checkpoint, destination, start, end = sys.argv[1:]
journal = QuotaJournal(Path(path), tuple(json.loads(destination)), "operator_01")
journal.begin("fixture", start, "items.jsonl")
if checkpoint != "begin":
    journal.confirm("fixture", start, "Fixture", "test")
if checkpoint == "stage":
    journal.stage(dict(operator_id="operator_01", nik="fixture", status="completed", finished_at=end), "items.jsonl")
os._exit(73)
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
    run = subprocess.run(
        [sys.executable, "-B", "-c", script, str(tmp_path), checkpoint, json.dumps(DEST), START, END],
        env=env, timeout=30, check=False,
    )
    assert run.returncode == 73
    with closing(open_journal(tmp_path)) as journal:
        event, = journal.entries()
        delivered = []
        if checkpoint == "begin":
            with pytest.raises(RuntimeError, match="no recorded outcome"):
                journal.require_resolved()
            assert journal.drain(lambda *args: pytest.fail("uncertain sale sent to DB")) == 0
            journal.reconcile(event["id"], confirmed_at=START)
        assert journal.drain(lambda *args: delivered.append(args)) == 1
        event_id, source, payload = delivered[0]
        assert (event_id, source) == (event["id"], "items.jsonl")
        expected_time = END if checkpoint == "stage" else START
        assert (payload["nik"], payload["status"], payload["finished_at"]) == (
            "fixture", "completed", expected_time
        )
        assert journal.drain(lambda *args: pytest.fail("duplicate delivery")) == 0


def test_uncertain_item_can_only_be_resolved_by_its_own_id(tmp_path):
    with closing(open_journal(tmp_path)) as journal:
        journal.begin("fixture", START, "items.jsonl")
        event, = journal.entries()
        with pytest.raises(ValueError, match="Unknown"):
            journal.reconcile("wrong-id", confirmed_at=None)
        with pytest.raises(RuntimeError, match="no recorded outcome"):
            journal.begin("another", END, "items.jsonl")
        journal.reconcile(event["id"], confirmed_at=None)
        assert list(journal.entries()) == []
        assert journal.drain(lambda *args: pytest.fail("no-sale changed quota")) == 0


def test_other_writer_cannot_touch_live_operator_journal(tmp_path):
    with closing(open_journal(tmp_path)) as journal:
        journal.begin("fixture", START, "items.jsonl")
        with pytest.raises(RuntimeError, match="locked or unavailable"):
            open_journal(tmp_path)
        with closing(QuotaJournal(tmp_path, (*DEST[:-2], "OPERATOR_2", "operator_02"), "operator_02")) as other:
            assert list(other.entries()) == []


def test_retry_retains_event_id_and_preserves_order(tmp_path):
    with closing(open_journal(tmp_path)) as journal:
        for nik in ("first", "second"):
            journal.stage(sale(nik), "items.jsonl")
        attempts = []
        def no_ack(event_id, source, payload):
            attempts.append(event_id)
            raise OSError("commit acknowledgement interrupted")
        with pytest.raises(OSError, match="acknowledgement"):
            journal.drain(no_ack)
    with closing(open_journal(tmp_path)) as journal:
        rows = []
        journal.drain(lambda event, source, payload: rows.append((event, payload["nik"])))
        assert [nik for _, nik in rows] == ["first", "second"]
        assert attempts == [rows[0][0]]
        assert rows[0][0] != rows[1][0]


def test_confirmed_event_cannot_be_dismissed_or_replaced_with_skip(tmp_path):
    with closing(open_journal(tmp_path)) as journal:
        journal.begin("fixture", START, "items.jsonl")
        journal.confirm("fixture", START, "", "")
        event, = journal.entries()
        with pytest.raises(ValueError, match="Unknown or already resolved"):
            journal.reconcile(event["id"], confirmed_at=None)
        with pytest.raises(ValueError, match="must stay completed"):
            journal.stage(dict(sale(), status="skipped_quota"), "items.jsonl")
        with pytest.raises(ValueError, match="different operator"):
            journal.stage(dict(sale(), operator_id="operator_02"), "items.jsonl")
        row, = journal.entries()
        assert json.loads(row["payload"])["status"] == "completed"


def test_manual_receipt_time_requires_timezone():
    from argparse import ArgumentTypeError
    with pytest.raises(ArgumentTypeError):
        receipt_time("2026-11-23 12:00:00")
    assert receipt_time(START) == START


def test_invalid_zero_quota_skip_cannot_block_the_next_sale(tmp_path):
    from src.infrastructure.database.report_syncer import DatabaseReportSyncer
    from src.infrastructure.reporting.models import TransactionRow

    with closing(open_journal(tmp_path)) as journal:
        syncer = DatabaseReportSyncer()
        syncer._journal = journal
        journal.begin("invalid-id", START, "items.jsonl")
        syncer._stage_row(TransactionRow("invalid-id", "skipped_nik_parsing_failed"), "items.jsonl")
        assert list(journal.entries()) == []
        journal.begin("fixture", START, "items.jsonl")
        journal.confirm("fixture", START, "", "")
        with pytest.raises(ValueError):
            journal.finish_without_quota("fixture")
        delivered = []
        journal.drain(lambda event, source, payload: delivered.append(payload["status"]))
        assert delivered == ["completed"]
