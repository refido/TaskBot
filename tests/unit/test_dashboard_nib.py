"""Active NIB handler with real polling/control flow and a virtual UI clock.

Only the browser boundary and diagnostic output are doubled. Production retry
constants, detection, outcome polling, and Tutup confirmation remain untouched.
"""

from types import SimpleNamespace

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.infrastructure.browser.page_objects import dashboard_page as module


@pytest.fixture
def nib_case(monkeypatch):
    case = SimpleNamespace(
        state="continue", elapsed=0, scheduled=[], clicks=[], waits=[], sleeps=[],
        events=[], close_locators=[], on_continue=None, on_close=None,
        click_error=None, close_error=None,
    )

    def advance(milliseconds):
        case.elapsed += milliseconds
        while case.scheduled and case.scheduled[0][0] <= case.elapsed:
            _, case.state = case.scheduled.pop(0)

    def sleep(milliseconds):
        case.sleeps.append(milliseconds)
        advance(milliseconds)

    class Locator:
        def __init__(self, kind):
            self.kind = kind

        def is_visible(self, **_kwargs):
            if self.kind == "modal":
                return case.state != "gone"
            return case.state == self.kind

        def wait_for(self, *, state, timeout):
            case.waits.append((self.kind, state, timeout))
            wanted = state == "visible"
            if self.is_visible() != wanted:
                advance(timeout)
            if self.is_visible() != wanted:
                raise PlaywrightTimeoutError(f"{self.kind} did not become {state}")

        def locator(self, selector):
            assert self.kind == "modal" and selector == "button"
            fresh = Locator("close")
            case.close_locators.append(fresh)
            return fresh

        def filter(self, **kwargs):
            if "has_text" in kwargs:
                assert kwargs["has_text"].search("Tutup")
            else:
                assert kwargs == {"visible": True}
            return self

        @property
        def first(self):
            return self

        def to_be_visible(self, **_kwargs):
            assert self.is_visible()

        def to_be_enabled(self, **_kwargs):
            assert self.is_visible()

    def click(locator, **kwargs):
        case.clicks.append((locator.kind, kwargs))
        case.events.append(("click", locator.kind))
        callback = case.on_continue if locator.kind == "continue" else case.on_close
        if callback:
            callback()
        if locator.kind == "continue" and case.click_error:
            raise case.click_error
        if locator.kind == "close" and case.close_error:
            raise case.close_error

    dashboard = module.Dashboard.__new__(module.Dashboard)
    dashboard.page = SimpleNamespace(wait_for_timeout=sleep)
    dashboard.perbarui_data_nib_pelanggan_modal = Locator("modal")
    dashboard.perbarui_data_nib_pelanggan_lanjut_nanti = Locator("continue")
    dashboard.perbarui_data_nib_pelanggan_tutup = Locator("close")
    dashboard.click_locator = click
    dashboard._debug_interaction_checkpoint = lambda label, **_kw: case.events.append(("checkpoint", label))
    dashboard._debug_pause = lambda label: case.events.append(("pause", label))
    dashboard._debug_poll_interaction_states = lambda label: case.events.append(("poll", label))
    monkeypatch.setattr(module, "expect", lambda locator: locator)
    monkeypatch.setattr(module, "log_print", lambda *_args, **_kwargs: None)
    case.dashboard = dashboard
    return case


def test_nib_not_present_does_not_click(nib_case):
    case = nib_case
    case.state = "gone"
    assert case.dashboard.attempt_continue_perbarui_data_nib_pelanggan() == "not_present"
    assert case.clicks == []
    assert case.waits == [("modal", "visible", 6000)]


def test_nib_live_path_instruments_detection_click_and_twenty_second_observation(nib_case):
    """Migrated from the legacy primitive: assert the active success contract."""
    case = nib_case
    case.on_continue = lambda: setattr(case, "state", "gone")
    assert case.dashboard.attempt_continue_perbarui_data_nib_pelanggan() == "continued"
    assert case.state == "gone"
    assert case.sleeps == []
    assert case.clicks == [("continue", {
        "action_name": "continuing transaction past 'Segera Lengkapi NIB' modal",
        "timeout_ms": 10000, "load_state": None,
    })]
    assert case.events == [
        ("checkpoint", "nib_modal_detected"),
        ("pause", "nib_modal_detected"),
        ("checkpoint", "nib_continue_later_before_click"),
        ("click", "continue"),
        ("checkpoint", "nib_continue_later_after_click"),
        ("poll", "nib_continue_later_post_click_20s"),
    ]


