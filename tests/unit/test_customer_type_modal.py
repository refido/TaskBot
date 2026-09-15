"""Customer-type interaction contracts with deterministic UI transitions."""

import re
from types import SimpleNamespace

import pytest
from playwright.sync_api import Error, TimeoutError

from src.infrastructure.browser.page_objects import dashboard_page
from src.web.session_state import SessionExpiredError

HOUSEHOLD = "Rumah Tangga"
MICRO = "Usaha Mikro"


def make_ui(monkeypatch):
    ui = SimpleNamespace(
        visible=True, options=[HOUSEHOLD, MICRO], selected=None, visual_only=False,
        elapsed=0, option_at=0, button_at=0, enabled=True, label_visible=True,
        native_visible=True, button_visible=True, portal_button=False,
        selection_delay=0, continue_delay=0, selection_works=True, continue_works=True,
        next_state="transaction_ready", followup=None, due_selection=None,
        due_continue=None, errors={}, trace=[], logs=[], diagnostics=[], polls=[],
    )

    def advance(milliseconds):
        ui.trace.append(("sleep", milliseconds))
        ui.elapsed += milliseconds
        if ui.due_selection and ui.elapsed >= ui.due_selection[0]:
            ui.selected = ui.due_selection[1]
            ui.due_selection = None
        if ui.due_continue is not None and ui.elapsed >= ui.due_continue:
            if ui.next_state == "disappeared":
                ui.visible = False
            else:
                ui.followup = ui.next_state
            ui.due_continue = None

    class Locator:
        def __init__(self, kind, value=None):
            self.kind, self.value = kind, value

        @property
        def first(self):
            return self

        def count(self):
            if self.kind in {"radio", "label", "selected"}:
                return int(self.value in ui.options and ui.elapsed >= ui.option_at)
            return 1

        def is_visible(self, **_kwargs):
            if self.kind == "modal":
                return ui.visible
            if self.kind in {"radio", "label", "selected"}:
                return bool(self.count() and ui.visible and (
                    ui.native_visible if self.kind == "radio" else
                    ui.label_visible if self.kind == "label" else ui.selected == self.value
                ))
            if self.kind == "button":
                return ui.visible and ui.button_visible and ui.elapsed >= ui.button_at
            if self.kind == "portal_button":
                return ui.visible and ui.portal_button and ui.elapsed >= ui.button_at
            return ui.followup == self.kind

        def is_enabled(self):
            return ui.enabled

        def is_checked(self):
            return ui.selected == self.value and not ui.visual_only

        def get_attribute(self, name):
            assert name == "aria-checked"
            return "true" if ui.selected == self.value else "false"

        def wait_for(self, *, state, timeout):
            ui.trace.append((self.kind, "wait", state, timeout))
            if self.is_visible() != (state == "visible"):
                raise TimeoutError("modal absent")

        def to_be_visible(self, *, timeout):
            ui.trace.append((self.kind, "expect_visible", timeout))
            if not self.is_visible():
                raise AssertionError("not visible")

        def to_be_enabled(self, *, timeout):
            ui.trace.append((self.kind, "expect_enabled", timeout))
            if not self.is_enabled():
                raise AssertionError("disabled")

        def scroll_into_view_if_needed(self, *, timeout):
            ui.trace.append((self.kind, "scroll", timeout))

        def click(self, *, timeout):
            ui.trace.append((self.kind, "click", self.value, timeout))
            if self.kind in {"radio", "label"} and ui.selection_works:
                if ui.selection_delay:
                    ui.due_selection = (ui.elapsed + ui.selection_delay, self.value)
                else:
                    ui.selected = self.value
            elif self.kind in {"button", "portal_button"} and ui.continue_works:
                if ui.continue_delay:
                    ui.due_continue = ui.elapsed + ui.continue_delay
                elif ui.next_state == "disappeared":
                    ui.visible = False
                else:
                    ui.followup = ui.next_state
            error = ui.errors.get(self.kind)
            if error:
                raise error

        def locator(self, selector):
            assert self.kind == "modal"
            ui.trace.append(("locator", selector))
            match = re.search(r'value="([^"]+)"', selector)
            if match:
                return Locator("label" if selector.startswith("label") else "radio", match[1])
            if selector == "button":
                return Collection("button")
            if selector in ("input[type='radio']", "label:has(input[type='radio'])", '[role="radio"]'):
                return Collection("label" if selector.startswith("label") else "radio")
            raise AssertionError(selector)

        def get_by_role(self, role, **kwargs):
            assert self.kind == "modal"
            if role == "radio":
                return Collection("radio")
            assert role == "button" and kwargs["name"].search("LANJUTKAN PENJUALAN")
            return Collection("button")

        def get_by_text(self, text, **kwargs):
            assert self.kind == "label" and text == "Terpilih" and kwargs == {"exact": True}
            return Locator("selected", self.value)

    class Collection:
        def __init__(self, kind):
            self.kind = kind

        @property
        def first(self):
            return self.nth(0)

        def count(self):
            if self.kind in {"button", "portal_button"}:
                return int(Locator(self.kind).is_visible())
            return len(ui.options) if ui.elapsed >= ui.option_at else 0

        def nth(self, index):
            return Locator(self.kind, ui.options[index] if self.kind in {"radio", "label"} else None)

        def filter(self, **kwargs):
            if "has_text" in kwargs:
                assert kwargs["has_text"].search("LANJUTKAN PENJUALAN")
            else:
                assert kwargs == {"visible": True}
            return self

    class Page:
        def wait_for_timeout(self, ms):
            advance(ms)

        def locator(self, selector):
            assert selector == "button"
            ui.trace.append(("portal", "locator", selector))
            return Collection("portal_button")

        def get_by_text(self, pattern):
            if pattern.search("Pernyataan Persetujuan"):
                return Locator("consent")
            assert pattern.search("Data Pelanggan belum lengkap")
            return Locator("update_required")

    dashboard = dashboard_page.Dashboard.__new__(dashboard_page.Dashboard)
    dashboard.page = Page()
    dashboard.jenis_pelanggan_modal = Locator("modal")
    dashboard.is_transaction_form_ready = lambda **kw: ui.followup == "transaction_ready"
    dashboard.get_visible_precheck_modal = lambda: ui.followup if ui.followup in {"nib_reminder", "invalid_registered_nik"} else None
    dashboard._debug_interaction_checkpoint = lambda label, **kw: ui.diagnostics.append((label, kw.get("target_name")))
    dashboard._debug_pause = lambda label: ui.diagnostics.append((label, None))
    dashboard._debug_poll_interaction_states = ui.polls.append
    dashboard._debug_customer_type_continue_collection = lambda: Collection("button")
    monkeypatch.setattr(dashboard_page, "expect", lambda locator: locator)
    monkeypatch.setattr(dashboard_page, "log_print", lambda *a, **kw: ui.logs.append(tuple(str(v) for v in a)))
    ui.dashboard = dashboard
    ui.page = dashboard.page
    ui.modal = dashboard.jenis_pelanggan_modal
    ui.choice = Locator("label", HOUSEHOLD)
    ui.clicks = lambda: [e for e in ui.trace if len(e) > 1 and e[1] == "click"]
    return ui


