from __future__ import annotations

import pytest

from nik_parser import parse_nik
from src.application.models.customer_workflow import (
    CustomerState,
    CustomerUpdateFailedError,
    CustomerUpdateLoopError,
    PrecheckAction,
    UnexpectedCustomerStateError,
)
from src.application.services.transaction_prechecks import TransactionPrechecksService
from src.web.session_state import SessionExpiredError


class Component:
    def __init__(self) -> None:
        self.calls = 0
        self.customers = []
        self.visible_now = False
        self.on_action = None

    def is_visible(self) -> bool:
        if callable(self.visible_now):
            return self.visible_now()
        return self.visible_now

    def _acted(self) -> None:
        self.calls += 1
        if self.on_action is not None:
            self.on_action()

    def continue_(self) -> None:
        self._acted()

    def open_update_form(self) -> None:
        self._acted()

    def fill_and_submit(self, customer) -> None:
        self.customers.append(customer)
        self._acted()

    def confirm_once(self) -> None:
        self._acted()

    def return_home(self) -> None:
        self._acted()


class Reporter:
    def __init__(self) -> None:
        self.events = []
        self.skips = []

    def record_workflow_event(self, nik: str, **payload) -> None:
        self.events.append((nik, payload))

    def skip(self, nik: str, started_at: str, skip_type: str, **payload) -> None:
        self.skips.append((nik, started_at, skip_type, payload))


class Dashboard:
    def __init__(self) -> None:
        self.home_calls = 0
        self.entry = "unknown"
        self.modal = None
        self.customer_type_calls = 0
        self.on_customer_type = None
        self.nib_reminder_calls = 0
        self.on_nib_reminder = None
        self.registration_request_limit_reason = (
            "Terlalu banyak melakukan permintaan pendaftaran untuk NIK pelanggan "
            "ini. Silakan coba lagi di hari berikutnya."
        )
        self.registration_request_limit_close_calls = 0
        self.reset_calls = []

    def ensure_on_dashboard(self) -> None:
        self.home_calls += 1

    def get_visible_customer_entry(self):
        return self.entry

    def get_visible_precheck_modal(self):
        return self.modal

    def select_jenis_pelanggan(self) -> None:
        self.customer_type_calls += 1
        if self.on_customer_type is not None:
            self.on_customer_type()

    def continue_perbarui_data_nib_pelanggan(self) -> None:
        self.nib_reminder_calls += 1
        if self.on_nib_reminder is not None:
            self.on_nib_reminder()

    def read_registration_request_limited_reason_if_present(
        self, detect_timeout=6000
    ):
        if self.modal != "registration_request_limited":
            return None
        return self.registration_request_limit_reason

    def dismiss_registration_request_limited_modal(self) -> None:
        self.registration_request_limit_close_calls += 1
        self.modal = None

    def reset_nik_input_or_return_to_dashboard(self, **kwargs) -> None:
        self.reset_calls.append(kwargs)


class Page:
    def __init__(self) -> None:
        self.url = "https://app.test/customer"
        self.timeouts = []

    def wait_for_timeout(self, timeout_ms: int) -> None:
        self.timeouts.append(timeout_ms)


class Limiter:
    def __init__(self) -> None:
        self.update_actions: list[str] = []
        self.skip_calls = 0

    def wait_before_update_action(self, _page, action: str) -> None:
        self.update_actions.append(action)

    def record_skip(self) -> None:
        self.skip_calls += 1


def build_service(states):
    components = [Component() for _ in range(5)]
    page = Page()
    service = TransactionPrechecksService(
        page=page,
        dashboard=Dashboard(),
        reporter=Reporter(),
        limiter=Limiter(),
        post_skip_cooldown_ms=0,
        max_kuota_timeout_ms=0,
        zero_stock_timeout_ms=0,
        log_func=lambda *args, **kwargs: None,
        consent_page=components[0],
        customer_update_page=components[1],
        update_required_modal=components[2],
        update_confirmation_modal=components[3],
        update_success_modal=components[4],
    )
    state_iterator = iter(states)
    service.resolve_customer_state = lambda **_kwargs: next(
        state_iterator, CustomerState.UNKNOWN
    )
    return service, components


