import json
import os
from collections.abc import Sequence
from contextlib import suppress
from datetime import datetime
from functools import partial
from math import isfinite
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from dotenv import load_dotenv

from src.application.services.account_runner import AccountRunner
from src.application.use_cases.process_account import process_account, process_accounts
from src.config import Config
from src.infrastructure.browser.playwright_session import BrowserSession

# Compatibility exports retain canonical identity and composition patch points.
from src.infrastructure.database.report_syncer import (
    DatabaseReportSyncer,
)
from src.logging_utils import configure_logging, log_print, logger
from src.orchestration.transaction_processor import TransactionProcessor
from src.privacy import nik_masking_enabled
from src.web.rate_limiter import CustomerUpdateRateLimiter, SkipRateLimiter
from src.web.reporter import TransactionReporter


def _build_skip_rate_limiter(
    update_limiter: CustomerUpdateRateLimiter | None = None,
) -> SkipRateLimiter:
    return SkipRateLimiter(
        max_skips=8,
        window_seconds=48,
        min_cooldown=48,
        jitter_seconds=5,
        customer_update_rate_limiter=update_limiter,
    )


def _nonnegative_env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number.") from exc
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative.")
    return value


def _build_customer_update_rate_limiter() -> CustomerUpdateRateLimiter:
    """Build the one application-wide customer-update pacing channel."""
    return CustomerUpdateRateLimiter(
        min_interval_seconds=_nonnegative_env_float(
            "CUSTOMER_UPDATE_MIN_INTERVAL_SECONDS", 1.0
        ),
        jitter_seconds=_nonnegative_env_float("CUSTOMER_UPDATE_JITTER_SECONDS", 0.25),
    )


def _sync_report_to_database(
    reporter: TransactionReporter,
    rows: Sequence[Any] | None = None,
) -> None:
    """Own and close a syncer for one backward-compatible synchronous invocation.

    No pending batches are owned here. Sync exceptions propagate; ordinary close
    failures are logged, matching DatabaseReportSyncer's best-effort close contract.
    """
    syncer = DatabaseReportSyncer()
    sync_completed = False
    try:
        syncer(reporter, rows)
        sync_completed = True
    finally:
        try:
            syncer.close()
        except BaseException as close_error:
            # Preserve interrupts during close alone, but never replace an
            # already-propagating sync error (including an interrupt).
            if sync_completed and not isinstance(close_error, Exception):
                raise
            with suppress(Exception):  # Cleanup error reporting is best-effort.
                logger.bind(
                    event="report.db_sync.one_off_close_failed",
                ).exception("Failed to close one-off report syncer")


def _build_account_runner(
    *, run_context=None, update_limiter=None, outcome=None
) -> AccountRunner:
    reporter_factory = (
        partial(TransactionReporter, run_context=run_context)
        if run_context is not None
        else TransactionReporter
    )
    return AccountRunner(
        reporter_factory=reporter_factory,
        limiter_factory=partial(
            _build_skip_rate_limiter,
            update_limiter=update_limiter,
        ),
        browser_session_factory=BrowserSession,
        transaction_processor_factory=TransactionProcessor,
        report_syncer=DatabaseReportSyncer(),
        logger=logger,
        outcome=outcome,
    )


def run_account(
    config: Config,
    *,
    run_context=None,
    update_limiter=None,
    outcomes: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, bool]:
    """Run one account through the extracted account runner."""
    resolved_run_context = run_context or getattr(config, "run_context", None)
    return process_account(
        config,
        account_runner=_build_account_runner(
            run_context=resolved_run_context,
            update_limiter=update_limiter,
            outcome=(
                outcomes.get(config.operator_id) if outcomes is not None else None
            ),
        ),
    )


