import json
import os
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from functools import partial
from math import isfinite
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from typing import Any

from dotenv import load_dotenv

from src.application.services.account_runner import AccountRunner
from src.application.use_cases.process_account import process_account, process_accounts
from src.config import Config
from src.infrastructure.browser.playwright_session import BrowserSession
from src.infrastructure.database import OperatorDatabaseManager
from src.logging_utils import configure_logging, log_print, logger
from src.orchestration.transaction_processor import TransactionProcessor
from src.privacy import nik_masking_enabled, sanitize_text
from src.web.rate_limiter import CustomerUpdateRateLimiter, SkipRateLimiter
from src.web.reporter import TransactionReporter

_DATABASE_SETUP_LOCK = Lock()


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


class DatabaseReportSyncer:
    """Lazily initialize one database manager and sync only supplied report rows."""

    def __init__(self) -> None:
        self._manager: OperatorDatabaseManager | None = None
        self._database_ready = False
        self._configuration_error: str | None = None
        self._connection: Any | None = None

    def __call__(
        self,
        reporter: TransactionReporter,
        rows: Sequence[Any] | None = None,
    ) -> None:
        if rows is not None and not rows:
            return

        report_path = getattr(reporter, "jsonl_path", None)

        if report_path is None:
            logger.bind(
                event="report.db_sync.skipped",
                reason="missing_report_path",
            ).info("Report database sync skipped")

            return

        manager = self._get_manager(report_path)

        if manager is None:
            return

        batch_size = len(rows) if rows is not None else None

        logger.bind(
            event="report.db_sync.started",
            report_path=str(report_path),
            batch_size=batch_size,
        ).info("Report database sync started")

        try:
            self._ensure_database(manager)

            connection = self._get_connection(manager)

            if rows is None:
                summary = manager.sync_report_file(
                    report_path,
                    connection=connection,
                )
            else:
                summary = manager.sync_report_payloads(
                    (_database_report_payload(row) for row in rows),
                    source=str(report_path),
                    connection=connection,
                )

                expected_rows = len(rows)
                if (
                    summary.processed != expected_rows
                    or summary.inserted_or_updated != expected_rows
                    or summary.skipped
                ):
                    raise RuntimeError(
                        "Per-NIK database sync did not persist every terminal row: "
                        f"expected={expected_rows}, processed={summary.processed}, "
                        f"inserted_or_updated={summary.inserted_or_updated}, "
                        f"skipped={summary.skipped}."
                    )

        except Exception:
            # Do not keep a connection around after a failed DB operation.
            # A later retry will create a fresh connection.
            self._discard_connection()

            logger.bind(
                event="report.db_sync.failed",
                report_path=str(report_path),
                batch_size=batch_size,
            ).exception("Report database sync failed")

            raise

        logger.bind(
            event="report.db_sync.finished",
            report_path=summary.source,
            batch_size=batch_size,
            processed=summary.processed,
            inserted_or_updated=summary.inserted_or_updated,
            skipped=summary.skipped,
        ).info("Report synced to database")

    def _get_manager(self, report_path: object) -> OperatorDatabaseManager | None:
        if self._manager is not None:
            return self._manager

        if self._configuration_error is not None:
            if self._configuration_error.startswith(
                "Missing database environment variables:"
            ):
                return None
            raise ValueError(self._configuration_error)

        try:
            self._manager = OperatorDatabaseManager.from_env(
                require_operator_targets=True
            )
        except ValueError as exc:
            self._configuration_error = str(exc)
            if self._configuration_error.startswith(
                "Missing database environment variables:"
            ):
                logger.bind(
                    event="report.db_sync.skipped",
                    reason=self._configuration_error,
                    report_path=str(report_path),
                ).info("Report database sync skipped because database is disabled")
                return None
            logger.bind(
                event="report.db_sync.configuration_failed",
                reason=self._configuration_error,
                report_path=str(report_path),
            ).error("Report database sync configuration is invalid")
            raise

        return self._manager

    def _get_connection(self, manager: OperatorDatabaseManager):
        """Return the reusable PostgreSQL connection for this account run."""

        if self._connection is not None:
            if not self._connection.closed:
                return self._connection

            self._connection = None

        self._connection = manager.open_connection()

        logger.bind(
            event="report.db_connection.opened",
        ).debug("Persistent report database connection opened")

        return self._connection

    def _discard_connection(self) -> None:
        """Close and forget the current PostgreSQL connection."""

        connection = self._connection
        self._connection = None

        if connection is None:
            return

        try:
            connection.close()
        except Exception:  # noqa: BLE001 - cleanup must not mask the caller failure.
            logger.bind(
                event="report.db_connection.close_failed",
            ).exception("Failed to close report database connection")

    def close(self) -> None:
        """Release database resources owned by this syncer."""

        self._discard_connection()

    def _ensure_database(self, manager: OperatorDatabaseManager) -> None:
        if self._database_ready:
            return

        with _DATABASE_SETUP_LOCK:
            if self._database_ready:
                return
            manager.ensure_database_and_tables()
            self._database_ready = True


