"""Customer-type modal interaction; workflow decisions remain with callers."""

import re
from collections.abc import Callable

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, TimeoutError

_CUSTOMER_TYPE_SELECTION_ATTEMPTS = 3
_CUSTOMER_TYPE_SELECTION_VERIFY_MS = 5000

# The target application can take several seconds to react after a click.
# These waits are post-condition waits, not blind sleeps.
_CUSTOMER_TYPE_CONTINUE_ATTEMPTS = 3
_CUSTOMER_TYPE_CONTINUE_RESULT_TIMEOUT_MS = 20000
_CUSTOMER_TYPE_CONTINUE_POLL_MS = 250


class CustomerTypeModal:
    """Own UI interaction using current locators and narrow observation callbacks."""

    def __init__(
        self,
        *,
        page: Page,
        modal: Locator,
        is_visible: Callable[[Locator], bool],
        first_usable_locator: Callable[..., Locator | None],
        followup_probe: Callable[[], str | None],
        checkpoint: Callable[..., None],
        poll_states: Callable[[str], None],
        continue_locator_factory: Callable[[], Locator],
        log: Callable[..., None],
        expect_locator: Callable,
    ) -> None:
        self.page = page
        self.modal = modal
        self._is_visible = is_visible
        self._first_usable_locator = first_usable_locator
        self._followup_probe = followup_probe
        self._checkpoint = checkpoint
        self._poll_states = poll_states
        self._continue_locator_factory = continue_locator_factory
        self._log = log
        self._expect = expect_locator

    def is_selected(
        self,
        option_name: str,
    ) -> bool:
        if option_name in {"Rumah Tangga", "Usaha Mikro"}:
            return self.is_named_selected(option_name)

        return self.is_any_selected()

    def is_named_selected(
        self,
        option_name: str,
    ) -> bool:
        """
        Verify a known customer type using both:

        1. native radio checked state
        2. application's visible "Terpilih" state

        The second check is important because this site uses a custom styled
        radio component and its rendered selected state is authoritative UI
        evidence that the application accepted the selection.
        """

        radio = self.modal.locator(f'input[type="radio"][value="{option_name}"]').first

        # First preference: actual native checked property.
        try:
            if radio.count() > 0 and radio.is_checked():
                self._log(f"Customer type native radio is checked: {option_name}")
                return True
        except PlaywrightError:
            pass

        # Second signal: the website itself visually reports "Terpilih"
        # inside the label belonging to this exact radio.
        label = self.modal.locator(
            f'label:has(input[type="radio"][value="{option_name}"])'
        ).first

        try:
            if label.count() == 0 or not label.is_visible():
                return False

            selected_status = label.get_by_text(
                "Terpilih",
                exact=True,
            )

            if selected_status.count() > 0 and selected_status.is_visible():
                self._log(f"Customer type visual selection confirmed: {option_name}")
                return True

        except PlaywrightError:
            pass

        return False

    def is_any_selected(self) -> bool:
        """Check whether any customer-type radio is actually selected."""

        scope = self.modal

        native_radios = scope.locator("input[type='radio']")

        try:
            count = native_radios.count()
        except PlaywrightError:
            count = 0

        for index in range(count):
            radio = native_radios.nth(index)

            try:
                if radio.is_checked():
                    return True
            except PlaywrightError:
                continue

        aria_radios = scope.locator('[role="radio"]')

        try:
            count = aria_radios.count()
        except PlaywrightError:
            count = 0

        for index in range(count):
            radio = aria_radios.nth(index)

            try:
                if radio.get_attribute("aria-checked") == "true":
                    return True
            except PlaywrightError:
                continue

        return False

    def wait_for_selection(
        self,
        option_name: str,
        timeout_ms: int = _CUSTOMER_TYPE_SELECTION_VERIFY_MS,
    ) -> bool:
        """Wait for the selected radio state to propagate through the UI."""

        interval_ms = 100
        attempts = max(1, timeout_ms // interval_ms)

        for _ in range(attempts):
            if self.is_selected(option_name):
                return True

            self.page.wait_for_timeout(interval_ms)

        return self.is_selected(option_name)

    def select_with_confirmation(
        self,
        option_name: str,
        initial_choice: Locator,
    ) -> None:
        """
        Select the requested customer type and verify that the UI actually
        entered the checked state.

        Retrying selection is safe because the same radio option is used
        every time. We do not switch customer types merely because the
        frontend was slow to acknowledge the first click.
        """

        choice = initial_choice

        for attempt in range(
            1,
            _CUSTOMER_TYPE_SELECTION_ATTEMPTS + 1,
        ):
            # It may already have become selected while React was rerendering.
            if self.is_selected(option_name):
                self._log(f"Jenis Pelanggan '{option_name}' is already selected.")
                return

            self._log(
                f"Selecting Jenis Pelanggan '{option_name}' "
                f"(attempt {attempt}/"
                f"{_CUSTOMER_TYPE_SELECTION_ATTEMPTS})"
            )

            self._checkpoint("customer_type_radio_before_click")
            try:
                choice.scroll_into_view_if_needed(timeout=3000)

                choice.click(timeout=5000)

            except PlaywrightError as exc:
                self._log(
                    f"Click on Jenis Pelanggan '{option_name}' "
                    "did not complete cleanly.",
                    exc,
                )
            finally:
                self._checkpoint("customer_type_radio_after_click")

            if self.wait_for_selection(option_name):
                self._log(f"Jenis Pelanggan selection confirmed: {option_name}")
                return

            self._log(
                f"Jenis Pelanggan '{option_name}' was clicked but "
                "the radio is still not selected."
            )

            if attempt >= _CUSTOMER_TYPE_SELECTION_ATTEMPTS:
                break

            # React may have replaced the original node. Re-resolve the
            # locator instead of relying on the previous DOM element.
            if option_name in {"Rumah Tangga", "Usaha Mikro"}:
                refreshed_choice = self.find_named_choice(option_name)
            else:
                refreshed_choice = self.find_first_available_choice()

            if refreshed_choice is not None:
                choice = refreshed_choice

            self.page.wait_for_timeout(300)

        raise RuntimeError(
            f"Jenis Pelanggan '{option_name}' could not be confirmed "
            f"as selected after "
            f"{_CUSTOMER_TYPE_SELECTION_ATTEMPTS} attempts."
        )

    def find_named_choice(
        self,
        option_name: str,
    ) -> Locator | None:
        """
        Locate a customer-type option using the radio's stable value attribute.

        The wrapping label is the preferred click target because this application
        implements a custom styled radio component.
        """

        radio = self.modal.locator(f'input[type="radio"][value="{option_name}"]').first

        try:
            if radio.count() == 0:
                self._log(f"Customer type radio not found by value: {option_name}")
                return None
        except PlaywrightError:
            return None

        # Prefer clicking the visible wrapping label rather than the possibly
        # visually-hidden/custom-styled native radio input.
        label = self.modal.locator(
            f'label:has(input[type="radio"][value="{option_name}"])'
        ).first

        try:
            if label.count() > 0 and label.is_visible():
                self._log(f"Customer type label found by radio value: {option_name}")
                return label
        except PlaywrightError:
            pass

        # Fallback to native radio if it is itself usable.
        try:
            if radio.is_visible() and radio.is_enabled():
                self._log(f"Using native customer type radio: {option_name}")
                return radio
        except PlaywrightError:
            pass

        return None

    def find_first_available_choice(
        self,
    ) -> Locator | None:
        """
        Generic fallback when the known customer labels cannot be resolved.

        This allows the automation to survive markup changes while still
        avoiding generated CSS classes.
        """

        scope = self.modal

        candidates = (
            # Best case: accessible semantic radios.
            scope.get_by_role("radio"),
            # Common custom-radio implementation:
            # visible label wrapping a hidden native radio.
            scope.locator("label:has(input[type='radio'])"),
            # Last semantic fallback.
            scope.locator("input[type='radio']"),
        )

        for collection in candidates:
            choice = self._first_usable_locator(collection)

            if choice is not None:
                return choice

        return None

    def find_continue_button(
        self,
    ) -> Locator | None:
        """
        Locate the visible LANJUTKAN PENJUALAN button.

        Plain DOM button lookup is preferred here because Mantine portals can be
        visually active while an ancestor is aria-hidden, which can make role
        selectors ignore the live button.
        """

        button_pattern = re.compile(
            r"^\s*LANJUTKAN\s+PENJUALAN\s*$",
            re.IGNORECASE,
        )

        candidates = (
            self.modal.locator("button")
            .filter(has_text=button_pattern)
            .filter(visible=True),
            self.modal.get_by_role(
                "button",
                name=button_pattern,
            ),
            # Last fallback: visible exact-text button anywhere in the current
            # portal. The modal visibility checks around the click prevent this
            # fallback from being used after the flow has already transitioned.
            self.page.locator("button")
            .filter(has_text=button_pattern)
            .filter(visible=True),
        )

        for collection in candidates:
            button = self._first_usable_locator(
                collection,
                require_enabled=False,
            )
            if button is not None:
                return button

        return None

    def continue_with_confirmation(
        self,
        option_name: str,
    ) -> None:
        """
        Click LANJUTKAN PENJUALAN and confirm an actual state transition.

        A retry happens only when:
        - the same Jenis Pelanggan modal is still visible,
        - no known next modal/state has appeared, and
        - the previous click had a full post-click observation window.

        This avoids racing a slow target application while still recovering
        when a click was visually performed but not accepted by the app.
        """

        for attempt in range(1, _CUSTOMER_TYPE_CONTINUE_ATTEMPTS + 1):
            if not self._is_visible(self.modal):
                self._log(
                    "Jenis Pelanggan modal already disappeared; "
                    "continue action was accepted."
                )
                return

            # React may re-render and lose the selected state before the action.
            if not self.is_selected(option_name):
                self._log(
                    "Jenis Pelanggan selection is no longer active; "
                    "re-selecting before continuing."
                )

                refreshed_choice = (
                    self.find_named_choice(option_name)
                    if option_name in {"Rumah Tangga", "Usaha Mikro"}
                    else self.find_first_available_choice()
                )
                if refreshed_choice is None:
                    raise RuntimeError(
                        "Customer-type selection disappeared and could not "
                        "be located again."
                    )

                self.select_with_confirmation(
                    option_name,
                    refreshed_choice,
                )

            continue_button = self.wait_for_continue_button()
            if continue_button is None:
                raise RuntimeError(
                    "Jenis Pelanggan is selected, but LANJUTKAN PENJUALAN "
                    "did not become visible."
                )

            try:
                self._expect(continue_button).to_be_enabled(timeout=15000)
            except AssertionError as exc:
                # If the modal vanished while waiting, the previous action won.
                if not self._is_visible(self.modal):
                    return
                raise RuntimeError(
                    "LANJUTKAN PENJUALAN remained disabled after selecting "
                    "Jenis Pelanggan."
                ) from exc

            # Small stabilization check: ensure the selected state still exists
            # after the button becomes enabled.
            if not self.is_selected(option_name):
                self._log(
                    "Customer type changed while waiting for the continue "
                    "button; retrying selection."
                )
                continue

            self._log(
                "Clicking LANJUTKAN PENJUALAN from Jenis Pelanggan "
                f"(attempt {attempt}/{_CUSTOMER_TYPE_CONTINUE_ATTEMPTS})."
            )

            self._checkpoint(
                "customer_type_continue_before_click",
                target_name="Jenis Pelanggan LANJUTKAN PENJUALAN",
                target_locator_factory=self._continue_locator_factory,
            )
            try:
                continue_button.scroll_into_view_if_needed(timeout=5000)

                self._expect(continue_button).to_be_visible(timeout=5000)

                self._expect(continue_button).to_be_enabled(timeout=5000)

                self._log(
                    "Clicking LANJUTKAN PENJUALAN using direct "
                    "Playwright locator.click()"
                )

                continue_button.click(timeout=15000)
            except (PlaywrightError, AssertionError, TimeoutError) as exc:
                # A Playwright-side click error does not necessarily mean the
                # target ignored the action. Check post-state before failing.
                if self.wait_for_transition(timeout_ms=3000):
                    self._log(
                        "Jenis Pelanggan transitioned despite a click-side "
                        "exception; treating the action as successful."
                    )
                    return

                self._log(
                    "LANJUTKAN PENJUALAN click did not produce an immediate "
                    "transition.",
                    exc,
                )
            finally:
                self._checkpoint(
                    "customer_type_continue_after_click",
                    target_name="Jenis Pelanggan LANJUTKAN PENJUALAN",
                    target_locator_factory=self._continue_locator_factory,
                )
                self._poll_states("customer_type_continue_post_click_20s")

            if self.wait_for_transition(
                timeout_ms=_CUSTOMER_TYPE_CONTINUE_RESULT_TIMEOUT_MS
            ):
                self._log("Jenis Pelanggan continue action confirmed by UI transition.")
                return

            followup_state = self._followup_probe()

            if followup_state is not None:
                self._log(
                    "Next workflow state detected after Jenis Pelanggan: "
                    f"{followup_state}"
                )
                return

            if not self._is_visible(self.modal):
                return

            if attempt < _CUSTOMER_TYPE_CONTINUE_ATTEMPTS:
                self._log(
                    "Jenis Pelanggan modal remains the active workflow state "
                    "after the full post-click wait; reacquiring the button "
                    "and retrying."
                )

                self.page.wait_for_timeout(500)

        raise RuntimeError(
            "LANJUTKAN PENJUALAN from Jenis Pelanggan did not produce "
            "a state transition after "
            f"{_CUSTOMER_TYPE_CONTINUE_ATTEMPTS} verified attempts."
        )

    def wait_for_continue_button(
        self,
        timeout_ms: int = 15000,
    ) -> Locator | None:
        """Wait for the live continue button to be rendered in the active modal."""

        elapsed = 0
        poll_ms = 200

        while elapsed < timeout_ms:
            if not self._is_visible(self.modal):
                return None

            button = self.find_continue_button()
            if button is not None and self._is_visible(button):
                return button

            self.page.wait_for_timeout(poll_ms)
            elapsed += poll_ms

        return self.find_continue_button()

    def wait_for_transition(
        self,
        *,
        timeout_ms: int,
    ) -> bool:
        """
        Observe whether the customer-type action moved to another workflow state.

        Do not require the old Mantine modal to disappear first. The application
        can render the next modal while the previous one is still present during
        its closing transition.
        """

        elapsed = 0

        while elapsed < timeout_ms:
            followup_state = self._followup_probe()

            if followup_state is not None:
                self._log(
                    "Jenis Pelanggan transitioned to next workflow state: "
                    f"{followup_state}"
                )
                return True

            # Normal case: old modal simply disappeared.
            if not self._is_visible(self.modal):
                self._log(
                    "Jenis Pelanggan modal disappeared; continue action accepted."
                )
                return True

            self.page.wait_for_timeout(_CUSTOMER_TYPE_CONTINUE_POLL_MS)
            elapsed += _CUSTOMER_TYPE_CONTINUE_POLL_MS

        # One final observation at timeout boundary.
        followup_state = self._followup_probe()

        if followup_state is not None:
            self._log(
                f"Jenis Pelanggan transitioned to next workflow state: {followup_state}"
            )
            return True

        return not self._is_visible(self.modal)