def _write_run_meta(
    run_context,
    account_configs: Sequence[Config],
    *,
    status: str,
    results: Sequence[tuple[str, bool]] = (),
    outcomes: dict[str, dict[str, Any]] | None = None,
) -> Path:
    """Persist credential-free metadata for the whole application execution."""
    run_dir = Path(run_context.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    result_by_operator = dict(results)
    operator_summaries: dict[str, Any] = {}
    for account_config in account_configs:
        operator_id = account_config.operator_id
        detail = (outcomes or {}).get(operator_id, {})
        summary_path = run_dir / "operators" / operator_id / "summary.json"
        if not summary_path.exists() and not detail:
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except OSError, UnicodeDecodeError, json.JSONDecodeError:
            summary = {}
        operator_summaries[operator_id] = {
            "success": (
                detail["status"] == "completed"
                if "status" in detail
                else result_by_operator.get(operator_id)
            ),
            "counts": detail.get("counts", summary.get("counts", {})),
            "workflow_summary": summary.get("workflow_summary", {}),
            "retry_report": {
                key: summary.get("retry_report", {}).get(key, 0)
                for key in ("total_retry_events", "total_retried_niks")
            },
        }

    payload = {
        "run_id": run_context.run_id,
        "started_at": run_context.started_at,
        "ended_at": (
            None
            if status == "running"
            else datetime.now().astimezone().isoformat(timespec="seconds")
        ),
        "status": status,
        "mask_enabled": bool(run_context.settings.mask_nik),
        "operator_count": len(account_configs),
        "operators": [config.operator_id for config in account_configs],
        "operator_summaries": operator_summaries,
        "account_outcomes": outcomes or {},
    }
    meta_path = run_dir / "run_meta.json"
    temporary_path = meta_path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(meta_path)
    return meta_path


def _fallback_run_context(logging_meta: dict[str, str]):
    """Create credential-free failure metadata when configuration cannot load."""
    return SimpleNamespace(
        run_id=logging_meta["run_id"],
        started_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        run_dir=Path(logging_meta["run_dir"]),
        settings=SimpleNamespace(mask_nik=nik_masking_enabled()),
    )


def _print_run_summary(
    run_context, account_configs: Sequence[Config], *, outcomes=None
) -> None:
    log_print("\nRUN SUMMARY", event="run.summary")
    for config in account_configs:
        summary_path = (
            Path(run_context.run_dir)
            / "operators"
            / config.operator_id
            / "summary.json"
        )
        counts: dict[str, int] = {}
        detail = (outcomes or {}).get(config.operator_id, {})
        if "counts" in detail:
            counts = detail["counts"]
        elif summary_path.exists():
            try:
                counts = json.loads(summary_path.read_text(encoding="utf-8")).get(
                    "counts", {}
                )
            except OSError, UnicodeDecodeError, json.JSONDecodeError:
                counts = {}
        for key, count in counts.items():
            if key.startswith("skipped_"):
                print(f"[DEBUG] {key=} {count=} {type(count)=}")
        skipped = sum(
            int(count or 0)
            for key, count in counts.items()
            if key.startswith("skipped_")
        )
        failed = counts.get("error", 0) + counts.get("failed_puzzle_solve", 0)
        log_print(
            (
                f"{config.operator_id}: completed={counts.get('completed', 0)} "
                f"skipped={skipped} failed={failed}"
                f" status={detail.get('status', 'unknown')}"
                f" remaining={detail.get('remaining_nik_count', 'unknown')}"
            ),
            event="run.summary.operator",
            operator_id=config.operator_id,
        )


def _aggregate_run_status(
    account_configs: Sequence[Config],
    results: Sequence[tuple[str, bool]],
    outcomes: dict[str, dict[str, Any]],
) -> str:
    """Operational failure dominates business errors, including missing worker results."""
    if len(results) != len(account_configs) or (
        {config.operator_id for config in account_configs}
        != {operator for operator, _ in results}
    ):
        return "failed"
    statuses = [
        outcomes.get(operator, {}).get("status")
        or ("completed" if successful else "failed")
        for operator, successful in results
    ]
    if "failed" in statuses:
        return "failed"
    if "completed_with_errors" in statuses:
        return "completed_with_errors"
    return "completed"


def main() -> None:
    """Main entry point."""
    load_dotenv(dotenv_path=Path(__file__).resolve().with_name(".env"))
    status = "failed"
    run_context = None
    logging_meta: dict[str, str] | None = None
    account_configs: list[Config] = []
    results: list[tuple[str, bool]] = []
    outcomes: dict[str, dict[str, Any]] = {}
    try:
        config = Config()
        run_context = config.run_context
        logging_meta = configure_logging(run_context=run_context)
        logger.bind(
            event="run.started",
            run_id=logging_meta["run_id"],
            json_log_path=logging_meta["json_log_path"],
            db_json_log_path=logging_meta.get("db_json_log_path"),
        ).info("TaskBot started")

        account_configs = config.account_configs()

        if not account_configs:
            raise ValueError(
                "No account configuration found. Set EMAIL/PIN/NIK or "
                "EMAIL_1/PIN_1/NIK_1."
            )

        # Each worker owns one preallocated detail dict; aggregation happens after fanout.
        outcomes = {account.operator_id: {} for account in account_configs}
        _write_run_meta(run_context, account_configs, status="running")

        update_limiter = _build_customer_update_rate_limiter()
        results = process_accounts(
            account_configs,
            run_account=partial(
                run_account,
                run_context=run_context,
                update_limiter=update_limiter,
                outcomes=outcomes,
            ),
            log=logger,
            outcomes=outcomes,
            max_concurrent_accounts=getattr(config, "max_concurrent_accounts", None),
        )
        status = _aggregate_run_status(account_configs, results, outcomes)
        _print_run_summary(run_context, account_configs, outcomes=outcomes)
    except BaseException:
        if logging_meta is None:
            logging_meta = configure_logging()
            run_context = _fallback_run_context(logging_meta)
        _write_run_meta(
            run_context,
            account_configs,
            status="failed",
            results=results,
            outcomes=outcomes,
        )
        logger.bind(
            event="run.failed",
            run_id=logging_meta["run_id"],
            status="failed",
        ).exception("TaskBot failed")
        raise
    else:
        _write_run_meta(
            run_context,
            account_configs,
            status=status,
            results=results,
            outcomes=outcomes,
        )
        logger.bind(
            event="run.completed" if status == "completed" else "run.failed",
            run_id=logging_meta["run_id"],
            status=status,
        ).info(f"TaskBot finished with status: {status}")
    finally:
        logger.complete()


if __name__ == "__main__":
    main()
