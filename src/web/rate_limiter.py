# rate_limiter.py
import random
import time
from collections import deque


class SkipRateLimiter:
    def __init__(
        self, max_skips=10, window_seconds=60, min_cooldown=60, jitter_seconds=5
    ):
        self.max_skips = max_skips
        self.window = window_seconds
        self.min_cooldown = min_cooldown
        self.jitter_seconds = jitter_seconds
        self.skips = deque()  # stores timestamps of recent skipped NIKs

    def record_skip(self):
        now = time.time()
        self.skips.append(now)
        self._prune(now)

    def record_success(self):
        # Success does not add pressure; just prune old entries
        self._prune(time.time())

    def _prune(self, now):
        while self.skips and now - self.skips[0] > self.window:
            self.skips.popleft()

    def wait_if_needed(self, page):
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
        print(
            f"Rate limit reached: {len(self.skips)} skipped in {self.window}s. Cooling {cooldown:.1f}s"
        )
        page.wait_for_timeout(int(cooldown * 1000))
        # After waiting, clear the window to start fresh
        self.skips.clear()
