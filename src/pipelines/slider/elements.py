from __future__ import annotations

from playwright.sync_api import Locator, Page

from src.logging_utils import log_print
from src.pipelines.slider.types import SliderConfig, SliderElements


class ElementResolver:
    """Resolves slider DOM elements."""

    _BG_VISIBLE_TIMEOUT_MS: int = 8000
    _CTRL_VISIBLE_TIMEOUT_MS: int = 6000
    _KNOB_VISIBLE_TIMEOUT_MS: int = 2000

    def __init__(self, config: SliderConfig) -> None:
        self.config = config

    def resolve(self, page: Page) -> SliderElements:
        """Locate and return slider elements."""
        bg_el = page.locator(self.config.bg_selector).first
        bg_el.wait_for(state="visible", timeout=self._BG_VISIBLE_TIMEOUT_MS)

        root = self._find_root_container(page, bg_el)
        control = self._find_control(root)
        knob = self._find_knob(root, control)

        self._prepare_elements(page, root, control, knob)
        return SliderElements(root=root, bg_el=bg_el, control=control, knob=knob)

    def _find_root_container(self, page: Page, bg_el: Locator) -> Locator:
        containers = page.locator(self.config.container_selector)
        count = containers.count()

        if count > 0:
            try:
                root = containers.filter(has=bg_el).first
                if root.count() > 0:
                    return root
            except Exception as exc:
                log_print(f"[ElementResolver] Filter error: {exc}")

        return bg_el.locator(
            "xpath=ancestor::div[contains(@class,'rc-slider-captcha')]"
        ).first

    def _find_control(self, root: Locator) -> Locator:
        control = root.locator(self.config.rail_selector).first
        if control.count() == 0:
            control = root.locator("div.rc-slider-captcha-control").first
        return control

    def _find_knob(self, root: Locator, control: Locator) -> Locator:
        knob = root.locator(self.config.knob_selector).first
        if knob.count() == 0:
            knob = control.locator(
                "span.rc-slider-captcha-button.rc-slider-captcha-control-button"
            ).first
        return knob

    def _prepare_elements(
        self, page: Page, root: Locator, control: Locator, knob: Locator
    ) -> None:
        try:
            root.scroll_into_view_if_needed(timeout=1000)
            root.hover()
            page.wait_for_timeout(120)
        except Exception as exc:
            log_print(f"[ElementResolver] Preparation error: {exc}")

        control.wait_for(state="visible", timeout=self._CTRL_VISIBLE_TIMEOUT_MS)

        try:
            knob.wait_for(state="visible", timeout=self._KNOB_VISIBLE_TIMEOUT_MS)
        except Exception as exc:
            log_print(f"[ElementResolver] Knob visibility error: {exc}")