def _sync_report_to_database(
    reporter: TransactionReporter,
    rows: Sequence[Any] | None = None,
) -> None:
    """Backward-compatible one-off report synchronizer."""
    DatabaseReportSyncer()(reporter, rows)


def _database_report_payload(row: Any) -> dict[str, Any]:
    """Keep raw NIK routing while removing credentials from DB report text."""
    payload = asdict(row)
    for key in ("url", "reason", "error"):
        payload[key] = sanitize_text(payload.get(key, ""))
    return payload


def _build_account_runner(*, run_context=None, update_limiter=None) -> AccountRunner:
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
    )


def run_account(
    config: Config,
    *,
    run_context=None,
    update_limiter=None,
) -> tuple[str, bool]:
    """Run one account through the extracted account runner."""
    resolved_run_context = run_context or getattr(config, "run_context", None)
    return process_account(
        config,
        account_runner=_build_account_runner(
            run_context=resolved_run_context,
            update_limiter=update_limiter,
        ),
    )


def _write_run_meta(
    run_context,
    account_configs: Sequence[Config],
    *,
    status: str,
    results: Sequence[tuple[str, bool]] = (),
) -> Path:
    """Persist credential-free metadata for the whole application execution."""
    run_dir = Path(run_context.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    result_by_operator = dict(results)
    operator_summaries: dict[str, Any] = {}
    for account_config in account_configs:
        operator_id = account_config.operator_id
        summary_path = run_dir / "operators" / operator_id / "summary.json"
        if not summary_path.exists():
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except OSError, UnicodeDecodeError, json.JSONDecodeError:
            continue
        operator_summaries[operator_id] = {
            "success": result_by_operator.get(operator_id),
            "counts": summary.get("counts", {}),
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


def _print_run_summary(run_context, account_configs: Sequence[Config]) -> None:
    log_print("\nRUN SUMMARY", event="run.summary")
    for config in account_configs:
        summary_path = (
            Path(run_context.run_dir)
            / "operators"
            / config.operator_id
            / "summary.json"
        )
        counts: dict[str, int] = {}
        if summary_path.exists():
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
            ),
            event="run.summary.operator",
            operator_id=config.operator_id,
        )


def main() -> None:
    """Main entry point."""
    load_dotenv(dotenv_path=Path(__file__).resolve().with_name(".env"))
    status = "failed"
    run_context = None
    logging_meta: dict[str, str] | None = None
    account_configs: list[Config] = []
    results: list[tuple[str, bool]] = []
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

        _write_run_meta(run_context, account_configs, status="running")

        update_limiter = _build_customer_update_rate_limiter()
        results = process_accounts(
            account_configs,
            run_account=partial(
                run_account,
                run_context=run_context,
                update_limiter=update_limiter,
            ),
            log=logger,
        )
        all_successful = len(results) == len(account_configs) and all(
            successful for _, successful in results
        )
        status = "completed" if all_successful else "completed_with_errors"
        _print_run_summary(run_context, account_configs)
    except BaseException:
        if logging_meta is None:
            logging_meta = configure_logging()
            run_context = _fallback_run_context(logging_meta)
        _write_run_meta(
            run_context,
            account_configs,
            status="failed",
            results=results,
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