@pytest.fixture
def ui(monkeypatch):
    return make_ui(monkeypatch)


def test_absent_modal(ui):
    ui.visible = False
    assert ui.dashboard.select_jenis_pelanggan_if_needed() is False
    assert ui.trace == [("modal", "wait", "visible", 5000)]
    assert not ui.clicks()


def test_selection_and_continue_success(ui):
    assert ui.dashboard.select_jenis_pelanggan_if_needed() is True
    assert ui.selected == HOUSEHOLD and ui.followup == "transaction_ready"
    assert [e[0] for e in ui.clicks()] == ["label", "button"]
    assert ("customer_type_radio_confirmed", None) in ui.diagnostics
    assert ui.polls == ["customer_type_continue_post_click_20s"]


@pytest.mark.parametrize("options,expected", [([MICRO], MICRO), (["Other"], "Other"), ([], None)])
def test_option_priority_and_generic_fallback(ui, options, expected):
    ui.options = options
    if expected is None:
        with pytest.raises(RuntimeError, match="no usable"):
            ui.dashboard.select_jenis_pelanggan()
        assert not ui.clicks()
    else:
        ui.dashboard.select_jenis_pelanggan()
        assert ui.selected == expected


def test_missing_options_are_not_polled(ui):
    ui.option_at = 200
    assert ui.dashboard._find_customer_type_choice() is None
    assert ui.elapsed == 0
    ui.dashboard.page.wait_for_timeout(200)
    assert ui.dashboard._find_customer_type_choice()[0] == HOUSEHOLD


def test_delayed_selection_and_continue_button(ui):
    ui.selection_delay = 300
    ui.button_at = 700
    ui.dashboard.select_jenis_pelanggan()
    assert ui.elapsed == 700
    assert ("sleep", 100) in ui.trace and ("sleep", 200) in ui.trace
    assert len(ui.clicks()) == 2


