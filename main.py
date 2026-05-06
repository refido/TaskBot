from src.application.services.account_runner import AccountRunner
from src.application.use_cases.process_account import process_account, process_accounts
from src.config import Config
from src.infrastructure.browser.playwright_session import BrowserSession
from src.logging_utils import configure_logging, logger
from src.orchestration.transaction_processor import TransactionProcessor
from src.web.rate_limiter import SkipRateLimiter
from src.web.reporter import TransactionReporter


def _build_skip_rate_limiter() -> SkipRateLimiter:
    return SkipRateLimiter(
        max_skips=8,
        window_seconds=48,
        min_cooldown=48,
        jitter_seconds=5,
    )


def _build_account_runner() -> AccountRunner:
    return AccountRunner(
        reporter_factory=TransactionReporter,
        limiter_factory=_build_skip_rate_limiter,
        browser_session_factory=BrowserSession,
        transaction_processor_factory=TransactionProcessor,
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
