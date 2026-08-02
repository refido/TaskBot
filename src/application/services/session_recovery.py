from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from src.logging_utils import logger
from src.web.session_state import is_login_page


class SessionRecoveryService:
    """Owns session probes and recovery for the transaction workflow."""

    def __init__(
        self,
        *,
        page,
        config: Any,
        dashboard,
        login,
        load_state: str,
        logged_out_check_timeout_ms: int,
        session_probe_interval_ms: int,
        login_page_detector: Callable[..., bool] = is_login_page,
    ) -> None:
        self.page = page
        self.config = config
        self.dashboard = dashboard
        self.login = login
        self.load_state = load_state
        self.logged_out_check_timeout_ms = logged_out_check_timeout_ms
        self.session_probe_interval_ms = session_probe_interval_ms
        self.login_page_detector = login_page_detector
        self._last_session_probe_at = time.monotonic()

    def handle_session_recovery(self) -> None:
        self.reset_probe()
        if self.check_if_logged_out():
            self.restore_logged_out_session()
            return

        try:
            self.dashboard.ensure_on_dashboard()
            return
        except Exception:
            self.page.goto(self.config.url_application)
            self.page.wait_for_load_state(self.load_state)

        if self.check_if_logged_out():
            self.restore_logged_out_session()
            return

        self.dashboard.ensure_on_dashboard()

    def restore_logged_out_session(self) -> None:
        self.page.goto(self.config.url_application)
        self.page.wait_for_load_state(self.load_state)
        self.login.login(self.config.email_user, self.config.pin_user)
        self.page.wait_for_load_state(self.load_state)
        self.dashboard.ensure_on_dashboard()
        self.reset_probe()

    def check_if_logged_out(self) -> bool:
        return self.login_page_detector(
            self.page,
            timeout_ms=self.logged_out_check_timeout_ms,
        )

    def probe_if_due(self, *, reason: str, force: bool = False) -> None:
        now = time.monotonic()
        elapsed_ms = (now - self._last_session_probe_at) * 1000

        if not force and elapsed_ms < self.session_probe_interval_ms:
            return

        self._last_session_probe_at = now
        if not self.check_if_logged_out():
            return

        logger.bind(
            event="transaction.session_probe.login_detected",
            operator=self.config.email_user,
            reason=reason,
            elapsed_ms=int(elapsed_ms),
        ).warning("Login page detected during periodic session probe")
        self.restore_logged_out_session()

    def reset_probe(self) -> None:
        self._last_session_probe_at = time.monotonic()