@pytest.mark.parametrize("error_type", [PlaywrightError, PlaywrightTimeoutError, AssertionError])
def test_nib_live_path_captures_after_state_even_when_click_raises(nib_case, error_type):
    """Migrated coverage: recoverable click errors still observe the outcome."""
    case = nib_case
    case.click_error = error_type("click response failed")
    case.on_continue = lambda: case.scheduled.append((case.elapsed + 750, "gone"))
    assert case.dashboard.attempt_continue_perbarui_data_nib_pelanggan() == "continued"
    assert len(case.clicks) == 1
    assert case.sleeps == [250, 250, 250]
    assert case.events[-2:] == [
        ("checkpoint", "nib_continue_later_after_click"),
        ("poll", "nib_continue_later_post_click_20s"),
    ]


def test_nib_unexpected_click_error_propagates_after_diagnostics(nib_case):
    case = nib_case
    error = RuntimeError("unexpected failure")
    case.click_error = error
    with pytest.raises(RuntimeError) as caught:
        case.dashboard.attempt_continue_perbarui_data_nib_pelanggan()
    assert caught.value is error
    assert case.events[-2:] == [
        ("checkpoint", "nib_continue_later_after_click"),
        ("poll", "nib_continue_later_post_click_20s"),
    ]


def test_nib_delayed_success_uses_real_poll_loop(nib_case):
    case = nib_case
    case.on_continue = lambda: case.scheduled.append((case.elapsed + 1000, "gone"))
    assert case.dashboard.attempt_continue_perbarui_data_nib_pelanggan() == "continued"
    assert case.sleeps == [250] * 4
    assert len(case.clicks) == 1


@pytest.mark.parametrize("when", ["initial", "immediate", "delayed"])
def test_nib_tutup_outcome_is_confirmed(nib_case, when):
    case = nib_case
    if when == "initial":
        case.state = "close"
    elif when == "immediate":
        case.on_continue = lambda: setattr(case, "state", "close")
    else:
        case.on_continue = lambda: case.scheduled.append((case.elapsed + 750, "close"))
    case.on_close = lambda: setattr(case, "state", "gone")
    assert case.dashboard.attempt_continue_perbarui_data_nib_pelanggan() == "close"
    assert case.state == "gone"
    assert [kind for kind, _ in case.clicks] == (["close"] if when == "initial" else ["continue", "close"])
    assert case.clicks[-1][1] == {
        "action_name": "closing 'Segera Lengkapi NIB' blocker",
        "expected_text": "Tutup", "timeout_ms": 10000, "load_state": None,
    }
    assert ("modal", "hidden", 7000) in case.waits


@pytest.mark.parametrize("success_on_second", [False, True])
def test_nib_continue_is_bounded_to_two_attempts(nib_case, success_on_second):
    case = nib_case
    def continued():
        if success_on_second and len(case.clicks) == 2:
            case.state = "gone"
    case.on_continue = continued
    expected = "continued" if success_on_second else "cannot_continue"
    assert case.dashboard.attempt_continue_perbarui_data_nib_pelanggan() == expected
    assert [kind for kind, _ in case.clicks] == ["continue", "continue"]
    expected_sleeps = [250] * 80 + [500]
    if not success_on_second:
        expected_sleeps += [250] * 80
    assert case.sleeps == expected_sleeps


@pytest.mark.parametrize("succeed", [False, True])
def test_initial_tutup_is_bounded_to_three_attempts(nib_case, succeed):
    case = nib_case
    case.state = "close"
    def closed():
        if succeed and len(case.clicks) == 3:
            case.state = "gone"
    case.on_close = closed
    assert case.dashboard.attempt_continue_perbarui_data_nib_pelanggan() == (
        "close" if succeed else "cannot_continue"
    )
    assert [kind for kind, _ in case.clicks] == ["close"] * 3
    assert len({id(locator) for locator in case.close_locators}) == 3
    assert case.sleeps == [500, 500]