def build_live_service(*, login_page_detector=lambda *_args, **_kwargs: False):
    components = [Component() for _ in range(5)]
    page = Page()
    dashboard = Dashboard()
    service = TransactionPrechecksService(
        page=page,
        dashboard=dashboard,
        reporter=Reporter(),
        limiter=Limiter(),
        post_skip_cooldown_ms=0,
        max_kuota_timeout_ms=0,
        zero_stock_timeout_ms=0,
        log_func=lambda *args, **kwargs: None,
        consent_page=components[0],
        customer_update_page=components[1],
        update_required_modal=components[2],
        update_confirmation_modal=components[3],
        update_success_modal=components[4],
        login_page_detector=login_page_detector,
    )
    service.CUSTOMER_STATE_WAIT_TIMEOUT_MS = 20
    service.CUSTOMER_STATE_POLL_INTERVAL_MS = 10
    return service, components


def test_direct_transaction_continues_without_optional_actions():
    service, components = build_service([CustomerState.TRANSACTION_READY])
    assert (
        service.handle_pre_checks("3573051108720003", "start")
        is PrecheckAction.CONTINUE
    )
    assert all(component.calls == 0 for component in components)
    assert service.limiter.update_actions == []
    assert service.limiter.skip_calls == 0


def test_customer_type_and_consent_are_resolved_before_transaction():
    service, components = build_service(
        [
            CustomerState.CUSTOMER_TYPE,
            CustomerState.CONSENT,
            CustomerState.TRANSACTION_READY,
        ]
    )
    assert (
        service.handle_pre_checks("3573051108720003", "start")
        is PrecheckAction.CONTINUE
    )
    assert components[0].calls == 1
    assert [event[1]["event"] for event in service.reporter.events] == [
        "customer_type_detected",
        "customer_type_selected",
        "consent_detected",
        "consent_continued",
    ]


@pytest.mark.parametrize(
    ("states", "expected_action", "expected_consent_calls", "expected_update_calls"),
    [
        ([CustomerState.TRANSACTION_READY], PrecheckAction.CONTINUE, 0, 0),
        (
            [CustomerState.CUSTOMER_TYPE, CustomerState.TRANSACTION_READY],
            PrecheckAction.CONTINUE,
            0,
            0,
        ),
        (
            [CustomerState.CONSENT, CustomerState.TRANSACTION_READY],
            PrecheckAction.CONTINUE,
            1,
            0,
        ),
        (
            [
                CustomerState.CUSTOMER_TYPE,
                CustomerState.CONSENT,
                CustomerState.TRANSACTION_READY,
            ],
            PrecheckAction.CONTINUE,
            1,
            0,
        ),
        (
            [
                CustomerState.CUSTOMER_TYPE,
                CustomerState.CONSENT,
                CustomerState.UPDATE_REQUIRED,
                CustomerState.UPDATE_FORM,
                CustomerState.UPDATE_CONFIRMATION,
                CustomerState.UPDATE_SUCCESS,
            ],
            PrecheckAction.RESTART_AFTER_UPDATE,
            1,
            4,
        ),
        (
            [
                CustomerState.CONSENT,
                CustomerState.UPDATE_REQUIRED,
                CustomerState.UPDATE_FORM,
                CustomerState.UPDATE_CONFIRMATION,
                CustomerState.UPDATE_SUCCESS,
            ],
            PrecheckAction.RESTART_AFTER_UPDATE,
            1,
            4,
        ),
    ],
)
def test_requested_happy_customer_path_matrix(
    states, expected_action, expected_consent_calls, expected_update_calls
):
    service, components = build_service(states)

    action = service.handle_pre_checks("3573051108720003", "start")

    assert action is expected_action
    assert components[0].calls == expected_consent_calls
    assert sum(component.calls for component in components[1:]) == (
        expected_update_calls
    )


