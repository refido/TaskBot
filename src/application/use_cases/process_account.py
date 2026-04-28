from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any


def process_account(config: Any, *, account_runner: Any) -> tuple[str, bool]:
    """Run one configured account through the injected account runner."""
    return account_runner.run(config)


def process_accounts(
    account_configs: Sequence[Any],
    *,
    run_account: Callable[[Any], tuple[str, bool]],
    log: Any,
) -> list[tuple[str, bool]]:
    """Run one or more accounts while preserving the existing thread-per-account behavior."""
    configs = list(account_configs)
    if not configs:
        return []

    if len(configs) == 1:
        return [run_account(configs[0])]

    log.bind(
        event="app.concurrent_start",
        account_count=len(configs),
    ).info("Running accounts concurrently using threads")

    results: list[tuple[str, bool]] = []
    with ThreadPoolExecutor(
        max_workers=len(configs),
        thread_name_prefix="taskbot-account",
    ) as executor:
        future_to_email = {
            executor.submit(run_account, account_config): account_config.email_user
            for account_config in configs
        }

        for future in as_completed(future_to_email):
            email = future_to_email[future]
            try:
                result = future.result()
                _, is_successful = result
                status = "completed" if is_successful else "completed with errors"
                log.bind(
                    event="account.thread.finished",
                    operator=email,
                    success=is_successful,
                    status=status,
                ).info("Thread finished")
                results.append(result)
            except Exception:
                log.bind(
                    event="account.thread.crashed",
                    operator=email,
                ).exception("Thread crashed unexpectedly")

    return results