def test_post_click_tutup_total_attempt_bound(nib_case):
    case = nib_case
    case.on_continue = lambda: setattr(case, "state", "close")
    assert case.dashboard.attempt_continue_perbarui_data_nib_pelanggan() == "cannot_continue"
    assert sum(kind == "close" for kind, _ in case.clicks) <= 3
    assert [kind for kind, _ in case.clicks] == ["continue"] + ["close"] * 3


@pytest.mark.parametrize("delayed", [False, True])
def test_tutup_after_second_continue_shares_budget_with_final_check(nib_case, delayed):
    case = nib_case

    def continued():
        if len(case.clicks) == 2:
            if delayed:
                case.scheduled.append((case.elapsed + 750, "close"))
            else:
                case.state = "close"

    case.on_continue = continued
    assert case.dashboard.attempt_continue_perbarui_data_nib_pelanggan() == "cannot_continue"
    assert [kind for kind, _ in case.clicks] == ["continue"] * 2 + ["close"] * 3


def test_tutup_while_continue_button_is_rendering_uses_invocation_budget(nib_case):
    case = nib_case
    case.state = "rendering"
    case.scheduled.append((750, "close"))
    assert case.dashboard.attempt_continue_perbarui_data_nib_pelanggan() == "cannot_continue"
    assert [kind for kind, _ in case.clicks] == ["close"] * 3


@pytest.mark.parametrize("succeed", [False, True])
def test_reentered_tutup_helper_uses_only_remaining_attempts(nib_case, succeed):
    case = nib_case
    case.on_continue = lambda: setattr(case, "state", "close")

    def closed():
        close_count = sum(kind == "close" for kind, _ in case.clicks)
        if close_count == 1:
            # The first helper returns while the button has changed. Later,
            # another Continue exposes Tutup again within the same invocation.
            case.state = "continue"
        elif close_count == 3 and succeed:
            case.state = "gone"

    case.on_close = closed
    assert case.dashboard.attempt_continue_perbarui_data_nib_pelanggan() == (
        "close" if succeed else "cannot_continue"
    )
    assert [kind for kind, _ in case.clicks] == [
        "continue", "close", "continue", "close", "close",
    ]


@pytest.mark.parametrize("error_type", [PlaywrightError, PlaywrightTimeoutError, AssertionError])
@pytest.mark.parametrize("succeed", [False, True])
def test_recoverable_tutup_click_error_consumes_attempt_and_observes_ui(
    nib_case, error_type, succeed,
):
    case = nib_case
    case.on_continue = lambda: setattr(case, "state", "close")
    case.close_error = error_type("Tutup click response failed")
    if succeed:
        case.on_close = lambda: setattr(case, "state", "gone")

    assert case.dashboard.attempt_continue_perbarui_data_nib_pelanggan() == (
        "close" if succeed else "cannot_continue"
    )
    expected_attempts = 1 if succeed else 3
    assert [kind for kind, _ in case.clicks] == ["continue"] + ["close"] * expected_attempts
    assert case.events.count(("checkpoint", "nib_tutup_after_click")) == expected_attempts
    assert case.waits.count(("modal", "hidden", 7000)) == expected_attempts


def test_unexpected_tutup_click_error_propagates_after_diagnostics(nib_case):
    case = nib_case
    case.on_continue = lambda: setattr(case, "state", "close")
    error = RuntimeError("unexpected Tutup failure")
    case.close_error = error

    with pytest.raises(RuntimeError) as caught:
        case.dashboard.attempt_continue_perbarui_data_nib_pelanggan()

    assert caught.value is error
    assert [kind for kind, _ in case.clicks] == ["continue", "close"]
    assert case.events[-1] == ("checkpoint", "nib_tutup_after_click")
    assert ("modal", "hidden", 7000) not in case.waits


def test_tutup_budget_is_fresh_for_each_invocation_on_same_dashboard(nib_case):
    case = nib_case
    for _ in range(2):
        case.state = "close"
        previous_clicks = len(case.clicks)
        assert case.dashboard.attempt_continue_perbarui_data_nib_pelanggan() == "cannot_continue"
        assert [kind for kind, _ in case.clicks[previous_clicks:]] == ["close"] * 3
