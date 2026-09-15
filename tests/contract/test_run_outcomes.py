import json
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main as taskbot_main
from src.orchestration.transaction_processor import (
    OutOfSellableStockError,
    TransactionProcessor,
)
from src.web.reporter import TransactionReporter


@pytest.fixture
def run_scenarios(monkeypatch, tmp_path):
    """Exercise real Reporter -> AccountRunner -> process_accounts -> main in memory."""
    def run(specs, *, max_concurrent_accounts=None):
        context = SimpleNamespace(
            run_id="status-contract", started_at="2026-09-10T10:00:00+07:00",
            run_dir=tmp_path, settings=SimpleNamespace(mask_nik=True),
        )
        configs = [
            SimpleNamespace(
                operator_id=f"operator_{index:02d}", run_context=context,
                nik=spec.get("niks", [
                    str(1000 + n) for n in range(spec.get("requested", len(spec["rows"])))
                ]),
                spec=spec,
            )
            for index, spec in enumerate(specs, 1)
        ]
        specs_by_operator = {config.operator_id: config.spec for config in configs}
        reporters = {}
        syncers = []
        captured = {}

        def reporter_factory(*, operator, run_context):
            reporter = TransactionReporter(operator=operator, run_context=run_context)
            reporter.print_summary = Mock()
            spec = specs_by_operator[operator]
            if spec.get("write_fails"):
                reporter.write_files = Mock(side_effect=OSError("final files unavailable"))
            elif spec.get("summary_content"):
                original_write = reporter.write_files

                def write_files():
                    original_write()
                    if spec["summary_content"] == "missing":
                        reporter.meta_path.unlink()
                    else:
                        reporter.meta_path.write_text(
                            '{"counts": {"completed": 999, "total": 999}}', encoding="utf-8"
                        )

                reporter.write_files = write_files
            reporters[operator] = reporter
            return reporter

        def processor_factory(config, page, reporter, limiter):
            statuses = iter(config.spec["rows"])

            def process_nik(nik):
                status = next(statuses)
                started = reporter.start_item(nik)
                if status == "completed":
                    reporter.complete(nik, started, puzzle_solved=True)
                elif status == "error":
                    reporter.error(nik, started, exc=RuntimeError("transaction rejected"))
                elif status == "failed_puzzle_solve":
                    reporter.failed_puzzle_solve(nik, started)
                else:
                    reporter.skip(nik, started, skip_type=status.removeprefix("skipped_"))
                if status == "skipped_out_of_stock":
                    raise OutOfSellableStockError("Sellable stock is empty", reported=True)

            def process():
                if "skipped_out_of_stock" in config.spec["rows"]:
                    # Use the real stop-on-stock-exhaustion loop without a browser.
                    processor = TransactionProcessor.__new__(TransactionProcessor)
                    processor.config = config
                    processor.operator_id = config.operator_id
                    processor.process_single_nik = process_nik
                    processor.process_all_niks()
                else:
                    for nik in config.nik[:len(config.spec["rows"])]:
                        process_nik(nik)
                if config.spec.get("processing_fails"):
                    raise RuntimeError("account processing failed")
                if config.spec.get("workflow_events"):
                    reporter.record_workflow_event(config.nik[0], event="customer_update_success")
                    reporter.record_retry(
                        config.nik[0], process="process_single_nik", trigger="general_error",
                        attempt_number=1, retry_number=1, max_retries=2,
                    )

            return SimpleNamespace(process_all_niks=Mock(side_effect=process))

        def syncer_factory():
            def sync(reporter, rows=None):
                spec = specs_by_operator[reporter.operator_id]
                if spec.get("db_disabled"):
                    return
                if spec.get("sync_fails"):
                    raise RuntimeError("final DB sync failed")

            syncer = Mock(side_effect=sync)
            syncer.close = Mock()
            syncers.append(syncer)
            return syncer

        original_process_accounts = taskbot_main.process_accounts

        def process_accounts(*args, **kwargs):
            assert kwargs.get("max_concurrent_accounts") == max_concurrent_accounts
            results = original_process_accounts(*args, **kwargs)
            captured["results"] = results
            return results

        monkeypatch.setattr(taskbot_main, "Config", lambda: SimpleNamespace(
            run_context=context, account_configs=lambda: configs,
            max_concurrent_accounts=max_concurrent_accounts,
        ))
        monkeypatch.setattr(taskbot_main, "load_dotenv", Mock())
        monkeypatch.setattr(taskbot_main, "configure_logging", lambda **kwargs: {
            "run_id": context.run_id, "json_log_path": str(tmp_path / "application.jsonl"),
        })
        logger = Mock()
        monkeypatch.setattr(taskbot_main, "logger", logger)
        monkeypatch.setattr(taskbot_main, "TransactionReporter", reporter_factory)
        monkeypatch.setattr(taskbot_main, "SkipRateLimiter", Mock())
        monkeypatch.setattr(taskbot_main, "_build_customer_update_rate_limiter", Mock())
        monkeypatch.setattr(taskbot_main, "BrowserSession", lambda config: nullcontext(
            SimpleNamespace(initialize_session=Mock(), require_page=lambda: object())
        ))
        monkeypatch.setattr(taskbot_main, "TransactionProcessor", processor_factory)
        monkeypatch.setattr(taskbot_main, "DatabaseReportSyncer", syncer_factory)
        monkeypatch.setattr(taskbot_main, "process_accounts", process_accounts)

        if len(specs) == 1 and specs[0].get("write_fails") and not specs[0].get("processing_fails"):
            with pytest.raises(OSError, match="final files unavailable"):
                taskbot_main.main()
            captured["results"] = []
        else:
            assert taskbot_main.main() is None  # Existing CLI completes without SystemExit.
        return SimpleNamespace(
            results=sorted(captured["results"]), reporters=reporters, syncers=syncers,
            meta=json.loads((tmp_path / "run_meta.json").read_text(encoding="utf-8")),
            logger=logger,
        )

    return run


