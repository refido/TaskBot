"""UI probes without customer-state priority, polling policy or actions."""

from collections.abc import Callable
from typing import Any


class BrowserPrecheckObserver:
    """Read current dependencies on demand; retain no browser or workflow state."""

    def customer_entry(self, dashboard: Any, *, timeout_ms: int) -> str | None:
        snapshot = getattr(dashboard, "get_visible_customer_entry", None)
        if snapshot is not None:
            return snapshot()

        # Compatibility for lightweight page-object test doubles.
        resolver = dashboard.resolve_customer_entry
        try:
            return resolver(detect_timeout=timeout_ms)
        except TypeError:
            return resolver()

    def precheck_modal(self, dashboard: Any) -> str | None:
        try:
            return dashboard.get_visible_precheck_modal()
        except AttributeError:
            return None

    def login_visible(
        self,
        page: Any,
        detector: Callable[..., bool],
        *,
        timeout_ms: int,
    ) -> bool:
        try:
            return bool(detector(page, timeout_ms=timeout_ms))
        except TypeError:
            return bool(detector(page))
        except AttributeError:
            return False

    def component_visible(self, component: Any) -> bool:
        try:
            return bool(component.is_visible())
        except AttributeError, TypeError:
            # Lightweight test doubles may not expose Playwright locators.
            return False
