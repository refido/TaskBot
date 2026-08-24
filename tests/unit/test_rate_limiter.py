from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from src.web.rate_limiter import (
    CustomerUpdateRateLimiter,
    LoginRetryRateLimiter,
    SkipRateLimiter,
)


class FakePage:
    def __init__(self) -> None:
        self.timeouts: list[int] = []

    def wait_for_timeout(self, timeout_ms: int) -> None:
        self.timeouts.append(timeout_ms)


@pytest.fixture(autouse=True)
def reset_shared_rate_limiter_reservations():
    CustomerUpdateRateLimiter._reset_shared_reservations_for_tests()
    LoginRetryRateLimiter._reset_shared_reservations_for_tests()
    yield
    CustomerUpdateRateLimiter._reset_shared_reservations_for_tests()
    LoginRetryRateLimiter._reset_shared_reservations_for_tests()


def test_login_retries_wait_two_minutes_and_serialize_same_account():
    first_page = FakePage()
    second_page = FakePage()
    limiter = LoginRetryRateLimiter(
        min_retry_delay_seconds=120,
        monotonic_func=lambda: 100.0,
    )

    limiter.wait_before_retry(first_page, "Operator_01")
    limiter.wait_before_retry(second_page, "operator_01")

    assert first_page.timeouts == [120_000]
    assert second_page.timeouts == [240_000]


def test_each_sequential_login_retry_waits_the_full_default_two_minutes():
    clock = [100.0]

    class AdvancingPage(FakePage):
        def wait_for_timeout(self, timeout_ms: int) -> None:
            super().wait_for_timeout(timeout_ms)
            clock[0] += timeout_ms / 1000

    page = AdvancingPage()
    limiter = LoginRetryRateLimiter(monotonic_func=lambda: clock[0])

    limiter.wait_before_retry(page, "operator_01")
    limiter.wait_before_retry(page, "operator_01")

    assert page.timeouts == [120_000, 120_000]


def test_login_retry_reservations_are_independent_between_accounts():
    first_page = FakePage()
    second_page = FakePage()
    limiter = LoginRetryRateLimiter(
        min_retry_delay_seconds=120,
        monotonic_func=lambda: 100.0,
    )

    limiter.wait_before_retry(first_page, "operator_01")
    limiter.wait_before_retry(second_page, "operator_02")

    assert first_page.timeouts == [120_000]
    assert second_page.timeouts == [120_000]


@pytest.mark.parametrize(
    ("value", "error_type"),
    [(-1, ValueError), (True, TypeError), (float("inf"), ValueError)],
)
def test_login_retry_limiter_rejects_invalid_delay(value, error_type):
    with pytest.raises(error_type):
        LoginRetryRateLimiter(min_retry_delay_seconds=value)


def test_customer_update_reservations_are_shared_and_thread_safe():
    worker_count = 4
    barrier = Barrier(worker_count)
    pages = [FakePage() for _ in range(worker_count)]
    limiters = [
        CustomerUpdateRateLimiter(
            min_interval_seconds=1,
            jitter_seconds=0,
            monotonic_func=lambda: 100.0,
        )
        for _ in range(worker_count)
    ]

    def reserve(index: int) -> None:
        barrier.wait()
        limiters[index].wait_before_action(pages[index], f"action-{index}")

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [pool.submit(reserve, index) for index in range(worker_count)]
        for future in futures:
            future.result()

    reserved_delays_ms = sorted(
        page.timeouts[0] if page.timeouts else 0 for page in pages
    )
    assert reserved_delays_ms == [0, 1000, 2000, 3000]


def test_skip_limiter_delegates_update_pacing_without_touching_skip_pressure():
    page = FakePage()
    update_limiter = CustomerUpdateRateLimiter(
        min_interval_seconds=2,
        jitter_seconds=0,
        monotonic_func=lambda: 50.0,
    )
    limiter = SkipRateLimiter(customer_update_rate_limiter=update_limiter)
    limiter.skips.extend((10.0, 20.0))
    original_skips = tuple(limiter.skips)

    limiter.wait_before_update_action(page, "open_update_form")
    limiter.wait_before_update_action(page, "submit_update_form")

    assert page.timeouts == [2000]
    assert tuple(limiter.skips) == original_skips


def test_customer_update_pacing_includes_configured_jitter_in_next_reservation():
    page = FakePage()
    limiter = CustomerUpdateRateLimiter(
        min_interval_seconds=1,
        jitter_seconds=0.5,
        monotonic_func=lambda: 75.0,
        jitter_func=lambda _low, high: high,
    )

    limiter.wait_before_action(page, "first")
    limiter.wait_before_action(page, "second")

    assert page.timeouts == [1500]


@pytest.mark.parametrize(
    ("field", "value", "error_type"),
    [
        ("min_interval_seconds", -1, ValueError),
        ("min_interval_seconds", True, TypeError),
        ("jitter_seconds", float("inf"), ValueError),
    ],
)
def test_customer_update_pacing_configuration_rejects_invalid_durations(
    field, value, error_type
):
    kwargs = {"min_interval_seconds": 1, "jitter_seconds": 0}
    kwargs[field] = value

    with pytest.raises(error_type):
        CustomerUpdateRateLimiter(**kwargs)