@pytest.mark.parametrize("limit", [1, 2])
@pytest.mark.parametrize("spec,expected", [
    ({"rows": ["completed"]}, "completed"),
    ({"rows": ["error"]}, "completed_with_errors"),
    ({"rows": [], "processing_fails": True}, "failed"),
    ({"rows": ["completed"], "sync_fails": True}, "failed"),
    ({"rows": ["completed"], "write_fails": True}, "failed"),
])
def test_bounded_accounts_preserve_main_status_and_finalize_every_account(
    run_scenarios, limit, spec, expected
):
    run = run_scenarios(
        [{"rows": ["completed"]}, spec, {"rows": ["completed"]}],
        max_concurrent_accounts=limit,
    )
    assert run.meta["status"] == expected
    assert set(run.reporters) == {"operator_01", "operator_02", "operator_03"}
    assert len(run.syncers) == 3
    for syncer in run.syncers:
        syncer.close.assert_called_once_with()
    assert len(run.reporters["operator_01"].rows) == 1
    assert len(run.reporters["operator_03"].rows) == 1
    assert len(run.results) == (2 if spec.get("write_fails") else 3)
    startup = next(call.kwargs for call in run.logger.bind.call_args_list
                   if call.kwargs.get("event") == "app.concurrent_start")
    assert startup["max_workers"] == limit


@pytest.mark.parametrize(
    ("spec", "expected_success", "expected_status"),
    [
        ({"rows": ["completed", "completed"]}, True, "completed"),
        ({"rows": ["completed", "error"]}, False, "completed_with_errors"),
        ({"rows": ["error", "error"]}, False, "completed_with_errors"),
        ({"rows": ["error"]}, False, "completed_with_errors"),
        ({"rows": ["completed"], "processing_fails": True}, False, "failed"),
        ({"rows": ["completed"], "sync_fails": True}, False, "failed"),
        ({"rows": ["completed"], "db_disabled": True}, True, "completed"),
        ({"rows": ["completed", "skipped_out_of_stock"], "requested": 3}, False, "completed_with_errors"),
        ({"rows": []}, True, "completed"),
        ({"rows": [], "requested": 2}, False, "completed_with_errors"),
    ],
)
def test_account_and_main_status_follow_terminal_outcomes(
    run_scenarios, spec, expected_success, expected_status
):
    run = run_scenarios([spec])

    assert run.results == [("operator_01", expected_success)]
    assert run.meta["status"] == expected_status
    assert [row.status for row in run.reporters["operator_01"].rows] == spec["rows"]
    run.syncers[0].close.assert_called_once_with()
    outcome = run.meta["account_outcomes"]["operator_01"]
    assert outcome["status"] == expected_status
    assert outcome["execution_status"] == ("failed" if spec.get("processing_fails") else "completed")
    assert outcome["persistence_status"] == ("failed" if spec.get("sync_fails") else "successful")
    assert outcome["counts"]["total"] == len(spec["rows"])
    assert outcome["remaining_nik_count"] == spec.get("requested", len(spec["rows"])) - len(spec["rows"])
    assert outcome["transaction_error_count"] == spec["rows"].count("error")


@pytest.mark.parametrize(
    ("specs", "expected_successes", "expected_status"),
    [
        ([{"rows": ["completed"]}, {"rows": ["completed"]}], [True, True], "completed"),
        ([{"rows": ["completed"]}, {"rows": ["error"]}], [True, False], "completed_with_errors"),
        ([{"rows": ["completed"]}, {"rows": [], "processing_fails": True}], [True, False], "failed"),
        ([{"rows": ["error"]}, {"rows": [], "processing_fails": True}], [False, False], "failed"),
    ],
)
def test_multi_account_status_prioritizes_operational_failure(
    run_scenarios, specs, expected_successes, expected_status
):
    run = run_scenarios(specs)

    assert [successful for _, successful in run.results] == expected_successes
    assert run.meta["status"] == expected_status
    for syncer in run.syncers:
        syncer.close.assert_called_once_with()
    thread_logs = [
        call.kwargs for call in run.logger.bind.call_args_list
        if call.kwargs.get("event") == "account.thread.finished"
    ]
    assert {entry["operator_id"]: entry["status"] for entry in thread_logs} == {
        operator: outcome["status"] for operator, outcome in run.meta["account_outcomes"].items()
    }


