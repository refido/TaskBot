from unittest.mock import Mock

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.infrastructure.browser.page_objects.dashboard_page import Dashboard
from src.web.session_state import SessionExpiredError


def mismatch_html(buttons):
    return (
        '<section role="dialog"><h6>NIK Pelanggan Tidak Padan</h6>'
        f'{buttons}<button onclick="this.parentElement.remove()">Tutup</button>'
        '</section>'
    )


def local_dashboard(page):
    dashboard = Dashboard(page)
    dashboard._raise_if_session_expired = lambda **_kwargs: None
    click = dashboard.click_locator

    def fast_click(locator, **kwargs):
        kwargs["timeout_ms"] = 2000
        click(locator, **kwargs)

    dashboard.click_locator = fast_click
    return dashboard


def test_mismatch_exact_title_and_visible_modal_scope(page):
    page.set_content(
        '<button onclick="window.wrongClick = true">LANJUTKAN Penjualan</button>'
        '<section hidden><h6>NIK Pelanggan Tidak Padan</h6>'
        '<button>LANJUTKAN Penjualan</button></section>'
        '<div aria-hidden="true">' + mismatch_html(
            '<button onclick="this.parentElement.remove()">LANJUTKAN Penjualan</button>'
        ) + '</div>'
    )
    dashboard = local_dashboard(page)

    assert dashboard.get_visible_precheck_modal() == "nik_mismatch"
    assert dashboard.get_visible_customer_entry() == "precheck_modal"
    assert dashboard.attempt_continue_nik_mismatch() is True
    assert dashboard.get_visible_precheck_modal() is None
    assert page.evaluate("window.wrongClick === undefined")


@pytest.mark.parametrize("content", [
    '<button>LANJUTKAN Penjualan</button>',
    '<section role="dialog"><h6>NIK Pelanggan Tidak Padan Lain</h6></section>',
    '<section role="dialog"><h6 hidden>NIK Pelanggan Tidak Padan</h6><button>Tutup</button></section>',
    '<div hidden>' + mismatch_html('<button>LANJUTKAN Penjualan</button>') + '</div>',
])
def test_no_visible_exact_mismatch_keeps_normal_detection(page, content):
    page.set_content(content)
    assert Dashboard(page).get_visible_precheck_modal() is None


@pytest.mark.parametrize("button", [
    '',
    '<button hidden>LANJUTKAN Penjualan</button>',
    '<button disabled>LANJUTKAN Penjualan</button>',
    '<button style="pointer-events:none">LANJUTKAN Penjualan</button>',
], ids=["absent", "hidden", "disabled", "not-clickable"])
def test_unavailable_proceed_uses_scoped_tutup(page, button):
    page.set_content(
        '<button onclick="window.wrongClose = true">Tutup</button>'
        + mismatch_html(button)
    )
    dashboard = local_dashboard(page)

    assert dashboard.get_visible_precheck_modal() == "nik_mismatch"
    assert dashboard.attempt_continue_nik_mismatch() is False
    assert dashboard.get_visible_precheck_modal() == "nik_mismatch"
    dashboard.dismiss_nik_mismatch_modal()
    assert dashboard.get_visible_precheck_modal() is None
    assert page.evaluate("window.wrongClose === undefined")


def test_continue_requires_modal_transition_and_preserves_unexpected_errors():
    dashboard = Dashboard.__new__(Dashboard)
    dashboard.nik_mismatch_continue = object()
    dashboard.nik_mismatch_modal = Mock()
    dashboard.nik_mismatch_modal.wait_for.side_effect = PlaywrightTimeoutError("still visible")
    dashboard.click_locator = Mock()
    assert dashboard.attempt_continue_nik_mismatch() is False
    dashboard.click_locator.assert_called_once()

    for error in (SessionExpiredError("expired"), RuntimeError("unexpected")):
        dashboard.click_locator.side_effect = error
        with pytest.raises(type(error)) as raised:
            dashboard.attempt_continue_nik_mismatch()
        assert raised.value is error
