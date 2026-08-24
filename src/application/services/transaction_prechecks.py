from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from nik_parser import parse_nik
from src.application.models.customer_workflow import (
    CustomerState,
    CustomerUpdateFailedError,
    CustomerUpdateLoopError,
    PrecheckAction,
    UnexpectedCustomerStateError,
    customer_update_data_from_nik,
)
from src.infrastructure.browser.page_objects.consent_page import ConsentPage
from src.infrastructure.browser.page_objects.customer_update_page import (
    CustomerUpdatePage,
)
from src.infrastructure.browser.page_objects.update_confirmation_modal import (
    UpdateConfirmationModal,
)
from src.infrastructure.browser.page_objects.update_required_modal import (
    UpdateRequiredModal,
)
from src.infrastructure.browser.page_objects.update_success_modal import (
    UpdateSuccessModal,
)
from src.logging_utils import log_print
from src.web.session_state import SessionExpiredError, is_login_page

if TYPE_CHECKING:
    from src.infrastructure.browser.page_objects.dashboard_page import Dashboard
    from src.infrastructure.browser.page_objects.penjualan_page import Penjualan
    from src.web.rate_limiter import SkipRateLimiter
    from src.web.reporter import TransactionReporter


@dataclass(frozen=True)
class TransactionBlockerOutcome:
    should_skip: bool = False
    stop_reason: str | None = None


