"""Persistent report synchronization adapter with per-account resource ownership."""

from collections.abc import Sequence
from contextlib import suppress
from dataclasses import asdict
from threading import Lock
from typing import Any, cast

from src.infrastructure.database.operator_store import (
    OperatorDatabaseManager,
    OperatorTargets,
    counts_toward_quota,
)
from src.infrastructure.database.quota_journal import QuotaJournal, recovery_directory
from src.logging_utils import logger
from src.privacy import sanitize_text
from src.web.reporter import TransactionReporter

_DATABASE_SETUP_LOCK = Lock()


class DatabaseReportSyncer:
    """Lazily initialize one database manager and sync only supplied report rows."""

    _journal: QuotaJournal | None = None
    _receipts_ready = False

    def __init__(self) -> None:
        self._manager: OperatorDatabaseManager | None = None
        self._database_ready = False
        self._configuration_error: str | None = None
        self._connection: Any | None = None

    def open_journal(self, operator_id: str, manager: OperatorDatabaseManager) -> QuotaJournal:
        config = manager.config
        # Both startup and manual recovery construct the manager with required targets.
        target = cast(OperatorTargets, manager.targets).resolve(operator_id)
        self._manager = manager
        self._journal = QuotaJournal(
            recovery_directory(),
            (config.host.casefold(), config.port, config.name, target.table_name, target.operator_id),
            target.operator_id,
        )
        return self._journal

    def prepare_delivery(self, reporter: TransactionReporter) -> bool:
        manager = self._get_manager(reporter.jsonl_path)
        if manager is None:
            return False
        journal = self.open_journal(reporter.operator_id, manager)
        recovered = journal.drain(self._deliver_event)
        journal.require_resolved()
        reporter.configure_quota_journal(
            begin=journal.begin, confirm=journal.confirm, stage=self._stage_row, check=journal.require_resolved
        )
        return recovered > 0

    def finish_delivery(self) -> None:
        if self._journal is not None:
            self._journal.drain(self._deliver_event)

    def _stage_row(self, row, source: str) -> None:
        # prepare_delivery registers this callback after open_journal sets the journal.
        if not counts_toward_quota(row.status):
            # Invalid customer IDs can be reportable skips. Keep zero-quota
            # rows on the ordinary sync path so they cannot block sale recovery.
            cast(QuotaJournal, self._journal).finish_without_quota(row.nik)
            return
        payload = _database_report_payload(row)
        # Only store fields consumed by OperatorDbRecord, never login or URL data.
        keys = ("operator_id", "nik", "status", "finished_at", "nama_pengguna",
                "jenis_pengguna", "reason", "error_label", "error")
        cast(QuotaJournal, self._journal).stage({key: payload[key] for key in keys}, source)

    def _deliver_event(self, event_id, source, payload) -> None:
        self._sync(self._manager, source, [payload], event_id=event_id)

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

        if self._journal is not None and rows is not None:
            for row in rows:
                if counts_toward_quota(row.status):
                    self._journal.drain(self._deliver_event)
                else:
                    self._sync(manager, report_path, [row])
            return
        self._sync(manager, report_path, rows)

    def _sync(self, manager, report_path, rows, *, event_id=None):
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
                if event_id is not None and not self._receipts_ready:
                    manager.ensure_delivery_receipts(connection)
                    self._receipts_ready = True
                payloads = rows if event_id is not None else (_database_report_payload(row) for row in rows)
                summary = manager.sync_report_payloads(
                    payloads,
                    source=str(report_path),
                    connection=connection,
                    **({"delivery_id": event_id} if event_id is not None else {}),
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
            with suppress(Exception):  # Cleanup error reporting is best-effort.
                logger.bind(
                    event="report.db_connection.close_failed",
                ).exception("Failed to close report database connection")

    def close(self) -> None:
        """Release database resources owned by this syncer."""

        try:
            self._discard_connection()
        finally:
            if self._journal is not None:
                self._journal.close()
                self._journal = None

    def _ensure_database(self, manager: OperatorDatabaseManager) -> None:
        if self._database_ready:
            return

        with _DATABASE_SETUP_LOCK:
            if self._database_ready:
                return
            manager.ensure_database_and_tables()
            self._database_ready = True


def _database_report_payload(row: Any) -> dict[str, Any]:
    """Keep raw NIK routing while removing credentials from DB report text."""
    payload = asdict(row)
    for key in ("url", "reason", "error"):
        payload[key] = sanitize_text(payload.get(key, ""))
    return payload
