from typing import Any, Callable


class AccountRunner:
    """Run one account end-to-end using injected infrastructure and workflow factories."""

    def __init__(
        self,
        *,
        reporter_factory: Callable[..., Any],
        limiter_factory: Callable[[], Any],
        browser_session_factory: Callable[[Any], Any],
        transaction_processor_factory: Callable[[Any, Any, Any, Any], Any],
        logger: Any,
        report_syncer: Callable[[Any], Any] | None = None,
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

        self.logger.bind(
            event="account.run.started",
            operator=config.email_user,
            nik_count=len(config.nik),
        ).info("Account run started")

        try:
            with self.browser_session_factory(config) as session:
                session.initialize_session()
                processor = self.transaction_processor_factory(
                    config,
                    session.require_page(),
                    reporter,
                    limiter,
                )
                processor.process_all_niks()
        except Exception:
            is_successful = False
            self.logger.bind(
                event="account.run.fatal_error",
                operator=config.email_user,
            ).exception("Fatal account-level error")
        finally:
            reporter.write_files()
            if self.report_syncer is not None:
                try:
                    self.report_syncer(reporter)
                except Exception:
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
