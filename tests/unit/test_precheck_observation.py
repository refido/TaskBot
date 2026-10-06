"""Resolution priority and probe ordering, before/after observation extraction."""

from itertools import combinations
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from playwright.sync_api import Error, TimeoutError

from src.application.models.customer_workflow import (
    CustomerState,
    UnexpectedCustomerStateError,
)
from src.application.services.transaction_prechecks import TransactionPrechecksService
from src.web.session_state import SessionExpiredError

MODALS = (
    "not_registered",
    "registration_request_limited",
    "invalid_registered_nik",
    "cannot_transact_at_base",
    "unusual_transaction",
    "nik_mismatch",
    "nib_reminder",
    "perbarui",
)
COMPONENTS = (
    "update_success",
    "update_confirmation",
    "update_form",
    "update_required",
    "consent",
)
PRIORITY = (
    "session_expired",
    "under_17",
    *MODALS[:6],
    *COMPONENTS,
    "nib_reminder",
    "customer_type",
    "transaction_ready",
)


def make_case(**extra):
    case = SimpleNamespace(
        facts=set(),
        trace=[],
        errors={},
        elapsed=0,
        appear_at=None,
        next_facts=set(),
        legacy=False,
    )

    def probe(name):
        case.trace.append(name)
        if name in case.errors:
            raise case.errors[name]

    class Page:
        def wait_for_timeout(self, ms):
            case.trace.append(("sleep", ms))
            case.elapsed += ms
            if case.appear_at is not None and case.elapsed >= case.appear_at:
                case.facts = case.next_facts.copy()

    class Dashboard:
        def get_visible_customer_entry(self):
            probe("entry")
            if "under_17" in case.facts:
                return "under_17"
            if any(name in case.facts for name in MODALS):
                return "precheck_modal"
            for name in (
                "customer_type",
                "customer_type_selected",
                "transaction_blocked",
                "transaction_ready",
            ):
                if name in case.facts:
                    return name
            return "unknown"

        def get_visible_precheck_modal(self):
            probe("modal")
            return next((name for name in MODALS if name in case.facts), None)

    class Component:
        def __init__(self, name):
            self.name = name

        def is_visible(self):
            probe(self.name)
            return self.name in case.facts

    def login(page, *, timeout_ms):
        assert page is case.service.page
        case.trace.append(("login_timeout", timeout_ms))
        probe("login")
        return "session_expired" in case.facts

    components = {name: Component(name) for name in COMPONENTS}
    case.service = TransactionPrechecksService(
        page=Page(),
        dashboard=Dashboard(),
        reporter=Mock(),
        limiter=Mock(),
        post_skip_cooldown_ms=0,
        max_kuota_timeout_ms=0,
        zero_stock_timeout_ms=0,
        consent_page=components["consent"],
        customer_update_page=components["update_form"],
        update_required_modal=components["update_required"],
        update_confirmation_modal=components["update_confirmation"],
        update_success_modal=components["update_success"],
        login_page_detector=login,
        log_func=Mock(),
        **extra,
    )
    return case


@pytest.fixture
def case():
    case = make_case()
    yield case
    # Observation must not record business telemetry or mutate limiter state.
    assert case.service.reporter.mock_calls == []
    assert case.service.limiter.mock_calls == []
    assert case.service.log_func.mock_calls == []


@pytest.mark.parametrize("state", list(CustomerState))
def test_single_state_resolution(case, state):
    case.facts = {state.value}
    assert case.service.resolve_customer_state() is state
    assert case.service._customer_type_action_pending == (
        state is CustomerState.CUSTOMER_TYPE
    )
    assert case.elapsed == 0


@pytest.mark.parametrize("higher,lower", list(combinations(PRIORITY, 2)))
def test_synthetic_coexistence_preserves_priority(case, higher, lower):
    case.facts = {higher, lower}
    assert case.service.resolve_customer_state() is CustomerState(higher)


@pytest.mark.parametrize(
    "entry,expected,pending",
    [
        ("perbarui", CustomerState.UPDATE_REQUIRED, False),
        ("customer_type_selected", CustomerState.CUSTOMER_TYPE, False),
        ("customer_type", CustomerState.CUSTOMER_TYPE, True),
        ("transaction_blocked", CustomerState.TRANSACTION_READY, False),
    ],
)
def test_compatibility_evidence_and_pending_flag(case, entry, expected, pending):
    case.facts = {entry}
    assert case.service.resolve_customer_state() is expected
    assert case.service._customer_type_action_pending is pending
    case.facts = set()
    assert case.service.resolve_customer_state() is CustomerState.UNKNOWN
    assert case.service._customer_type_action_pending is False