class TransactionPrechecksService:
    """Encapsulates skip-or-stop checks before and during a transaction."""

    MAX_CUSTOMER_PRECHECK_TRANSITIONS = 10
    CUSTOMER_STATE_WAIT_TIMEOUT_MS = 10_000
    CUSTOMER_STATE_POLL_INTERVAL_MS = 100
    CUSTOMER_STATE_PROBE_TIMEOUT_MS = 100
    _INTERRUPT_STATES = frozenset(
        {
            CustomerState.SESSION_EXPIRED,
            CustomerState.UNDER_17,
            CustomerState.NOT_REGISTERED,
            CustomerState.REGISTRATION_REQUEST_LIMITED,
            CustomerState.INVALID_REGISTERED_NIK,
            CustomerState.CANNOT_TRANSACT_AT_BASE,
            CustomerState.UNUSUAL_TRANSACTION,
        }
    )
    _AFTER_UPDATE_REQUIRED_STATES = _INTERRUPT_STATES | {CustomerState.UPDATE_FORM}
    _AFTER_UPDATE_FORM_STATES = _INTERRUPT_STATES | {CustomerState.UPDATE_CONFIRMATION}
    _AFTER_UPDATE_CONFIRMATION_STATES = _INTERRUPT_STATES | {
        CustomerState.UPDATE_SUCCESS
    }

    def __init__(
        self,
        *,
        page,
        dashboard: Dashboard,
        reporter: TransactionReporter,
        limiter: SkipRateLimiter,
        post_skip_cooldown_ms: int,
        max_kuota_timeout_ms: int,
        zero_stock_timeout_ms: int,
        log_func: Callable[..., None] = log_print,
        consent_page=None,
        customer_update_page=None,
        update_required_modal=None,
        update_confirmation_modal=None,
        update_success_modal=None,
        parse_nik_func: Callable = parse_nik,
        login_page_detector: Callable[..., bool] = is_login_page,
    ) -> None:
        self.page = page
        self.dashboard = dashboard
        self.reporter = reporter
        self.limiter = limiter
        self.post_skip_cooldown_ms = post_skip_cooldown_ms
        self.max_kuota_timeout_ms = max_kuota_timeout_ms
        self.zero_stock_timeout_ms = zero_stock_timeout_ms
        self.log_func = log_func
        self.consent_page = consent_page or ConsentPage(page)
        self.customer_update_page = customer_update_page or CustomerUpdatePage(page)
        self.update_required_modal = update_required_modal or UpdateRequiredModal(page)
        self.update_confirmation_modal = (
            update_confirmation_modal or UpdateConfirmationModal(page)
        )
        self.update_success_modal = update_success_modal or UpdateSuccessModal(page)
        self.parse_nik = parse_nik_func
        self.login_page_detector = login_page_detector

    def handle_pre_checks(
        self,
        nik: str,
        started_at: str,
        *,
        allow_customer_update: bool = True,
    ) -> PrecheckAction:
        """Resolve and process optional customer states until a terminal action."""
        update_form_submitted = False
        update_confirmed = False
        handled_states: set[CustomerState] = set()
        self.log_func(
            "Customer precheck started",
            event="customer.precheck.started",
            nik=nik,
            url=self.page.url,
        )
        state = self._wait_for_customer_state()

        for transition in range(1, self.MAX_CUSTOMER_PRECHECK_TRANSITIONS + 1):
            self.log_func(
                "Resolved customer precheck state:",
                state.value,
                event="customer.precheck.state",
                transition=transition,
                nik=nik,
                state=state.value,
                url=self.page.url,
            )

            if state is CustomerState.SESSION_EXPIRED:
                raise SessionExpiredError(
                    "Session expired while resolving customer prechecks"
                )
            if state is CustomerState.TRANSACTION_READY:
                return PrecheckAction.CONTINUE
            if state is CustomerState.CUSTOMER_TYPE:
                self._raise_if_repeated(state, handled_states)
                self._record_workflow_event(nik, "customer_type_detected")
                self._log_customer_action(nik, state, "select_customer_type")
                if getattr(
                    self, "_customer_type_action_pending", False
                ) and self._run_customer_step(
                    self.dashboard.select_jenis_pelanggan,
                    nik=nik,
                    started_at=started_at,
                ):
                    return PrecheckAction.SKIP
                self._record_workflow_event(nik, "customer_type_selected")
                handled_states.add(state)
                state = self._resolve_after_action(nik, state)
                continue
            if state is CustomerState.NIB_REMINDER:
                self._raise_if_repeated(state, handled_states)
                self._record_workflow_event(nik, "customer_nib_reminder_detected")
                self._log_customer_action(nik, state, "continue_nib_reminder")
                if self._run_customer_step(
                    self.dashboard.continue_perbarui_data_nib_pelanggan,
                    nik=nik,
                    started_at=started_at,
                ):
                    return PrecheckAction.SKIP
                self._record_workflow_event(nik, "customer_nib_reminder_continued")
                handled_states.add(state)
                state = self._resolve_after_action(nik, state)
                continue
            if state is CustomerState.CONSENT:
                self._raise_if_repeated(state, handled_states)
                self._record_workflow_event(nik, "consent_detected")
                self._log_customer_action(nik, state, "continue_consent")
                if self._run_customer_step(
                    self.consent_page.continue_,
                    nik=nik,
                    started_at=started_at,
                ):
                    return PrecheckAction.SKIP
                self._record_workflow_event(nik, "consent_continued")
                handled_states.add(state)
                state = self._resolve_after_action(nik, state)
                continue
            if state is CustomerState.UPDATE_REQUIRED:
                self._raise_if_repeated(state, handled_states)
                self._record_workflow_event(nik, "customer_update_required")
                self._raise_if_update_disallowed(nik, allow_customer_update)
                self._log_customer_action(nik, state, "open_update_form")
                self._wait_before_update_action("open_update_form")
                if self._run_update_step(
                    self.update_required_modal.open_update_form,
                    "Customer update form could not be opened",
                    nik=nik,
                    started_at=started_at,
                ):
                    return PrecheckAction.SKIP
                self._record_workflow_event(nik, "customer_update_form_opened")
                handled_states.add(state)
                state = self._resolve_after_action(
                    nik,
                    state,
                    allowed_states=self._AFTER_UPDATE_REQUIRED_STATES,
                    update_failure_message=(
                        "Customer update form did not become the current visible state"
                    ),
                )
                continue
            if state is CustomerState.UPDATE_FORM:
                self._raise_if_repeated(state, handled_states)
                self._raise_if_update_disallowed(nik, allow_customer_update)
                self._log_customer_action(nik, state, "submit_update_form")
                try:
                    customer = customer_update_data_from_nik(self.parse_nik(nik))
                except Exception as exc:
                    raise CustomerUpdateFailedError(
                        "Customer update data could not be prepared from the current NIK"
                    ) from exc
                self._wait_before_update_action("submit_update_form")
                if self._run_update_step(
                    partial(self.customer_update_page.fill_and_submit, customer),
                    "Customer update form could not be submitted",
                    nik=nik,
                    started_at=started_at,
                ):
                    return PrecheckAction.SKIP
                update_form_submitted = True
                self._record_workflow_event(nik, "customer_update_submitted")
                handled_states.add(state)
                state = self._resolve_after_action(
                    nik,
                    state,
                    allowed_states=self._AFTER_UPDATE_FORM_STATES,
                    update_failure_message=(
                        "Customer update confirmation did not appear after submission"
                    ),
                )
                continue
            if state is CustomerState.UPDATE_CONFIRMATION:
                self._raise_if_repeated(state, handled_states)
                self._record_workflow_event(
                    nik, "customer_update_confirmation_detected"
                )
                if not update_form_submitted:
                    raise CustomerUpdateFailedError(
                        "Refusing to confirm an update not submitted by this workflow"
                    )
                self._log_customer_action(nik, state, "confirm_update")
                self._wait_before_update_action("confirm_update")
                if self._run_update_step(
                    self.update_confirmation_modal.confirm_once,
                    "Customer update confirmation failed",
                    nik=nik,
                    started_at=started_at,
                ):
                    return PrecheckAction.SKIP
                update_confirmed = True
                self._record_workflow_event(nik, "customer_update_confirmed")
                handled_states.add(state)
                state = self._resolve_after_action(
                    nik,
                    state,
                    allowed_states=self._AFTER_UPDATE_CONFIRMATION_STATES,
                    update_failure_message=(
                        "Customer update success did not appear after confirmation"
                    ),
                )
                continue
            if state is CustomerState.UPDATE_SUCCESS:
                if not update_confirmed:
                    raise CustomerUpdateFailedError(
                        "Customer update success appeared before workflow confirmation"
                    )
                self._record_workflow_event(nik, "customer_update_success")
                self._log_customer_action(nik, state, "return_home")
                if self._run_update_step(
                    self.update_success_modal.return_home,
                    "Dashboard could not be restored after customer update",
                    nik=nik,
                    started_at=started_at,
                ):
                    return PrecheckAction.SKIP
                if self._handle_registration_request_limit_if_present(nik, started_at):
                    return PrecheckAction.SKIP
                if self._run_update_step(
                    self.dashboard.ensure_on_dashboard,
                    "Dashboard could not be restored after customer update",
                    nik=nik,
                    started_at=started_at,
                ):
                    return PrecheckAction.SKIP
                if self._handle_registration_request_limit_if_present(nik, started_at):
                    return PrecheckAction.SKIP
                self._log_customer_transition(
                    nik,
                    previous_state=state.value,
                    new_state="dashboard_ready",
                )
                return PrecheckAction.RESTART_AFTER_UPDATE
            if state is CustomerState.UNDER_17:
                if self._handle_under_17(nik, started_at):
                    return PrecheckAction.SKIP
                state = self._resolve_after_action(nik, state)
                continue
            if state is CustomerState.REGISTRATION_REQUEST_LIMITED:
                if self._handle_registration_request_limited(nik, started_at):
                    return PrecheckAction.SKIP
                state = self._resolve_after_action(nik, state)
                continue
            if state in {
                CustomerState.NOT_REGISTERED,
                CustomerState.INVALID_REGISTERED_NIK,
                CustomerState.CANNOT_TRANSACT_AT_BASE,
                CustomerState.UNUSUAL_TRANSACTION,
            }:
                if self._handle_precheck_modal(state.value, nik, started_at):
                    return PrecheckAction.SKIP
                state = self._resolve_after_action(nik, state)
                continue
            raise UnexpectedCustomerStateError(
                f"Unable to resolve customer state after NIK submission: {state.value}"
            )

        raise UnexpectedCustomerStateError(
            "Customer precheck exceeded the maximum of "
            f"{self.MAX_CUSTOMER_PRECHECK_TRANSITIONS} transitions"
        )

    def resolve_customer_state(
        self, *, after_state: CustomerState | None = None
    ) -> CustomerState:
        """Return the highest-priority current visible state without waiting."""
        self._customer_type_action_pending = False

        if self._is_login_page_visible():
            return CustomerState.SESSION_EXPIRED

        entry_outcome = self._get_visible_customer_entry()
        modal_name = self._get_visible_precheck_modal()

        # Existing terminal blockers always beat stale customer workflow pages.
        if entry_outcome == "under_17":
            return CustomerState.UNDER_17
        if modal_name and modal_name not in {"nib_reminder", "perbarui"}:
            return CustomerState(modal_name)

        for state, component in (
            (CustomerState.UPDATE_SUCCESS, self.update_success_modal),
            (CustomerState.UPDATE_CONFIRMATION, self.update_confirmation_modal),
            (CustomerState.UPDATE_FORM, self.customer_update_page),
            (CustomerState.UPDATE_REQUIRED, self.update_required_modal),
            (CustomerState.CONSENT, self.consent_page),
        ):
            if state is after_state:
                continue
            try:
                if component.is_visible():
                    return state
            except AttributeError, TypeError:
                # Lightweight test doubles may not expose Playwright locators.
                pass

        if (
            modal_name == "nib_reminder"
            and after_state is not CustomerState.NIB_REMINDER
        ):
            return CustomerState.NIB_REMINDER

        if (
            modal_name == "perbarui"
            and after_state is not CustomerState.UPDATE_REQUIRED
        ):
            return CustomerState.UPDATE_REQUIRED

        if (
            entry_outcome == "customer_type"
            and after_state is not CustomerState.CUSTOMER_TYPE
        ):
            self._customer_type_action_pending = True
            return CustomerState.CUSTOMER_TYPE
        if (
            entry_outcome == "customer_type_selected"
            and after_state is not CustomerState.CUSTOMER_TYPE
        ):
            return CustomerState.CUSTOMER_TYPE
        if entry_outcome in {"transaction_ready", "transaction_blocked"}:
            return CustomerState.TRANSACTION_READY
        return CustomerState.UNKNOWN

    def _wait_for_customer_state(
        self,
        *,
        after_state: CustomerState | None = None,
        allowed_states: frozenset[CustomerState] | set[CustomerState] | None = None,
    ) -> CustomerState:
        """Wait a bounded time for any known state other than the prior state."""
        poll_ms = max(1, self.CUSTOMER_STATE_POLL_INTERVAL_MS)
        attempts = max(1, self.CUSTOMER_STATE_WAIT_TIMEOUT_MS // poll_ms)

        for attempt in range(attempts + 1):
            state = self.resolve_customer_state(after_state=after_state)
            known_next_state = (
                state is not CustomerState.UNKNOWN and state is not after_state
            )
            if known_next_state and (allowed_states is None or state in allowed_states):
                return state
            if attempt < attempts:
                self.page.wait_for_timeout(poll_ms)

        prior = after_state.value if after_state is not None else "NIK submission"
        raise UnexpectedCustomerStateError(
            "No known customer state became visible after "
            f"{prior} within {self.CUSTOMER_STATE_WAIT_TIMEOUT_MS}ms"
        )

    def _resolve_after_action(
        self,
        nik: str,
        previous_state: CustomerState,
        *,
        allowed_states: frozenset[CustomerState] | set[CustomerState] | None = None,
        update_failure_message: str | None = None,
    ) -> CustomerState:
        try:
            state = self._wait_for_customer_state(
                after_state=previous_state,
                allowed_states=allowed_states,
            )
        except UnexpectedCustomerStateError as exc:
            if update_failure_message is not None:
                raise CustomerUpdateFailedError(update_failure_message) from exc
            raise
        self._log_customer_transition(
            nik,
            previous_state=previous_state.value,
            new_state=state.value,
        )
        return state

    def _get_visible_customer_entry(self):
        snapshot = getattr(self.dashboard, "get_visible_customer_entry", None)
        if snapshot is not None:
            return snapshot()

        # Compatibility for lightweight page-object test doubles.
        resolver = self.dashboard.resolve_customer_entry
        try:
            return resolver(detect_timeout=self.CUSTOMER_STATE_PROBE_TIMEOUT_MS)
        except TypeError:
            return resolver()

    def _get_visible_precheck_modal(self):
        try:
            return self.dashboard.get_visible_precheck_modal()
        except AttributeError:
            return None

    def _is_login_page_visible(self) -> bool:
        try:
            return bool(
                self.login_page_detector(
                    self.page,
                    timeout_ms=self.CUSTOMER_STATE_PROBE_TIMEOUT_MS,
                )
            )
        except TypeError:
            return bool(self.login_page_detector(self.page))
        except AttributeError:
            return False

    def _log_customer_action(self, nik: str, state: CustomerState, action: str) -> None:
        self.log_func(
            "Customer precheck action:",
            action,
            event="customer.precheck.action",
            nik=nik,
            state=state.value,
            action=action,
            url=self.page.url,
        )

    def _log_customer_transition(
        self, nik: str, *, previous_state: str, new_state: str
    ) -> None:
        self.log_func(
            "Customer precheck transition:",
            previous_state,
            "->",
            new_state,
            event="customer.precheck.transition",
            nik=nik,
            previous_state=previous_state,
            state=new_state,
            url=self.page.url,
        )

    def _record_workflow_event(self, nik: str, event: str, *, reason: str = "") -> None:
        callback = getattr(self.reporter, "record_workflow_event", None)
        if callback is not None:
            callback(
                nik,
                event=event,
                stage="precheck",
                url=self.page.url,
                reason=reason,
            )

    def _run_update_step(
        self,
        action: Callable[[], None],
        message: str,
        *,
        nik: str,
        started_at: str,
    ) -> bool:
        try:
            action()
        except SessionExpiredError:
            raise
        except Exception as exc:
            if self._handle_registration_request_limit_if_present(nik, started_at):
                return True
            if self._is_login_page_visible():
                raise SessionExpiredError(
                    "Session expired during the customer-update workflow"
                ) from exc
            raise CustomerUpdateFailedError(message) from exc
        return False

    def _wait_before_update_action(self, action: str) -> None:
        """Pace update work when the injected limiter supports it."""
        wait = getattr(self.limiter, "wait_before_update_action", None)
        if callable(wait):
            wait(self.page, action)

    def _run_customer_step(
        self,
        action: Callable[[], None],
        *,
        nik: str,
        started_at: str,
    ) -> bool:
        try:
            action()
        except SessionExpiredError:
            raise
        except Exception as exc:
            if self._handle_registration_request_limit_if_present(nik, started_at):
                return True
            if self._is_login_page_visible():
                raise SessionExpiredError(
                    "Session expired during customer precheck action"
                ) from exc
            raise
        return False

    def _handle_registration_request_limit_if_present(
        self, nik: str, started_at: str
    ) -> bool:
        if self._get_visible_precheck_modal() != "registration_request_limited":
            return False
        return self._handle_registration_request_limited(nik, started_at)

    def _raise_if_update_disallowed(
        self, nik: str, allow_customer_update: bool
    ) -> None:
        if allow_customer_update:
            return
        self._record_workflow_event(nik, "customer_update_required_again")
        raise CustomerUpdateLoopError(
            "Customer data was updated successfully but the same NIK "
            "requested another update"
        )

    @staticmethod
    def _raise_if_repeated(
        state: CustomerState, handled_states: set[CustomerState]
    ) -> None:
        if state in handled_states:
            raise UnexpectedCustomerStateError(
                f"Customer state repeated after its action completed: {state.value}"
            )

    def _handle_customer_type_follow_up(self, nik: str, started_at: str) -> bool:
        follow_up_outcome = self.dashboard.wait_for_transaction_form_or_precheck_modal()
        if follow_up_outcome == "transaction_ready":
            return False
        if follow_up_outcome != "precheck_modal":
            return False

        modal_name = self.dashboard.get_visible_precheck_modal()
        if modal_name is None:
            return False
        return self._handle_precheck_modal(modal_name, nik, started_at)

    def _handle_precheck_modal(
        self, modal_name: str, nik: str, started_at: str
    ) -> bool:
        if modal_name == "not_registered":
            return self._handle_not_registered(nik, started_at)
        if modal_name == "invalid_registered_nik":
            return self._handle_invalid_registered_nik(nik, started_at)
        if modal_name == "cannot_transact_at_base":
            return self._handle_cannot_transact_at_base(nik, started_at)
        if modal_name == "unusual_transaction":
            return self._handle_unusual_transaction(nik, started_at)
        return False

    def _handle_under_17(self, nik: str, started_at: str) -> bool:
        under_17_reason = self.dashboard.read_under_17_validation_if_present(
            detect_timeout=500
        )
        if not under_17_reason:
            return False

        self.dashboard.reset_nik_input_or_return_to_dashboard(
            reset_action_name="clearing NIK input after under-17 validation",
            reset_log="Cleared NIK input after under-17 validation message.",
            dashboard_log="Under-17 validation handled; returned to dashboard.",
        )
        self._record_skip_and_cooldown(
            nik=nik,
            started_at=started_at,
            skip_callback=lambda: self.reporter.skip_under_17(
                nik,
                started_at,
                url=self.page.url,
            ),
            message=f"Skipping NIK {nik} ({under_17_reason}).",
        )
        return True

    def _handle_not_registered(self, nik: str, started_at: str) -> bool:
        not_registered_reason = (
            self.dashboard.read_pelanggan_tidak_terdaftar_reason_if_present(
                detect_timeout=500
            )
        )
        if not not_registered_reason:
            return False

        self.dashboard.dismiss_pelanggan_tidak_terdaftar_modal()
        self.dashboard.reset_nik_input_or_return_to_dashboard(
            reset_action_name="resetting NIK input after pelanggan modal",
            reset_log="Closed 'Pelanggan Tidak Terdaftar'; NIK input reset.",
            dashboard_log="Closed 'Pelanggan Tidak Terdaftar'; returned to dashboard.",
        )
        self._record_skip_and_cooldown(
            nik=nik,
            started_at=started_at,
            skip_callback=lambda: self.reporter.skip_not_registered(
                nik,
                started_at,
                url=self.page.url,
                reason=not_registered_reason,
            ),
            message=f"Skipping NIK {nik} ({not_registered_reason}).",
        )
        return True

    def _handle_registration_request_limited(self, nik: str, started_at: str) -> bool:
        reason = self.dashboard.read_registration_request_limited_reason_if_present(
            detect_timeout=500
        )
        if not reason:
            return False

        self._record_workflow_event(
            nik,
            "customer_registration_request_limited",
            reason=reason,
        )
        self.dashboard.dismiss_registration_request_limited_modal()
        self._record_workflow_event(
            nik,
            "customer_registration_request_limit_closed",
            reason=reason,
        )
        self.dashboard.reset_nik_input_or_return_to_dashboard(
            reset_action_name=(
                "resetting NIK input after customer registration request limit"
            ),
            reset_log=(
                "Closed customer registration request-limit modal; NIK input reset."
            ),
            dashboard_log=(
                "Closed customer registration request-limit modal; returned to dashboard."
            ),
        )
        self._record_skip_and_cooldown(
            nik=nik,
            started_at=started_at,
            skip_callback=lambda: self.reporter.skip(
                nik,
                started_at,
                "registration_request_limited",
                url=self.page.url,
                reason=reason,
            ),
            message=(
                f"Skipping NIK {nik} because its customer registration request "
                f"limit was reached ({reason})."
            ),
        )
        return True

    def _handle_perbarui_data_pelanggan(self, nik: str, started_at: str) -> bool:
        perbarui_action = self.dashboard.attempt_continue_perbarui_data_pelanggan()
        if perbarui_action == "continued":
            return False

        self.dashboard.dismiss_perbarui_data_pelanggan_modal()
        self.dashboard.reset_nik_input_or_return_to_dashboard(
            reset_action_name="resetting NIK input after Perbarui Data Pelanggan modal",
            reset_log="Closed 'Perbarui Data Pelanggan'; NIK input reset.",
            dashboard_log="Closed 'Perbarui Data Pelanggan'; returned to dashboard.",
        )
        needs_update_reason = (
            "Perbarui Data Pelanggan cannot continue transaction; modal closed."
            if perbarui_action == "cannot_continue"
            else "Perbarui Data Pelanggan closed; transaction skipped."
        )
        self._record_skip_and_cooldown(
            nik=nik,
            started_at=started_at,
            skip_callback=lambda: self.reporter.skip_needs_update(
                nik,
                started_at,
                url=self.page.url,
                reason=needs_update_reason,
            ),
            message=f"Skipping NIK {nik} ({needs_update_reason})",
        )
        return True

    def _handle_invalid_registered_nik(self, nik: str, started_at: str) -> bool:
        invalid_registered_nik_reason = (
            self.dashboard.read_invalid_registered_nik_reason_if_present(
                detect_timeout=500
            )
        )
        if not invalid_registered_nik_reason:
            return False

        self.dashboard.dismiss_invalid_registered_nik_modal()
        self.dashboard.reset_nik_input_or_return_to_dashboard(
            reset_action_name="resetting NIK input after warning modal",
            reset_log="Closed invalid registered-customer NIK modal; NIK input reset.",
            dashboard_log="Closed invalid registered-customer NIK modal; returned to dashboard.",
        )
        self._record_skip_and_cooldown(
            nik=nik,
            started_at=started_at,
            skip_callback=lambda: self.reporter.skip_invalid_registered_nik(
                nik,
                started_at,
                url=self.page.url,
            ),
            message=f"Skipping NIK {nik} ({invalid_registered_nik_reason}).",
        )
        return True

    def _handle_cannot_transact_at_base(self, nik: str, started_at: str) -> bool:
        cannot_transact_at_base_reason = (
            self.dashboard.read_cannot_transact_at_base_reason_if_present(
                detect_timeout=500
            )
        )
        if not cannot_transact_at_base_reason:
            return False

        self.dashboard.dismiss_cannot_transact_at_base_modal()
        self.dashboard.reset_nik_input_or_return_to_dashboard(
            reset_action_name="resetting NIK input after warning modal",
            reset_log="Closed base-restriction modal; NIK input reset.",
            dashboard_log="Closed base-restriction modal; returned to dashboard.",
        )
        self._record_skip_and_cooldown(
            nik=nik,
            started_at=started_at,
            skip_callback=lambda: self.reporter.skip_cannot_transact_at_base(
                nik,
                started_at,
                url=self.page.url,
            ),
            message=f"Skipping NIK {nik} ({cannot_transact_at_base_reason}).",
        )
        return True

    def _handle_unusual_transaction(self, nik: str, started_at: str) -> bool:
        unusual_transaction_reason = (
            self.dashboard.read_unusual_transaction_reason_if_present(
                detect_timeout=500
            )
        )
        if not unusual_transaction_reason:
            return False

        self.dashboard.dismiss_unusual_transaction_modal()
        self.dashboard.reset_nik_input_or_return_to_dashboard(
            reset_action_name="resetting NIK input after warning modal",
            reset_log="Closed unusual-transaction modal; NIK input reset.",
            dashboard_log="Closed unusual-transaction modal; returned to dashboard.",
        )
        self._record_skip_and_cooldown(
            nik=nik,
            started_at=started_at,
            skip_callback=lambda: self.reporter.skip_unusual_transaction_at_other_base(
                nik,
                started_at,
                url=self.page.url,
            ),
            message=f"Skipping NIK {nik} ({unusual_transaction_reason}).",
        )
        return True

    def check_transaction_blocker(
        self,
        penjualan: Penjualan,
        nik: str,
        started_at: str,
        stage: str,
        *,
        timeout_ms: int | None = None,
        nama_pengguna: str = "",
        jenis_pengguna: str = "",
    ) -> TransactionBlockerOutcome:
        """Return the handling outcome for a visible transaction blocker alert."""
        alert = penjualan.read_transaction_blocker_alert(
            timeout=(
                timeout_ms
                if timeout_ms is not None
                else max(self.max_kuota_timeout_ms, self.zero_stock_timeout_ms)
            )
        )
        if alert is None:
            return TransactionBlockerOutcome()

        alert_kind, alert_text = alert
        self.log_func(
            "Transaction blocker detected:",
            alert_kind,
            alert_text,
            event="transaction.blocker.detected",
            nik=nik,
            blocker_kind=alert_kind,
            stage=stage,
            alert_text=alert_text,
            url=self.page.url,
        )
        if alert_kind == "zero_stock":
            stop_reason = self._record_zero_stock_skip(
                nik=nik,
                started_at=started_at,
                stage=stage,
                alert_text=alert_text,
                nama_pengguna=nama_pengguna,
                jenis_pengguna=jenis_pengguna,
            )
            return TransactionBlockerOutcome(stop_reason=stop_reason)

        self._record_max_kuota_skip(
            penjualan=penjualan,
            nik=nik,
            started_at=started_at,
            stage=stage,
            alert_text=alert_text,
            nama_pengguna=nama_pengguna,
            jenis_pengguna=jenis_pengguna,
        )
        return TransactionBlockerOutcome(should_skip=True)

    def check_max_kuota(
        self, penjualan: Penjualan, nik: str, started_at: str, stage: str
    ) -> bool:
        """Return True when the transaction must be skipped for max kuota."""
        if not penjualan.is_max_kuota_alert_present(timeout=self.max_kuota_timeout_ms):
            return False

        self._record_max_kuota_skip(
            penjualan=penjualan, nik=nik, started_at=started_at, stage=stage
        )
        return True

    def check_zero_stock(
        self, penjualan: Penjualan, nik: str, started_at: str, stage: str
    ) -> str | None:
        """Return a stop reason after recording the skip when stock is empty."""
        alert_text = penjualan.get_zero_stock_alert_text(
            timeout=self.zero_stock_timeout_ms
        )
        if not alert_text:
            return None

        if not penjualan.is_zero_stock_alert_text(alert_text):
            return None

        return self._record_zero_stock_skip(
            nik=nik,
            started_at=started_at,
            stage=stage,
            alert_text=alert_text,
        )

    def _record_max_kuota_skip(
        self,
        *,
        penjualan: Penjualan,
        nik: str,
        started_at: str,
        stage: str,
        alert_text: str = "",
        nama_pengguna: str = "",
        jenis_pengguna: str = "",
    ) -> None:
        try:
            penjualan.ganti_pelanggan()
        except Exception as exc:  # noqa: BLE001 - customer switching is best effort.
            self.log_func(
                "Failed to switch customer after max-kuota alert:",
                exc,
                level="DEBUG",
            )

        reason = f"Max kuota {stage}"
        if alert_text:
            reason = f"{reason}: {alert_text}"

        self._record_skip_and_cooldown(
            nik=nik,
            started_at=started_at,
            skip_callback=lambda: self.reporter.skip_max_kuota(
                nik,
                started_at,
                url=self.page.url,
                reason=reason,
                nama_pengguna=nama_pengguna,
                jenis_pengguna=jenis_pengguna,
            ),
            message=f"Skipping NIK {nik} ({reason}).",
        )

    def _record_zero_stock_skip(
        self,
        *,
        nik: str,
        started_at: str,
        stage: str,
        alert_text: str,
        nama_pengguna: str = "",
        jenis_pengguna: str = "",
    ) -> str:
        reason = f"Sellable stock empty {stage}: {alert_text}"
        self._record_skip_and_cooldown(
            nik=nik,
            started_at=started_at,
            skip_callback=lambda: self.reporter.skip_out_of_stock(
                nik,
                started_at,
                url=self.page.url,
                reason=reason,
                nama_pengguna=nama_pengguna,
                jenis_pengguna=jenis_pengguna,
            ),
            message=(
                f"Stopping account run for NIK {nik} because sellable stock "
                f"is empty ({stage})."
            ),
        )
        return reason

    def _record_skip_and_cooldown(
        self,
        *,
        nik: str,
        started_at: str,
        skip_callback: Callable[[], None],
        message: str,
    ) -> None:
        self.limiter.record_skip()
        skip_callback()
        self.log_func(message)
        self.page.wait_for_timeout(self.post_skip_cooldown_ms)
