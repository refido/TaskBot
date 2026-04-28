import json
from pathlib import Path
from types import SimpleNamespace

import main as taskbot_main
import src.web.reporter as reporter_module


def test_reporter_labels_network_and_application_errors(monkeypatch):
    monkeypatch.setattr(reporter_module, "log_print", lambda *args, **kwargs: None)
    reporter = reporter_module.TransactionReporter.__new__(
        reporter_module.TransactionReporter
    )
    reporter.operator = "tester@example.com"
    reporter.run_started_at = reporter_module.now_iso()
    reporter.rows = []
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
    assert rows_by_nik["nik-network"].error_label == reporter_module._NETWORK_ERROR_LABEL
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


def test_run_account_limits_testing_hits_to_three(monkeypatch):
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

    email, is_successful = taskbot_main.run_account(
        SimpleNamespace(email_user="tester@example.com", nik=["3174"])
    )

    assert email == "tester@example.com"
    assert is_successful is True
    assert limiter_kwargs["max_skips"] == 3
    assert limiter_kwargs["window_seconds"] == 60
    assert limiter_kwargs["min_cooldown"] == 60
    assert limiter_kwargs["jitter_seconds"] == 5


def test_main_delegates_account_fanout_to_process_accounts(monkeypatch):
    calls = {}

    class DummyLogger:
        def bind(self, **kwargs):
            return self

        def info(self, *args, **kwargs) -> None:
            return None

    class FakeConfig:
        def account_configs(self):
            return [SimpleNamespace(email_user="tester@example.com", nik=["3174"])]

    def fake_configure_logging():
        return {
            "run_id": "run-1",
            "json_log_path": "logs/run-1.jsonl",
        }

    def fake_process_accounts(account_configs, *, run_account, log):
        calls["account_configs"] = account_configs
        calls["run_account"] = run_account
        calls["log"] = log
        return [("tester@example.com", True)]

    monkeypatch.setattr(taskbot_main, "configure_logging", fake_configure_logging)
    monkeypatch.setattr(taskbot_main, "logger", DummyLogger())
    monkeypatch.setattr(taskbot_main, "Config", FakeConfig)
    monkeypatch.setattr(taskbot_main, "process_accounts", fake_process_accounts)

    taskbot_main.main()

    assert len(calls["account_configs"]) == 1
    assert calls["account_configs"][0].email_user == "tester@example.com"
    assert calls["run_account"] is taskbot_main.run_account
    assert calls["log"] is taskbot_main.logger


def test_reporter_write_files_preserves_snapshot_and_meta_schema(monkeypatch):
    monkeypatch.setattr(reporter_module, "log_print", lambda *args, **kwargs: None)

    report_root = Path("reports_phase2_contract")
    reporter = reporter_module.TransactionReporter(
        out_dir=str(report_root),
        operator="tester@example.com",
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

    snapshot_payload = json.loads(
        reporter.final_json_path.read_text(encoding="utf-8")
    )
    assert set(snapshot_payload) == {
        "operator",
        "run_started_at",
        "run_ended_at",
        "counts",
        "analytics",
        "items",
        "mapping_report",
        "mapping_error_report",
        "mapping_failed_puzzle_report",
        "nik_lists",
        "puzzle_stats_by_nik",
    }
    assert snapshot_payload["counts"]["completed"] == 1
    assert snapshot_payload["mapping_report"]["successful"] == ["3174"]

    analytics_payload = json.loads(
        reporter.analytics_path.read_text(encoding="utf-8")
    )
    assert set(analytics_payload) == {
        "summary",
        "performance",
        "puzzle_metrics",
        "breakdown_by_status",
        "skip_reasons",
        "error_analysis",
    }

    meta_payload = json.loads(reporter.meta_path.read_text(encoding="utf-8"))
    assert set(meta_payload) == {
        "operator",
        "run_started_at",
        "run_ended_at",
        "counts",
        "analytics",
        "mapping_report",
        "mapping_error_report",
        "mapping_failed_puzzle_report",
        "nik_lists",
        "files",
        "paths",
    }
    assert meta_payload["files"]["csv"].endswith("items.csv")
    assert meta_payload["paths"]["run_dir"] == str(reporter.run_dir)