@pytest.mark.parametrize("state", [*COMPONENTS, "nib_reminder", "customer_type"])
def test_after_state_suppression_is_policy_not_observation(case, state):
    case.facts = {state}
    assert (
        case.service.resolve_customer_state(after_state=CustomerState(state))
        is CustomerState.UNKNOWN
    )
    if state in COMPONENTS:
        assert state not in case.trace  # Skipped probes must stay skipped.


def test_short_circuit_call_order(case):
    case.facts = {"update_form", "consent", "nib_reminder"}
    assert case.service.resolve_customer_state() is CustomerState.UPDATE_FORM
    assert case.trace == [
        ("login_timeout", 100),
        "login",
        "entry",
        "modal",
        "update_success",
        "update_confirmation",
        "update_form",
    ]


@pytest.mark.parametrize("stage", ["entry", "modal", "update_success"])
@pytest.mark.parametrize(
    "error_type", [TimeoutError, AssertionError, SessionExpiredError, Error, ValueError]
)
def test_probe_exceptions_preserve_identity(case, stage, error_type):
    error = error_type("probe failed")
    case.errors[stage] = error
    with pytest.raises(error_type) as caught:
        case.service.resolve_customer_state()
    assert caught.value is error


@pytest.mark.parametrize("error_type", [AttributeError, TypeError])
def test_component_compatibility_errors_are_ignored(case, error_type):
    case.errors["update_success"] = error_type("unsupported double")
    case.facts = {"consent"}
    assert case.service.resolve_customer_state() is CustomerState.CONSENT


def test_modal_probe_still_precedes_under17_decision(case):
    case.facts = {"under_17"}
    case.errors["modal"] = ValueError("modal probe failed")
    with pytest.raises(ValueError, match="modal probe failed"):
        case.service.resolve_customer_state()


@pytest.mark.parametrize("arrival", [0, 100, 300, None])
def test_polling_initial_final_and_timeout_observations(case, arrival):
    service = case.service
    service.CUSTOMER_STATE_WAIT_TIMEOUT_MS = 300
    case.appear_at = arrival
    case.next_facts = {"transaction_ready"}
    if arrival == 0:
        case.facts = case.next_facts.copy()
    if arrival is None:
        with pytest.raises(UnexpectedCustomerStateError, match="within 300ms"):
            service._wait_for_customer_state()
    else:
        assert service._wait_for_customer_state() is CustomerState.TRANSACTION_READY
    expected_elapsed = 300 if arrival is None else arrival
    assert case.elapsed == expected_elapsed
    assert case.trace.count("entry") == expected_elapsed // 100 + 1


def test_wait_filters_known_but_disallowed_states(case):
    case.facts = {"consent"}
    case.appear_at, case.next_facts = 200, {"update_form"}
    assert (
        case.service._wait_for_customer_state(
            allowed_states={CustomerState.UPDATE_FORM}
        )
        is CustomerState.UPDATE_FORM
    )
    assert case.elapsed == 200


def test_default_wait_bounds(case):
    with pytest.raises(UnexpectedCustomerStateError, match="within 10000ms"):
        case.service._wait_for_customer_state()
    assert case.elapsed == 10000
    assert case.trace.count("entry") == 101


def test_legacy_dashboard_and_login_signatures(case):
    calls = []

    def entry():
        calls.append("legacy_entry")
        return "transaction_ready"

    case.service.dashboard = SimpleNamespace(resolve_customer_entry=entry)
    case.service.login_page_detector = lambda page: (
        calls.append("legacy_login") or False
    )
    assert case.service.resolve_customer_state() is CustomerState.TRANSACTION_READY
    assert calls == ["legacy_login", "legacy_entry"]


def test_invalid_modal_vocabulary_is_not_silently_normalized(case):
    case.service.dashboard.get_visible_precheck_modal = lambda: "unrecognized"
    with pytest.raises(ValueError):
        case.service.resolve_customer_state()