@pytest.mark.parametrize("next_state", ["transaction_ready", "consent", "update_required", "nib_reminder", "invalid_registered_nik", "disappeared"])
def test_continue_observes_transition_without_acting_on_other_domain(ui, next_state):
    ui.next_state = next_state
    ui.continue_delay = 500
    ui.dashboard.select_jenis_pelanggan()
    assert ui.elapsed == 500
    assert [e[0] for e in ui.clicks()] == ["label", "button"]
    assert ui.followup == next_state if next_state != "disappeared" else not ui.visible


@pytest.mark.parametrize("error", [ValueError("unexpected"), SessionExpiredError("session")])
@pytest.mark.parametrize("kind", ["label", "button"])
def test_unexpected_or_session_error_preserves_identity_and_finally_diagnostics(ui, kind, error):
    ui.errors[kind] = error
    with pytest.raises(type(error)) as caught:
        ui.dashboard.select_jenis_pelanggan()
    assert caught.value is error
    suffix = "radio" if kind == "label" else "continue"
    assert any(label == f"customer_type_{suffix}_after_click" for label, _ in ui.diagnostics)


def test_continue_click_timeout_retry_bound(ui):
    ui.continue_works = False
    ui.next_state = "unknown"
    ui.errors["button"] = TimeoutError("click timeout")
    with pytest.raises(RuntimeError, match="3 verified attempts"):
        ui.dashboard.select_jenis_pelanggan()
    assert sum(e[0] == "button" for e in ui.clicks()) == 3
    assert ui.elapsed == 70000
    assert len(ui.polls) == 3


def test_continue_button_portal_fallback(ui):
    ui.button_visible = False
    ui.portal_button = True
    ui.dashboard.select_jenis_pelanggan()
    assert ui.clicks()[-1][0] == "portal_button"


def test_continue_reselects_lost_selection(ui):
    ui.dashboard._continue_jenis_pelanggan_with_confirmation(HOUSEHOLD)
    assert [e[0] for e in ui.clicks()] == ["label", "button"]


def test_repeated_invocation_after_modal_disappears(ui):
    ui.next_state = "disappeared"
    assert ui.dashboard.select_jenis_pelanggan_if_needed() is True
    assert ui.dashboard.select_jenis_pelanggan_if_needed() is False
    assert len(ui.clicks()) == 2


def make_component(ui):
    from src.infrastructure.browser.page_objects.customer_type_modal import (
        CustomerTypeModal,
    )

    def first_usable(collection, *, require_enabled=True):
        for index in range(collection.count()):
            candidate = collection.nth(index)
            if candidate.is_visible() and (not require_enabled or candidate.is_enabled()):
                return candidate
        return None

    return CustomerTypeModal(
        page=ui.page, modal=ui.modal, is_visible=lambda locator: locator.is_visible(),
        first_usable_locator=first_usable,
        followup_probe=lambda: ui.followup if ui.followup != "unknown" else None,
        checkpoint=lambda label, **kw: ui.diagnostics.append((label, kw.get("target_name"))),
        poll_states=ui.polls.append,
        continue_locator_factory=lambda: ui.modal.locator("button"),
        log=lambda *a: ui.logs.append(tuple(str(v) for v in a)),
        expect_locator=lambda locator: locator,
    )


@pytest.mark.parametrize("scenario", ["immediate", "native_selected", "visual_selected", "delayed", "unconfirmed", "click_error", "unexpected", "session"])
def test_component_selection(ui, scenario):
    component = make_component(ui)
    if scenario in {"native_selected", "visual_selected"}:
        ui.selected = HOUSEHOLD
        ui.visual_only = scenario == "visual_selected"
    ui.selection_delay = 400 if scenario == "delayed" else 0
    ui.selection_works = scenario != "unconfirmed"
    error = {
        "click_error": Error("after effect"), "unexpected": ValueError("unexpected"),
        "session": SessionExpiredError("session"),
    }.get(scenario)
    if error:
        ui.errors["label"] = error
    if scenario in {"unexpected", "session", "unconfirmed"}:
        with pytest.raises(type(error) if error else RuntimeError) as caught:
            component.select_with_confirmation(HOUSEHOLD, ui.choice)
        if error:
            assert caught.value is error
        else:
            assert "after 3 attempts" in str(caught.value)
            assert ui.clicks() == [("label", "click", HOUSEHOLD, 5000)] * 3
            assert ui.elapsed == 3 * 5000 + 2 * 300
            assert ui.diagnostics.count(("customer_type_radio_after_click", None)) == 3
    else:
        assert component.select_with_confirmation(HOUSEHOLD, ui.choice) is None
        assert component.is_selected(HOUSEHOLD)
        assert len(ui.clicks()) == (0 if scenario.endswith("selected") else 1)
        assert ui.elapsed == (400 if scenario == "delayed" else 0)
    if error:
        assert ("customer_type_radio_after_click", None) in ui.diagnostics


