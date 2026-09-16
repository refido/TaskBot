# rate_limiter.py
import random
import time
from collections import deque
from collections.abc import Callable
from math import ceil, isfinite
from threading import Lock
from typing import ClassVar

from playwright.sync_api import Page

from src.logging_utils import log_print


class LoginRetryRateLimiter:
    """Schedule login retries with a minimum delay per account.

    Bootstrap login is intentionally outside this limiter. Each call represents
    a reauthentication attempt after the application has returned to its login
    page, so even the first reserved retry waits for the configured interval.
    Shared reservations keep concurrent recovery paths for the same account
    from attempting to authenticate at the same time.
    """

    _reservation_lock = Lock()
    _next_retry_at_by_account: ClassVar[dict[str, float]] = {}

    def __init__(
        self,
        min_retry_delay_seconds: float = 120.0,
        *,
        monotonic_func: Callable[[], float] = time.monotonic,
    ) -> None:
        self.min_retry_delay_seconds = self._validate_duration(min_retry_delay_seconds)
        self._monotonic = monotonic_func

    def wait_before_retry(self, page: Page, account_key: str) -> None:
        """Wait for this account's atomically reserved reauthentication slot."""
        delay_seconds = self._reserve_delay_seconds(account_key)
        wait_ms = ceil(delay_seconds * 1000)
        log_print(
            f"Rate-limiting login retry for {delay_seconds:.1f}s",
            event="login.retry.rate_limit",
            wait_ms=wait_ms,
        )
        page.wait_for_timeout(wait_ms)

    def _reserve_delay_seconds(self, account_key: str) -> float:
        normalized_key = str(account_key).strip().casefold()
        if not normalized_key:
            raise ValueError("account_key must not be empty")

        with self._reservation_lock:
            now = float(self._monotonic())
            previously_reserved_at = self._next_retry_at_by_account.get(
                normalized_key,
                now,
            )
            retry_at = max(now, previously_reserved_at) + self.min_retry_delay_seconds
            LoginRetryRateLimiter._next_retry_at_by_account[normalized_key] = retry_at
        return retry_at - now

    @classmethod
    def _reset_shared_reservations_for_tests(cls) -> None:
        """Reset shared retry slots for deterministic isolated tests."""
        with cls._reservation_lock:
            cls._next_retry_at_by_account.clear()

    @staticmethod
    def _validate_duration(value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("min_retry_delay_seconds must be a number")
        normalized = float(value)
        if not isfinite(normalized) or normalized < 0:
            raise ValueError("min_retry_delay_seconds must be finite and non-negative")
        return normalized


class CustomerUpdateRateLimiter:
    """Reserve globally paced slots for customer-update actions.

    Account runs each own a :class:`SkipRateLimiter`, but customer updates can
    execute concurrently across those accounts.  Reservations therefore share
    one monotonic timeline guarded by a lock.  This pacing is deliberately
    independent from skipped-NIK pressure.
    """

    _reservation_lock = Lock()
    _next_available_at = 0.0

    def __init__(
        self,
        min_interval_seconds: float = 1.0,
        jitter_seconds: float = 0.25,
        *,
        monotonic_func: Callable[[], float] = time.monotonic,
        jitter_func: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.min_interval_seconds = self._validate_duration(
            min_interval_seconds, "min_interval_seconds"
        )
        self.jitter_seconds = self._validate_duration(jitter_seconds, "jitter_seconds")
        self._monotonic = monotonic_func
        self._jitter = jitter_func

    def wait_before_action(self, page: Page, action: str) -> None:
        """Wait for this action's atomically reserved global time slot."""
        delay_seconds = self._reserve_delay_seconds()
        if delay_seconds <= 0:
            return

        wait_ms = ceil(delay_seconds * 1000)
        log_print(
            f"Pacing customer-update action {action!r} for {delay_seconds:.3f}s",
            event="customer.update.rate_limit",
            action=action,
            wait_ms=wait_ms,
        )
        page.wait_for_timeout(wait_ms)

    def _reserve_delay_seconds(self) -> float:
        with self._reservation_lock:
            now = float(self._monotonic())
            reserved_at = max(now, self._next_available_at)
            jitter = (
                float(self._jitter(0.0, self.jitter_seconds))
                if self.jitter_seconds
                else 0.0
            )
            if not isfinite(jitter) or jitter < 0:
                raise ValueError(
                    "Customer-update jitter must be finite and non-negative"
                )
            CustomerUpdateRateLimiter._next_available_at = (
                reserved_at + self.min_interval_seconds + jitter
            )
        return max(0.0, reserved_at - now)

    @classmethod
    def _reset_shared_reservations_for_tests(cls) -> None:
        """Reset shared pacing state for deterministic isolated tests."""
        with cls._reservation_lock:
            cls._next_available_at = 0.0

    @staticmethod
    def _validate_duration(value: float, name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{name} must be a number")
        normalized = float(value)
        if not isfinite(normalized) or normalized < 0:
            raise ValueError(f"{name} must be finite and non-negative")
        return normalized


class SkipRateLimiter:
    def __init__(
        self,
        max_skips: int = 5,
        window_seconds: int = 60,
        min_cooldown: int = 60,
        jitter_seconds: int = 5,
        *,
        update_min_interval_seconds: float = 1.0,
        update_jitter_seconds: float = 0.25,
        customer_update_rate_limiter: CustomerUpdateRateLimiter | None = None,
    ) -> None:
        self.max_skips = max_skips
        self.window = window_seconds
        self.min_cooldown = min_cooldown
        self.jitter_seconds = jitter_seconds
        self.skips: deque[float] = deque()  # stores timestamps of recent skipped NIKs
        self.customer_update_rate_limiter = (
            customer_update_rate_limiter
            if customer_update_rate_limiter is not None
            else CustomerUpdateRateLimiter(
                min_interval_seconds=update_min_interval_seconds,
                jitter_seconds=update_jitter_seconds,
            )
        )

    def record_skip(self) -> None:
        now = time.time()
        self.skips.append(now)
        self._prune(now)

    def record_success(self) -> None:
        # Success does not add pressure; just prune old entries
        self._prune(time.time())

    def _prune(self, now: float) -> None:
        while self.skips and now - self.skips[0] > self.window:
            self.skips.popleft()

    def wait_if_needed(self, page: Page) -> None:
        now = time.time()
        self._prune(now)
        if len(self.skips) < self.max_skips:
            return

        oldest = self.skips[0]
        remaining = self.window - (now - oldest)
        if remaining <= 0:
            return

        jitter = random.uniform(0, self.jitter_seconds)
        cooldown = max(self.min_cooldown, remaining) + jitter
        log_print(
            f"Rate limit reached: {len(self.skips)} skipped in {self.window}s. Cooling {cooldown:.1f}s"
        )
        page.wait_for_timeout(int(cooldown * 1000))
        # After waiting, clear the window to start fresh
        self.skips.clear()

    def wait_before_update_action(self, page: Page, action: str) -> None:
        """Delegate update pacing without reading or mutating skip pressure."""
        self.customer_update_rate_limiter.wait_before_action(page, action)
