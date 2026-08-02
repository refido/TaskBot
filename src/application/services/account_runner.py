from collections.abc import Callable
from typing import Any


class AccountRunner:
    """Run one account end-to-end using injected infrastructure and workflow factories."""

    _DATABASE_BATCH_SIZE = 100

    def __init__(
        self,
        *,
        reporter_factory: Callable[..., Any],
        limiter_factory: Callable[[], Any],
        browser_session_factory: Callable[[Any], Any],
        transaction_processor_factory: Callable[[Any, Any, Any, Any], Any],
        logger: Any,
        report_syncer: Callable[..., Any] | None = None,
    ) -> None:
        self.reporter_factory = reporter_factory
        self.limiter_factory = limiter_factory
        self.browser_session_factory = browser_session_factory
        self.transaction_processor_factory = transaction_processor_factory
        self.report_syncer = report_syncer
        self.logger = logger

    def run(self, config: Any) -> tuple[str, bool]:
        reporter = self.reporter_factory(operator=config.email_user)
        limiter = self.limiter_factory()
        is_successful = True
        batch_sync_configured = False

        self.logger.bind(
            event="account.run.started",
            operator=config.email_user,
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
            self.logger.bind(
                event="account.run.fatal_error",
                operator=config.email_user,
            ).exception("Fatal account-level error")
        finally:
            reporter.write_files()
            if self.report_syncer is not None:
                try:
                    if batch_sync_configured:
                        reporter.flush_pending_batches()
                    else:
                        self.report_syncer(reporter)
                except Exception:  # noqa: BLE001 - database errors must mark the account unsuccessful.
                    is_successful = False
                    self.logger.bind(
                        event="account.report_db_sync_error",
                        operator=config.email_user,
                    ).exception("Report database sync failed")
            reporter.print_summary()

        self.logger.bind(
            event="account.run.finished",
            operator=config.email_user,
            success=is_successful,
        ).info("Account run finished")

        return config.email_user, is_successful

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