@pytest.mark.parametrize("summary_content", ["wrong", "missing"])
def test_run_status_and_counts_do_not_depend_on_summary_files(run_scenarios, summary_content):
    run = run_scenarios([{"rows": ["completed", "error"], "summary_content": summary_content}])

    assert run.meta["status"] == "completed_with_errors"
    assert run.meta["account_outcomes"]["operator_01"]["counts"] == {
        "completed": 1, "error": 1, "total": 2,
    }
    assert run.meta["operator_summaries"]["operator_01"]["counts"] == {
        "completed": 1, "error": 1, "total": 2,
    }


@pytest.mark.parametrize("status", ["failed_puzzle_solve", "skipped_max_kuota", "skipped_not_registered"])
def test_noncompleted_terminal_results_are_not_clean_success(run_scenarios, status):
    run = run_scenarios([{"rows": [status]}])

    outcome = run.meta["account_outcomes"]["operator_01"]
    assert run.results == [("operator_01", False)]
    assert run.meta["status"] == "completed_with_errors"
    assert outcome["execution_status"] == "completed"
    assert outcome["persistence_status"] == "successful"
    assert outcome["transaction_error_count"] == int(status == "failed_puzzle_solve")
    assert outcome["remaining_nik_count"] == 0


def test_workflow_and_retry_events_do_not_count_as_terminal_outcomes(run_scenarios):
    run = run_scenarios([{"rows": ["completed"], "workflow_events": True}])

    assert run.results == [("operator_01", True)]
    assert run.meta["account_outcomes"]["operator_01"]["counts"] == {"completed": 1, "total": 1}
    reporter = run.reporters["operator_01"]
    assert len(reporter.workflow_events) == 1
    assert len(reporter.retry_events) == 1


def test_successful_duplicate_nik_is_not_reported_as_remaining_work(run_scenarios):
    run = run_scenarios([{"rows": ["completed"], "niks": ["1000", "1000"]}])

    outcome = run.meta["account_outcomes"]["operator_01"]
    assert run.results == [("operator_01", True)]
    assert outcome["requested_nik_count"] == outcome["processed_nik_count"] == 1
    assert outcome["remaining_nik_count"] == 0


@pytest.mark.parametrize("processing_fails", [False, True])
def test_write_failure_is_failed_even_with_successful_terminal_rows(run_scenarios, processing_fails):
    run = run_scenarios([{"rows": ["completed"], "write_fails": True, "processing_fails": processing_fails}])

    outcome = run.meta["account_outcomes"]["operator_01"]
    assert run.meta["status"] == "failed"
    assert outcome["transaction_status"] == "completed"
    assert outcome["persistence_status"] == "failed"
    assert outcome["execution_status"] == ("failed" if processing_fails else "completed")
    run.syncers[0].close.assert_called_once_with()


def test_missing_account_result_is_a_failed_run(run_scenarios):
    run = run_scenarios([{"rows": ["completed"]}, {"rows": ["completed"], "write_fails": True}])

    assert run.results == [("operator_01", True)]  # Existing fanout contract omits crashed workers.
    assert run.meta["status"] == "failed"
    assert run.meta["account_outcomes"]["operator_02"]["persistence_status"] == "failed"


@pytest.mark.parametrize("status", ["completed", "completed_with_errors", "failed", "uncaught"])
def test_cli_exit_code_compatibility(tmp_path, status):
    script = '''
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import main
root = Path(sys.argv[1])
status = sys.argv[2]
context = SimpleNamespace(run_id="exit-test", started_at="2026-09-10", run_dir=root,
                          settings=SimpleNamespace(mask_nik=True))
config = SimpleNamespace(operator_id="operator_01", nik=["1000"])
main.Config = lambda: SimpleNamespace(run_context=context, account_configs=lambda: [config])
main.load_dotenv = Mock()
main.configure_logging = lambda **kwargs: {"run_id": context.run_id, "json_log_path": str(root / "app.jsonl")}
main.logger = Mock()
main._build_customer_update_rate_limiter = Mock()
main._print_run_summary = Mock()
def process_accounts(*args, **kwargs):
    if status == "uncaught":
        raise RuntimeError("unhandled run failure")
    kwargs["outcomes"][config.operator_id].update(status=status)
    return [(config.operator_id, status == "completed")]
main.process_accounts = process_accounts
main.main()
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), status],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == (1 if status == "uncaught" else 0), result.stderr
    meta = json.loads((tmp_path / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == ("failed" if status == "uncaught" else status)
