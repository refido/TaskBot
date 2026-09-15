"""Warning UI contracts, exercised through real Dashboard/BasePage operations."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from playwright.sync_api import Error, TimeoutError

from src.infrastructure.browser.page_objects import base_page, dashboard_page
from src.web.session_state import SessionExpiredError

DOMAINS = ("invalid_registered_nik", "unusual_transaction", "cannot_transact_at_base")
FALLBACKS = {
    "invalid_registered_nik": "NIK pelanggan yang didaftarkan tidak valid.",
    "unusual_transaction": "NIK pelanggan terindikasi transaksi tidak wajar di pangkalan lain dengan jarak tidak wajar dan waktu berdekatan.",
    "cannot_transact_at_base": "Pelanggan Tidak Dapat Transaksi di Pangkalan Ini",
}


@pytest.fixture(params=DOMAINS)
def ui(request, monkeypatch):
    kind = request.param
    case = SimpleNamespace(
        kind=kind, visible={k: False for k in DOMAINS}, trace=[], logs=[],
        missing=set(), text={}, errors={}, stays=False, login=False,
        login_after_click=False, resets=[],
    )

    class Locator:
        def __init__(self, domain, part):
            self.domain, self.part = domain, part

        def wait_for(self, *, state, timeout):
            case.trace.append((self.domain, self.part, "wait", state, timeout))
            error = case.errors.get((self.part, "wait"))
            if error:
                raise error
            visible = case.visible[self.domain] and self.part not in case.missing
            if visible != (state == "visible"):
                raise TimeoutError("not " + state)

        def inner_text(self):
            case.trace.append((self.domain, self.part, "text"))
            error = case.errors.get((self.part, "text"))
            if error:
                raise error
            return case.text.get(self.part, "Tutup" if self.part == "button" else "  reason \n")

        def to_be_visible(self, *, timeout):
            self.wait_for(state="visible", timeout=timeout)

        def to_be_enabled(self, *, timeout):
            case.trace.append((self.domain, self.part, "enabled", timeout))

        def click(self, *, timeout):
            case.trace.append((self.domain, self.part, "click", timeout))
            error = case.errors.get((self.part, "click"))
            if error:
                raise error
            if not case.stays:
                case.visible[self.domain] = False
            case.login = case.login_after_click

    dashboard = dashboard_page.Dashboard.__new__(dashboard_page.Dashboard)
    dashboard.page = Mock()
    for domain in DOMAINS:
        for suffix, part in (("", "modal"), ("_title", "title"), ("_tutup", "button")):
            setattr(dashboard, domain + "_modal" + suffix, Locator(domain, part))
        if domain != "cannot_transact_at_base":
            setattr(dashboard, domain + "_modal_message", Locator(domain, "message"))
    dashboard.reset_nik_input_or_return_to_dashboard = Mock(side_effect=lambda **kw: case.resets.append(kw))
    monkeypatch.setattr(base_page, "expect", lambda locator: locator)
    monkeypatch.setattr(base_page, "is_login_page", lambda *a, **kw: case.login)
    monkeypatch.setattr(base_page, "log_print", lambda *a, **kw: case.logs.append(a))
    monkeypatch.setattr(dashboard_page, "log_print", lambda *a, **kw: case.logs.append(a))
    case.dashboard = dashboard
    case.read = getattr(dashboard, "read_" + kind + "_reason_if_present")
    case.dismiss = getattr(dashboard, "dismiss_" + kind + "_modal")
    case.close = getattr(dashboard, "close_" + kind + "_if_needed")
    case.part = "title" if kind == "cannot_transact_at_base" else "message"
    yield case
    # Synthetic simultaneous warnings must never cause access to another domain.
    assert all(event[0] == kind for event in case.trace)
    dashboard.page.assert_not_called()
    assert dashboard.page.method_calls == []  # No navigation, diagnostics or load wait.


def test_absent_returns_none_without_action(ui):
    assert ui.close() is None
    assert ui.trace == [(ui.kind, "modal", "wait", "visible", 6000)]
    assert "not present; continuing." in ui.logs[0][0]
    assert not ui.resets


@pytest.mark.parametrize("text", ["  reason \n", "", " \t\n"])
def test_reason_and_blank_fallback(ui, text):
    ui.visible[ui.kind] = True
    ui.text[ui.part] = text
    assert ui.read(detect_timeout=321) == (text.strip() or FALLBACKS[ui.kind])
    assert ui.trace == [
        (ui.kind, "modal", "wait", "visible", 321),
        (ui.kind, ui.part, "wait", "visible", 1000 if ui.part == "title" else 1500),
        (ui.kind, ui.part, "text"),
    ]
    assert len(ui.logs) == 1


def test_missing_content_uses_fallback_and_diagnostic_log(ui):
    ui.visible[ui.kind] = True
    ui.missing.update({"message", "title"})
    assert ui.read() == FALLBACKS[ui.kind]
    assert "without the expected" in ui.logs[-1][0]


def test_message_timeout_falls_back_to_title(ui):
    ui.visible[ui.kind] = True
    ui.missing.add("message")
    ui.text["title"] = "  title reason  "
    assert ui.read() == "title reason"


def test_dismiss_success_and_hidden_confirmation(ui):
    ui.visible[ui.kind] = True
    assert ui.dismiss() is None
    assert ui.trace == [
        (ui.kind, "button", "wait", "visible", 5000),
        (ui.kind, "button", "text"),
        (ui.kind, "button", "enabled", 5000),
        (ui.kind, "button", "click", 5000),
        (ui.kind, "modal", "wait", "hidden", 7000),
    ]
    assert not ui.visible[ui.kind]
    assert not ui.resets  # Primitive does not own reset policy.


def test_wrapper_read_dismiss_reset_and_repeated_invocation(ui):
    ui.visible.update({k: True for k in DOMAINS})  # Synthetic coexistence only.
    assert ui.close() == "reason"
    assert len(ui.resets) == 1
    assert ui.resets[0]["reset_action_name"] == "resetting NIK input after warning modal"
    assert ui.resets[0]["reset_log"].endswith("NIK input reset.")
    assert ui.resets[0]["dashboard_log"].endswith("returned to dashboard.")
    assert all(ui.visible[k] for k in DOMAINS if k != ui.kind)
    assert ui.close() is None
    assert len(ui.resets) == 1
    assert sum(e[2] == "click" for e in ui.trace) == 1


@pytest.mark.parametrize("failure", ["stays_visible", "button_timeout", "click_timeout", "click_error"])
def test_dismiss_failure_propagates_without_reset(ui, failure):
    ui.visible[ui.kind] = True
    if failure == "stays_visible":
        ui.stays = True
    elif failure == "button_timeout":
        ui.missing.add("button")
    else:
        error = TimeoutError("click") if failure == "click_timeout" else Error("click")
        ui.errors[("button", "click")] = error
    with pytest.raises((Error, TimeoutError)):
        ui.close()
    assert not ui.resets
    assert sum(e[2] == "click" for e in ui.trace) == (failure != "button_timeout")


@pytest.mark.parametrize("stage", ["wait", "text"])
def test_unexpected_read_error_propagates(ui, stage):
    ui.visible[ui.kind] = True
    error = ValueError("unexpected")
    ui.errors[("modal" if stage == "wait" else ui.part, stage)] = error
    with pytest.raises(ValueError) as caught:
        ui.close()
    assert caught.value is error
    assert not ui.resets


@pytest.mark.parametrize("after_click", [False, True])
def test_session_safety_before_and_after_click(ui, after_click):
    ui.visible[ui.kind] = True
    ui.login = not after_click
    ui.login_after_click = after_click
    with pytest.raises(SessionExpiredError, match="closing warning modal"):
        ui.close()
    assert not ui.resets
    assert sum(e[2] == "click" for e in ui.trace) == int(after_click)
    assert not any(e[3:] == ("hidden", 7000) for e in ui.trace)


def test_read_does_not_introduce_session_check(ui):
    ui.visible[ui.kind] = True
    ui.login = True
    assert ui.read() == "reason"


def test_reset_failure_preserves_existing_exception(ui):
    ui.visible[ui.kind] = True
    error = RuntimeError("reset failed")
    ui.dashboard.reset_nik_input_or_return_to_dashboard.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        ui.close()
    assert caught.value is error
    assert not ui.visible[ui.kind]


# The primitive has two read shapes; unusual_transaction repeats the message shape.
@pytest.mark.parametrize("ui", ["invalid_registered_nik", "cannot_transact_at_base"], indirect=True)
@pytest.mark.parametrize("scenario", ["absent", "text", "blank", "missing", "unexpected"])
def test_component_read_without_dashboard_workflow(ui, scenario):
    from src.infrastructure.browser.page_objects.simple_warning_modal import (
        SimpleWarningModal,
    )

    ui.visible[ui.kind] = scenario != "absent"
    if scenario == "blank":
        ui.text[ui.part] = " \n "
    if scenario == "missing":
        ui.missing.update({"title", "message"})
    failure = ValueError("read error")
    if scenario == "unexpected":
        ui.errors[(ui.part, "text")] = failure
    component = SimpleWarningModal(getattr(ui.dashboard, ui.kind + "_modal"))
    kwargs = dict(
        detect_timeout=432, missing_log="absent", log=lambda *a: ui.logs.append(a),
        title_locator=getattr(ui.dashboard, ui.kind + "_modal_title"),
        title_fallback=FALLBACKS[ui.kind],
    )
    if ui.part == "message":
        kwargs.update(
            message_locator=getattr(ui.dashboard, ui.kind + "_modal_message"),
            message_fallback=FALLBACKS[ui.kind],
        )
    if scenario == "unexpected":
        with pytest.raises(ValueError) as caught:
            component.read_reason(**kwargs)
        assert caught.value is failure
    else:
        expected = None if scenario == "absent" else "reason" if scenario == "text" else FALLBACKS[ui.kind]
        assert component.read_reason(**kwargs) == expected
    assert not ui.resets
    assert not any(e[2] == "click" for e in ui.trace)


# Domain-specific locator wiring and reset policy are covered by the wrapper tests.
@pytest.mark.parametrize("ui", ["invalid_registered_nik"], indirect=True)
@pytest.mark.parametrize("scenario", ["success", "visible", "click_error", "session"])
def test_component_dismiss_preserves_session_aware_action(ui, scenario):
    from src.infrastructure.browser.page_objects.simple_warning_modal import (
        SimpleWarningModal,
    )

    ui.visible[ui.kind] = True
    ui.stays = scenario == "visible"
    ui.login = scenario == "session"
    if scenario == "click_error":
        ui.errors[("button", "click")] = Error("click failure")
    component = SimpleWarningModal(getattr(ui.dashboard, ui.kind + "_modal"))

    def dismiss():
        component.dismiss(
            close_button=getattr(ui.dashboard, ui.kind + "_modal_tutup"),
            click_locator=ui.dashboard.click_locator,
        )

    if scenario == "success":
        assert dismiss() is None
        assert not ui.visible[ui.kind]
    else:
        expected = SessionExpiredError if scenario == "session" else Error
        with pytest.raises(expected):
            dismiss()
    assert not ui.resets
    assert sum(e[2] == "click" for e in ui.trace) == (scenario != "session")