@pytest.mark.parametrize("stage", ["entry", "modal", "login", "component"])
@pytest.mark.parametrize(
    "error_type",
    [
        AttributeError,
        TypeError,
        TimeoutError,
        AssertionError,
        SessionExpiredError,
        Error,
        ValueError,
    ],
)
def test_browser_observer_exception_contract(stage, error_type):
    from src.infrastructure.browser.precheck_observer import BrowserPrecheckObserver

    observer = BrowserPrecheckObserver()
    error = error_type("probe failure")
    probe = Mock(side_effect=error)
    obj = SimpleNamespace(
        get_visible_customer_entry=probe,
        get_visible_precheck_modal=probe,
        is_visible=probe,
    )
    invoke = {
        "entry": lambda: observer.customer_entry(obj, timeout_ms=100),
        "modal": lambda: observer.precheck_modal(obj),
        "login": lambda: observer.login_visible(obj, probe, timeout_ms=100),
        "component": lambda: observer.component_visible(obj),
    }[stage]
    swallowed = (stage in {"modal", "login"} and error_type is AttributeError) or (
        stage == "component" and error_type in {AttributeError, TypeError}
    )
    if swallowed:
        assert invoke() is (None if stage == "modal" else False)
    else:
        with pytest.raises(error_type) as caught:
            invoke()
        assert caught.value is error
    assert probe.call_count == (
        2 if stage == "login" and error_type is TypeError else 1
    )


def test_browser_observer_legacy_fallback_and_current_dependencies():
    from src.infrastructure.browser.precheck_observer import BrowserPrecheckObserver

    observer = BrowserPrecheckObserver()
    calls = []

    def legacy_entry():
        calls.append("entry")
        return "customer_type_selected"

    assert (
        observer.customer_entry(
            SimpleNamespace(resolve_customer_entry=legacy_entry), timeout_ms=7
        )
        == "customer_type_selected"
    )
    snapshot = Mock(return_value="transaction_ready")
    assert (
        observer.customer_entry(
            SimpleNamespace(get_visible_customer_entry=snapshot), timeout_ms=9
        )
        == "transaction_ready"
    )
    snapshot.assert_called_once_with()
    assert observer.login_visible(object(), lambda page: True, timeout_ms=11)
    assert observer.precheck_modal(object()) is None
    assert observer.component_visible(object()) is False
    assert calls == ["entry"]
    assert vars(observer) == {}  # No retained page, cache or workflow state.


@pytest.mark.parametrize(
    "state",
    [
        CustomerState.SESSION_EXPIRED,
        CustomerState.UNDER_17,
        CustomerState.UPDATE_FORM,
        CustomerState.TRANSACTION_READY,
    ],
)
def test_explicit_observer_injection_does_not_invoke_ui(state, monkeypatch):
    import src.application.services.transaction_prechecks as prechecks
    from src.infrastructure.browser.precheck_observer import BrowserPrecheckObserver

    observer = Mock(spec=BrowserPrecheckObserver)
    observer.login_visible.return_value = state is CustomerState.SESSION_EXPIRED
    observer.customer_entry.return_value = (
        "under_17" if state is CustomerState.UNDER_17 else "transaction_ready"
    )
    observer.precheck_modal.return_value = None
    observer.component_visible.side_effect = lambda component: (
        state is CustomerState.UPDATE_FORM and component.name == "update_form"
    )
    constructor = Mock(
        side_effect=AssertionError("default observer must not be created")
    )
    monkeypatch.setattr(prechecks, "BrowserPrecheckObserver", constructor)
    case = make_case(observer=observer)
    assert case.service.resolve_customer_state() is state
    assert case.trace == []
    assert case.service.observer is observer
    constructor.assert_not_called()


def test_default_action_construction_is_preserved(monkeypatch):
    import src.application.services.transaction_prechecks as prechecks
    from src.infrastructure.browser.precheck_observer import BrowserPrecheckObserver

    factories = {}
    for name in (
        "ConsentPage",
        "CustomerUpdatePage",
        "UpdateRequiredModal",
        "UpdateConfirmationModal",
        "UpdateSuccessModal",
    ):
        factories[name] = Mock(return_value=SimpleNamespace(is_visible=lambda: False))
        monkeypatch.setattr(prechecks, name, factories[name])
    page = object()
    service = TransactionPrechecksService(
        page=page,
        dashboard=object(),
        reporter=object(),
        limiter=object(),
        post_skip_cooldown_ms=0,
        max_kuota_timeout_ms=0,
        zero_stock_timeout_ms=0,
    )
    assert isinstance(service.observer, BrowserPrecheckObserver)
    for factory in factories.values():
        factory.assert_called_once_with(page)


def test_component_truthiness_errors_keep_existing_boundary():
    from src.infrastructure.browser.precheck_observer import BrowserPrecheckObserver

    class Unsupported:
        def __bool__(self):
            raise TypeError("unsupported truthiness")

    assert (
        BrowserPrecheckObserver().component_visible(
            SimpleNamespace(is_visible=lambda: Unsupported())
        )
        is False
    )
