from concurrent.futures import ThreadPoolExecutor, as_completed

from src.config import Config
from src.logging_utils import configure_logging, logger
from src.orchestration.browser_session import BrowserSession
from src.orchestration.transaction_processor import TransactionProcessor
from src.web.rate_limiter import SkipRateLimiter
from src.web.reporter import TransactionReporter


def run_account(config: Config) -> tuple[str, bool]:
    """
    Run a full transaction workflow for one account.

    Each call creates its own BrowserSession (and sync_playwright) so it can be
    executed safely inside a thread.
    """
    reporter = TransactionReporter(operator=config.email_user)
    limiter = SkipRateLimiter(
        max_skips=5, window_seconds=60, min_cooldown=60, jitter_seconds=5
    )

    is_successful = True

    logger.bind(
        event="account.run.started",
        operator=config.email_user,
        nik_count=len(config.nik),
    ).info("Account run started")

    try:
        with BrowserSession(config) as session:
            session.initialize_session()
            processor = TransactionProcessor(
                config, session.require_page(), reporter, limiter
            )
            processor.process_all_niks()
    except Exception:
        is_successful = False
        logger.bind(
            event="account.run.fatal_error", operator=config.email_user
        ).exception("Fatal account-level error")
    finally:
        reporter.write_files()
        reporter.print_summary()

    logger.bind(
        event="account.run.finished",
        operator=config.email_user,
        success=is_successful,
    ).info("Account run finished")

    return config.email_user, is_successful


def main() -> None:
    """Main entry point."""
    logging_meta = configure_logging()
    logger.bind(
        event="app.start",
        run_id=logging_meta["run_id"],
        json_log_path=logging_meta["json_log_path"],
    ).info("TaskBot started")

    config = Config()
    account_configs = config.account_configs()

    if not account_configs:
        raise ValueError(
            "No account configuration found. Set EMAIL/PIN/NIK or EMAIL_1/PIN_1/NIK_1."
        )

    if len(account_configs) == 1:
        run_account(account_configs[0])
        return

    logger.bind(
        event="app.concurrent_start",
        account_count=len(account_configs),
    ).info("Running accounts concurrently using threads")

    with ThreadPoolExecutor(
        max_workers=len(account_configs), thread_name_prefix="taskbot-account"
    ) as executor:
        future_to_email = {
            executor.submit(run_account, account_config): account_config.email_user
            for account_config in account_configs
        }

        for future in as_completed(future_to_email):
            email = future_to_email[future]
            try:
                _, is_successful = future.result()
                status = "completed" if is_successful else "completed with errors"
                logger.bind(
                    event="account.thread.finished",
                    operator=email,
                    success=is_successful,
                    status=status,
                ).info("Thread finished")
            except Exception:
                logger.bind(
                    event="account.thread.crashed",
                    operator=email,
                ).exception("Thread crashed unexpectedly")


if __name__ == "__main__":
    main()