def test_update_uses_parsed_region_and_birth_date_then_restarts_same_nik():
    service, components = build_service(
        [
            CustomerState.UPDATE_REQUIRED,
            CustomerState.UPDATE_FORM,
            CustomerState.UPDATE_CONFIRMATION,
            CustomerState.UPDATE_SUCCESS,
        ]
    )
    action = service.handle_pre_checks("3573051108720003", "start")
    customer = components[1].customers[0]
    parsed = parse_nik("3573051108720003")
    assert action is PrecheckAction.RESTART_AFTER_UPDATE
    assert customer.nik == parsed.original_nik
    assert customer.city == parsed.kota_kabupaten
    assert (customer.birth_day, customer.birth_month, customer.birth_year) == (
        11,
        8,
        1972,
    )
    assert [component.calls for component in components[1:]] == [1, 1, 1, 1]
    assert service.dashboard.home_calls == 1
    assert service.limiter.update_actions == [
        "open_update_form",
        "submit_update_form",
        "confirm_update",
    ]
    assert service.limiter.skip_calls == 0


def test_update_form_is_not_rate_limited_until_nik_parsing_succeeds():
    service, components = build_service([CustomerState.UPDATE_FORM])

    def fail_parse(_nik: str):
        raise ValueError("invalid NIK")

    service.parse_nik = fail_parse

    with pytest.raises(
        CustomerUpdateFailedError,
        match="Customer update data could not be prepared",
    ):
        service.handle_pre_checks("3573051108720003", "start")

    assert components[1].calls == 0
    assert service.limiter.update_actions == []
    assert service.limiter.skip_calls == 0


def test_second_update_request_is_a_bounded_failure_without_second_mutation():
    service, components = build_service([CustomerState.UPDATE_REQUIRED])
    with pytest.raises(CustomerUpdateLoopError):
        service.handle_pre_checks(
            "3573051108720003", "start", allow_customer_update=False
        )
    assert components[2].calls == 0
    assert service.limiter.update_actions == []
    assert service.limiter.skip_calls == 0
    assert service.reporter.events[-1][1]["event"] == "customer_update_required_again"


def test_repeated_consent_state_never_clicks_the_mutation_twice():
    service, components = build_service([])
    service.CUSTOMER_STATE_WAIT_TIMEOUT_MS = 20
    service.CUSTOMER_STATE_POLL_INTERVAL_MS = 10
    service.resolve_customer_state = lambda **_kwargs: CustomerState.CONSENT
    with pytest.raises(UnexpectedCustomerStateError):
        service.handle_pre_checks("3573051108720003", "start")
    assert components[0].calls == 1


def test_update_required_beats_stale_visible_consent():
    service, components = build_live_service()
    service.dashboard.modal = "nib_reminder"
    components[0].visible_now = True
    components[2].visible_now = True

    assert service.resolve_customer_state() is CustomerState.UPDATE_REQUIRED
    assert service.dashboard.nib_reminder_calls == 0


def test_nib_reminder_is_distinct_from_automatic_customer_update():
    service, components = build_live_service()
    service.dashboard.modal = "nib_reminder"

    assert service.resolve_customer_state() is CustomerState.NIB_REMINDER
    assert components[2].calls == 0


def test_nib_reminder_continues_once_then_resolves_transaction():
    service, components = build_live_service()
    service.dashboard.modal = "nib_reminder"

    def continue_to_transaction() -> None:
        service.dashboard.modal = None
        service.dashboard.entry = "transaction_ready"

    service.dashboard.on_nib_reminder = continue_to_transaction

    action = service.handle_pre_checks("3573051108720003", "start")

    assert action is PrecheckAction.CONTINUE
    assert service.dashboard.nib_reminder_calls == 1
    assert components[2].calls == 0
    assert [event[1]["event"] for event in service.reporter.events] == [
        "customer_nib_reminder_detected",
        "customer_nib_reminder_continued",
    ]


def test_blocker_beats_stale_optional_workflow_state():
    service, components = build_live_service()
    service.dashboard.modal = "invalid_registered_nik"
    components[4].visible_now = True

    assert service.resolve_customer_state() is CustomerState.INVALID_REGISTERED_NIK


def test_registration_request_limit_beats_stale_update_states():
    service, components = build_live_service()
    service.dashboard.modal = "registration_request_limited"
    for component in components[1:]:
        component.visible_now = True

    assert (
        service.resolve_customer_state()
        is CustomerState.REGISTRATION_REQUEST_LIMITED
    )


