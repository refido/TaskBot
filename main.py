from collections.abc import Sequence
from dataclasses import asdict
from threading import Lock
from typing import Any

from src.application.services.account_runner import AccountRunner
from src.application.use_cases.process_account import process_account, process_accounts
from src.config import Config
from src.infrastructure.browser.playwright_session import BrowserSession
from src.infrastructure.database import OperatorDatabaseManager
from src.logging_utils import configure_logging, logger
from src.orchestration.transaction_processor import TransactionProcessor
from src.web.rate_limiter import SkipRateLimiter
from src.web.reporter import TransactionReporter

_DATABASE_SETUP_LOCK = Lock()


def _build_skip_rate_limiter() -> SkipRateLimiter:
    return SkipRateLimiter(
        max_skips=8,
        window_seconds=48,
        min_cooldown=48,
        jitter_seconds=5,
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
                    (asdict(row) for row in rows),
                    source=str(report_path),
                    connection=connection,
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
            return None

        try:
            self._manager = OperatorDatabaseManager.from_env(
                require_operator_targets=True
            )
        except ValueError as exc:
            self._configuration_error = str(exc)
            logger.bind(
                event="report.db_sync.skipped",
                reason=self._configuration_error,
                report_path=str(report_path),
            ).info("Report database sync skipped")
            return None

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
        except Exception:
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


def _build_account_runner() -> AccountRunner:
    return AccountRunner(
        reporter_factory=TransactionReporter,
        limiter_factory=_build_skip_rate_limiter,
        browser_session_factory=BrowserSession,
        transaction_processor_factory=TransactionProcessor,
        report_syncer=DatabaseReportSyncer(),
        logger=logger,
    )


def run_account(config: Config) -> tuple[str, bool]:
    """Run one account through the extracted account runner."""
    return process_account(config, account_runner=_build_account_runner())


def main() -> None:
    """Main entry point."""
    logging_meta = configure_logging()
    logger.bind(
        event="app.start",
        run_id=logging_meta["run_id"],
        json_log_path=logging_meta["json_log_path"],
        db_json_log_path=logging_meta.get("db_json_log_path"),
    ).info("TaskBot started")

    config = Config()
    account_configs = config.account_configs()

    if not account_configs:
        raise ValueError(
            "No account configuration found. Set EMAIL/PIN/NIK or EMAIL_1/PIN_1/NIK_1."
        )

    process_accounts(
        account_configs,
        run_account=run_account,
        log=logger,
    )


if __name__ == "__main__":
    main()
