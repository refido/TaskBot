# rate_limiter.py
import random
import time
from collections import deque
from typing import Deque

from playwright.sync_api import Page

from src.logging_utils import log_print


class SkipRateLimiter:
    def __init__(
        self,
        max_skips: int = 10,
        window_seconds: int = 60,
        min_cooldown: int = 60,
        jitter_seconds: int = 5,
    ) -> None:
        self.max_skips = max_skips
        self.window = window_seconds
        self.min_cooldown = min_cooldown
        self.jitter_seconds = jitter_seconds
        self.skips: Deque[float] = deque()  # stores timestamps of recent skipped NIKs

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
