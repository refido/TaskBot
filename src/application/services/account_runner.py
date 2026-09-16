from collections.abc import Callable
from contextlib import suppress
from typing import Any

from src.logging_utils import operator_logging_context


class AccountRunner:
    """Run one account end-to-end using injected infrastructure and workflow factories."""

    _DATABASE_BATCH_SIZE = 1

    def __init__(
        self,
        *,
        reporter_factory: Callable[..., Any],
        limiter_factory: Callable[[], Any],
        browser_session_factory: Callable[[Any], Any],
        transaction_processor_factory: Callable[[Any, Any, Any, Any], Any],
        logger: Any,
        report_syncer: Callable[..., Any] | None = None,
        outcome: dict[str, Any] | None = None,
    ) -> None:
        self.reporter_factory = reporter_factory
        self.limiter_factory = limiter_factory
        self.browser_session_factory = browser_session_factory
        self.transaction_processor_factory = transaction_processor_factory
        self.report_syncer = report_syncer
        self.logger = logger
        self.outcome = outcome if outcome is not None else {}

    def run(self, config: Any) -> tuple[str, bool]:
        """Return the legacy tuple, with True reserved for a clean account outcome."""
        self.outcome.clear()
        self.outcome.update(
            status="failed", execution_status="failed", persistence_status="failed"
        )
        operator_id = getattr(config, "operator_id", "") or "operator_01"
        with operator_logging_context(operator_id):
            return self._run_with_context(config, operator_id)

    def _run_with_context(self, config: Any, operator_id: str) -> tuple[str, bool]:
        reporter = self.reporter_factory(operator=operator_id)
        limiter = self.limiter_factory()
        is_successful = True
        batch_sync_configured = False
        finalization_error: Exception | None = None
        execution_status = "completed"
        persistence_status = "successful"

        self.logger.bind(
            event="account.run.started",
            operator_id=operator_id,
            nik_count=len(config.nik),
        ).info("Account run started")

        try:
            batch_sync_configured = self._configure_batch_sync(reporter)

            with self.browser_session_factory(config) as session:
                session.initialize_session()

                processor = self.transaction_processor_factory(
                    config,
                    session.require_page(),
                    reporter,
                    limiter,
                )

                processor.process_all_niks()

        except Exception:  # noqa: BLE001 - account boundary records all infrastructure failures.
            is_successful = False
            execution_status = "failed"

            self.logger.bind(
                event="account.run.fatal_error",
                operator_id=operator_id,
            ).exception("Fatal account-level error")

        finally:
            # Processing and DB sync errors keep the existing unsuccessful-result
            # contract. Otherwise, re-raise the first finalization error after
            # cleanup; later failures are logged without replacing the primary one.
            try:
                reporter.write_files()
            except Exception as exc:  # noqa: BLE001 - still attempt final sync and close.
                persistence_status = "failed"
                if is_successful:
                    finalization_error = exc
                is_successful = False
                with suppress(Exception):  # Cleanup error reporting is best-effort.
                    self.logger.bind(
                        event="account.report_write_error",
                        operator_id=operator_id,
                    ).exception("Final report file writing failed")

            if self.report_syncer is not None:
                try:
                    if batch_sync_configured:
                        reporter.flush_pending_batches()
                    else:
                        self.report_syncer(reporter)

                except Exception:  # noqa: BLE001 - database errors must mark the account unsuccessful.
                    is_successful = False
                    persistence_status = "failed"

                    with suppress(Exception):  # Cleanup error reporting is best-effort.
                        self.logger.bind(
                            event="account.report_db_sync_error",
                            operator_id=operator_id,
                        ).exception("Report database sync failed")

                finally:
                    try:
                        close_syncer = getattr(self.report_syncer, "close", None)
                        if callable(close_syncer):
                            close_syncer()
                    except Exception as exc:  # noqa: BLE001 - preserve the primary failure.
                        persistence_status = "failed"
                        if is_successful:
                            finalization_error = exc
                        is_successful = False
                        with suppress(Exception):  # Cleanup error reporting is best-effort.
                            self.logger.bind(
                                event="account.report_db_close_error",
                                operator_id=operator_id,
                            ).exception("Report database syncer close failed")

            try:
                reporter.print_summary()
            except Exception as exc:  # noqa: BLE001 - summary cannot replace a primary failure.
                persistence_status = "failed"
                if is_successful:
                    finalization_error = exc
                is_successful = False
                with suppress(Exception):  # Cleanup error reporting is best-effort.
                    self.logger.bind(
                        event="account.report_summary_error",
                        operator_id=operator_id,
                    ).exception("Final report summary printing failed")

        transactions = self._transaction_outcome(reporter, config)
        status = (
            (transactions["transaction_status"] or "completed")
            if is_successful else "failed"
        )
        self.outcome.update(
            **transactions,
            execution_status=execution_status,
            persistence_status=persistence_status,
            status=status,
        )
        self.logger.bind(
            event="account.run.finished",
            operator_id=operator_id,
            success=status == "completed",
            status=status,
            execution_status=execution_status,
            persistence_status=persistence_status,
            transaction_status=transactions["transaction_status"],
        ).info("Account run finished")

        if finalization_error is not None:
            raise finalization_error

        return operator_id, status == "completed"

    @staticmethod
    def _transaction_outcome(reporter: Any, config: Any) -> dict[str, Any]:
        """Count terminal rows once; workflow/retry events and summaries are not outcomes."""
        rows = getattr(reporter, "rows", None)
        counts: dict[str, int] = {}
        observed_niks: set[str] = set()
        if rows is None:
            return {"transaction_status": None}  # Legacy reporters may expose no rows.
        for row in rows:
            if not hasattr(row, "status") or not hasattr(row, "nik"):
                return {"transaction_status": None}
            counts[row.status] = counts.get(row.status, 0) + 1
            observed_niks.add(str(row.nik))
        requested_niks = {str(nik) for nik in config.nik}
        remaining = len(requested_niks - observed_niks)
        counts["total"] = sum(counts.values())
        return {
            "transaction_status": (
                "completed"
                if not remaining and counts.get("completed", 0) == counts["total"]
                else "completed_with_errors"
            ),
            "counts": counts,
            "transaction_error_count": (
                counts.get("error", 0) + counts.get("failed_puzzle_solve", 0)
            ),
            "requested_nik_count": len(requested_niks),
            "processed_nik_count": len(requested_niks & observed_niks),
            "remaining_nik_count": remaining,
        }

    def _configure_batch_sync(self, reporter: Any) -> bool:
        if self.report_syncer is None:
            return False

        configure_batch_sync = getattr(reporter, "configure_batch_sync", None)
        flush_pending_batches = getattr(reporter, "flush_pending_batches", None)
        if not callable(configure_batch_sync) or not callable(flush_pending_batches):
            return False

        configure_batch_sync(
            lambda rows: self.report_syncer(reporter, rows),
            batch_size=self._DATABASE_BATCH_SIZE,
        )
        return True
