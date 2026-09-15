from collections.abc import Callable, Mapping, Sequence
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
    outcomes: Mapping[str, Mapping[str, Any]] | None = None,
    max_concurrent_accounts: int | None = None,
) -> list[tuple[str, bool]]:
    """Run all accounts with an optional cap; retain completion-ordered results."""
    if max_concurrent_accounts is not None and (
        isinstance(max_concurrent_accounts, bool)
        or not isinstance(max_concurrent_accounts, int)
        or max_concurrent_accounts <= 0
    ):
        raise ValueError("max_concurrent_accounts must be a positive integer or None.")
    configs = list(account_configs)
    if not configs:
        return []

    if len(configs) == 1:
        return [run_account(configs[0])]

    max_workers = min(len(configs), max_concurrent_accounts or len(configs))
    log.bind(
        event="app.concurrent_start",
        account_count=len(configs),
        max_concurrent_accounts=max_concurrent_accounts,
        max_workers=max_workers,
    ).info("Running accounts concurrently using threads")

    results: list[tuple[str, bool]] = []
    with ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="taskbot-account",
    ) as executor:
        future_to_operator_id = {
            executor.submit(run_account, account_config): getattr(
                account_config, "operator_id", "operator_01"
            )
            for account_config in configs
        }

        for future in as_completed(future_to_operator_id):
            operator_id = future_to_operator_id[future]
            try:
                result = future.result()
                _, is_successful = result
                detail = (outcomes or {}).get(operator_id, {})
                status = detail.get("status") or ("completed" if is_successful else "failed")
                log.bind(
                    event="account.thread.finished",
                    operator_id=operator_id,
                    success=is_successful,
                    status=status,
                ).info("Thread finished")
                results.append(result)
            except Exception:  # noqa: BLE001 - isolate failures between account threads.
                log.bind(
                    event="account.thread.crashed",
                    operator_id=operator_id,
                ).exception("Thread crashed unexpectedly")

    return results