@pytest.mark.parametrize(
    ("states", "expected_update_calls", "expected_update_rate_actions"),
    [
        ([CustomerState.REGISTRATION_REQUEST_LIMITED], [0, 0, 0, 0], []),
        (
            [
                CustomerState.UPDATE_REQUIRED,
                CustomerState.REGISTRATION_REQUEST_LIMITED,
            ],
            [0, 1, 0, 0],
            ["open_update_form"],
        ),
        (
            [
                CustomerState.UPDATE_FORM,
                CustomerState.REGISTRATION_REQUEST_LIMITED,
            ],
            [1, 0, 0, 0],
            ["submit_update_form"],
        ),
        (
            [
                CustomerState.UPDATE_FORM,
                CustomerState.UPDATE_CONFIRMATION,
                CustomerState.REGISTRATION_REQUEST_LIMITED,
            ],
            [1, 0, 1, 0],
            ["submit_update_form", "confirm_update"],
        ),
    ],
)
def test_registration_request_limit_is_terminal_at_each_update_boundary(
    states, expected_update_calls, expected_update_rate_actions
):
    service, components = build_service(states)
    reason = service.dashboard.registration_request_limit_reason
    service.dashboard.modal = "registration_request_limited"

    action = service.handle_pre_checks("3573051108720003", "start")

    assert action is PrecheckAction.SKIP
    assert [component.calls for component in components[1:]] == expected_update_calls
    assert service.limiter.update_actions == expected_update_rate_actions
    assert service.limiter.skip_calls == 1
    assert service.dashboard.registration_request_limit_close_calls == 1
    assert service.reporter.skips == [
        (
            "3573051108720003",
            "start",
            "registration_request_limited",
            {"url": service.page.url, "reason": reason},
        )
    ]


def test_update_click_race_resolves_registration_limit_instead_of_update_error():
    service, components = build_service([CustomerState.UPDATE_FORM])

    def reveal_limit_then_fail() -> None:
        components[1].calls += 1
        service.dashboard.modal = "registration_request_limited"
        raise RuntimeError("Tutup overlay intercepted submit")

    components[1]._acted = reveal_limit_then_fail

    action = service.handle_pre_checks("3573051108720003", "start")

    assert action is PrecheckAction.SKIP
    assert components[1].calls == 1
    assert components[3].calls == 0
    assert service.dashboard.registration_request_limit_close_calls == 1
    assert service.limiter.skip_calls == 1


def test_registration_limit_after_update_success_prevents_same_nik_restart():
    service, components = build_service(
        [
            CustomerState.UPDATE_FORM,
            CustomerState.UPDATE_CONFIRMATION,
            CustomerState.UPDATE_SUCCESS,
        ]
    )
    components[4].on_action = lambda: setattr(
        service.dashboard, "modal", "registration_request_limited"
    )

    action = service.handle_pre_checks("3573051108720003", "start")

    assert action is PrecheckAction.SKIP
    assert [component.calls for component in components[1:]] == [1, 0, 1, 1]
    assert service.dashboard.home_calls == 0
    assert service.dashboard.registration_request_limit_close_calls == 1
    assert service.limiter.skip_calls == 1


def test_session_expiry_beats_all_visible_customer_states():
    service, components = build_live_service(
        login_page_detector=lambda *_args, **_kwargs: True
    )
    service.dashboard.modal = "invalid_registered_nik"
    components[4].visible_now = True

    assert service.resolve_customer_state() is CustomerState.SESSION_EXPIRED
    with pytest.raises(SessionExpiredError):
        service.handle_pre_checks("3573051108720003", "start")
    assert all(component.calls == 0 for component in components)


def test_stale_consent_does_not_mask_transaction_after_single_click():
    service, components = build_live_service()
    components[0].visible_now = True
    components[0].on_action = lambda: setattr(
        service.dashboard, "entry", "transaction_ready"
    )

    action = service.handle_pre_checks("3573051108720003", "start")

    assert action is PrecheckAction.CONTINUE
    assert components[0].calls == 1


def test_consent_can_transition_to_inline_transaction_blocker_without_unknown_state():
    service, components = build_live_service()
    components[0].visible_now = True
    components[0].on_action = lambda: setattr(
        service.dashboard, "entry", "transaction_blocked"
    )

    action = service.handle_pre_checks("3573051108720003", "start")

    assert action is PrecheckAction.CONTINUE
    assert components[0].calls == 1