@pytest.mark.parametrize("scenario", ["label", "native", "missing", "delayed", "generic"])
def test_component_option_lookup(ui, scenario):
    component = make_component(ui)
    ui.label_visible = scenario != "native"
    if scenario == "missing":
        ui.options = []
    elif scenario == "delayed":
        ui.option_at = 200
    elif scenario == "generic":
        ui.options = ["Other"]
    choice = component.find_named_choice(HOUSEHOLD)
    if scenario in {"missing", "delayed", "generic"}:
        assert choice is None
    else:
        assert choice.kind == ("radio" if scenario == "native" else "label")
        if scenario == "native":
            component.select_with_confirmation(HOUSEHOLD, choice)
            assert ui.clicks()[0][:3] == ("radio", "click", HOUSEHOLD)
    if scenario == "generic":
        choice = component.find_first_available_choice()
        component.select_with_confirmation("first visible/enabled customer type", choice)
        assert component.is_any_selected()
    if scenario == "delayed":
        assert ui.elapsed == 0
        ui.page.wait_for_timeout(200)
        assert component.find_named_choice(HOUSEHOLD).kind == "label"


@pytest.mark.parametrize("scenario", ["ready", "next_modal", "disappeared", "absent", "delayed", "button_late", "button_missing", "disabled", "pending", "unknown", "click_error", "selection_missing"])
def test_component_continue(ui, scenario):
    component = make_component(ui)
    ui.selected = HOUSEHOLD
    if scenario == "next_modal":
        ui.next_state = "nib_reminder"  # Observe only; never act on that modal.
    if scenario in {"disappeared", "absent"}:
        ui.next_state = "disappeared"
    if scenario == "absent":
        ui.visible = False
    ui.continue_delay = 750 if scenario == "delayed" else 0
    ui.button_at = 600 if scenario == "button_late" else 0
    ui.button_visible = scenario != "button_missing"
    ui.enabled = scenario != "disabled"
    ui.continue_works = scenario != "pending"
    if scenario == "unknown":
        ui.next_state = "unknown"
    if scenario == "click_error":
        ui.errors["button"] = Error("after effect")
    if scenario == "selection_missing":
        ui.selected = None
        ui.options = []
    if scenario in {"button_missing", "disabled", "pending", "unknown", "selection_missing"}:
        with pytest.raises(RuntimeError) as caught:
            component.continue_with_confirmation(HOUSEHOLD)
        assert len(ui.clicks()) == (3 if scenario in {"pending", "unknown"} else 0)
        if scenario in {"pending", "unknown"}:
            assert "3 verified attempts" in str(caught.value)
            assert ui.elapsed == 61000
            assert len(ui.polls) == 3
        elif scenario in {"button_missing", "disabled"}:
            assert ("disabled" if scenario == "disabled" else "did not become visible") in str(caught.value)
            assert ui.elapsed == (15000 if scenario == "button_missing" else 0)
    else:
        assert component.continue_with_confirmation(HOUSEHOLD) is None
        assert len(ui.clicks()) == (0 if scenario == "absent" else 1)
        assert ui.elapsed == (750 if scenario == "delayed" else 600 if scenario == "button_late" else 0)
        if scenario == "click_error":
            assert ui.followup == "transaction_ready"
            assert any(label == "customer_type_continue_after_click" for label, _ in ui.diagnostics)


def test_component_final_timeout_boundary_observation(ui):
    component = make_component(ui)
    ui.due_selection = (100, HOUSEHOLD)
    assert component.wait_for_selection(HOUSEHOLD, timeout_ms=100) is True
    ui.due_continue = ui.elapsed + 250
    assert component.wait_for_transition(timeout_ms=250) is True
    assert ui.elapsed == 350


def test_dashboard_adapters_resolve_current_dependencies(ui, monkeypatch):
    from unittest.mock import Mock

    from src.infrastructure.browser.page_objects.customer_type_modal import (
        CustomerTypeModal,
    )

    original = CustomerTypeModal.find_named_choice
    seen = []

    def lookup(component, name):
        seen.append(component.modal)
        return original(component, name)

    monkeypatch.setattr(CustomerTypeModal, "find_named_choice", lookup)
    assert ui.dashboard._find_named_customer_type_choice(HOUSEHOLD).value == HOUSEHOLD
    replacement = Mock()
    replacement.locator.return_value.first.count.return_value = 0
    ui.dashboard.jenis_pelanggan_modal = replacement
    assert ui.dashboard._find_named_customer_type_choice(HOUSEHOLD) is None
    assert seen == [ui.modal, replacement]