def test_live_customer_type_is_selected_once_then_state_is_resolved_again():
    service, _components = build_live_service()
    service.dashboard.entry = "customer_type"
    service.dashboard.on_customer_type = lambda: setattr(
        service.dashboard, "entry", "transaction_ready"
    )

    action = service.handle_pre_checks("3573051108720003", "start")

    assert action is PrecheckAction.CONTINUE
    assert service.dashboard.customer_type_calls == 1


def test_delayed_optional_state_is_polled_then_resolved():
    service, components = build_live_service()
    visibility = iter([False, True])
    components[0].visible_now = lambda: next(visibility, True)
    components[0].on_action = lambda: setattr(
        service.dashboard, "entry", "transaction_ready"
    )

    action = service.handle_pre_checks("3573051108720003", "start")

    assert action is PrecheckAction.CONTINUE
    assert components[0].calls == 1
    assert service.page.timeouts == [10]


def test_confirmation_without_workflow_submit_is_never_clicked():
    service, components = build_service([CustomerState.UPDATE_CONFIRMATION])

    with pytest.raises(CustomerUpdateFailedError, match="Refusing to confirm"):
        service.handle_pre_checks("3573051108720003", "start")

    assert components[3].calls == 0


def test_submit_transition_timeout_is_terminal_and_never_resubmits():
    service, components = build_service([CustomerState.UPDATE_FORM])
    service.CUSTOMER_STATE_WAIT_TIMEOUT_MS = 20
    service.CUSTOMER_STATE_POLL_INTERVAL_MS = 10

    with pytest.raises(CustomerUpdateFailedError, match="confirmation did not appear"):
        service.handle_pre_checks("3573051108720003", "start")

    assert components[1].calls == 1


def test_confirmation_transition_timeout_is_terminal_and_never_reconfirms():
    service, components = build_service(
        [CustomerState.UPDATE_FORM, CustomerState.UPDATE_CONFIRMATION]
    )
    service.CUSTOMER_STATE_WAIT_TIMEOUT_MS = 20
    service.CUSTOMER_STATE_POLL_INTERVAL_MS = 10

    with pytest.raises(CustomerUpdateFailedError, match="success did not appear"):
        service.handle_pre_checks("3573051108720003", "start")

    assert components[1].calls == 1
    assert components[3].calls == 1


def test_transient_transaction_ready_cannot_bypass_confirmation_or_success():
    service, components = build_service(
        [
            CustomerState.UPDATE_FORM,
            CustomerState.TRANSACTION_READY,
            CustomerState.UPDATE_CONFIRMATION,
            CustomerState.TRANSACTION_READY,
            CustomerState.UPDATE_SUCCESS,
        ]
    )

    action = service.handle_pre_checks("3573051108720003", "start")

    assert action is PrecheckAction.RESTART_AFTER_UPDATE
    assert components[1].calls == 1
    assert components[3].calls == 1
    assert components[4].calls == 1


def test_direct_update_form_on_same_nik_restart_cannot_submit_again():
    service, components = build_service([CustomerState.UPDATE_FORM])

    with pytest.raises(CustomerUpdateLoopError):
        service.handle_pre_checks(
            "3573051108720003", "start", allow_customer_update=False
        )

    assert components[1].calls == 0
    assert service.reporter.events[-1][1]["event"] == ("customer_update_required_again")


@pytest.mark.parametrize(
    "blocker_state",
    [
        CustomerState.UNDER_17,
        CustomerState.NOT_REGISTERED,
        CustomerState.INVALID_REGISTERED_NIK,
        CustomerState.CANNOT_TRANSACT_AT_BASE,
        CustomerState.UNUSUAL_TRANSACTION,
    ],
)
def test_disappeared_terminal_blocker_is_resolved_again_instead_of_silent_skip(
    blocker_state,
):
    service, _components = build_service(
        [blocker_state, CustomerState.TRANSACTION_READY]
    )
    service._handle_under_17 = lambda *_args: False
    service._handle_precheck_modal = lambda *_args: False

    action = service.handle_pre_checks("3573051108720003", "start")

    assert action is PrecheckAction.CONTINUE
