import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.infrastructure.browser.page_objects.dashboard_page import Dashboard


TITLE = "NIK pelanggan diblokir karena pelanggan terindikasi fraud"


def modal_html(*, title=TITLE, button="TUTUP"):
    return (
        '<section><div><h6 class="mantine-Text-root mantine-Title-root">'
        f'{title}</h6></div><div><button '
        'onclick="this.closest(\'section\').remove()">'
        f'{button}</button></div></section>'
    )


@pytest.mark.parametrize("aria_hidden", [False, True])
def test_fraud_reads_reason_and_closes_only_visible_exact_modal(page, aria_hidden):
    page.set_content(
        '<button>CEK PESANAN</button>'
        '<button onclick="window.wrongClose = true">TUTUP</button>'
        '<section hidden><h6>' + TITLE + '</h6><button>TUTUP</button></section>'
        f'<div aria-hidden="{str(aria_hidden).lower()}">' + modal_html() + '</div>'
    )
    dashboard = Dashboard(page)
    dashboard._raise_if_session_expired = lambda **_kwargs: None

    assert dashboard.wait_for_precheck_modal(detect_timeout=100) == "fraud"
    assert dashboard.get_visible_customer_entry() == "precheck_modal"
    assert not dashboard.is_transaction_form_ready(detect_timeout=100)
    assert dashboard.wait_for_transaction_form_or_precheck_modal(100) == "precheck_modal"
    assert dashboard.read_fraud_reason_if_present(100) == TITLE
    dashboard.dismiss_fraud_modal()
    assert dashboard.get_visible_precheck_modal() is None
    assert page.evaluate("window.wrongClose === undefined")


@pytest.mark.parametrize("content", [
    modal_html(title=TITLE + " lain"),
    '<section><h6 hidden>' + TITLE + '</h6><button>TUTUP</button></section>',
    '<div hidden>' + modal_html() + '</div>',
    '<div>' + TITLE + '</div><button>TUTUP</button>',
])
def test_fraud_ignores_hidden_or_inexact_title(page, content):
    page.set_content(content)
    assert Dashboard(page).get_visible_precheck_modal() is None


@pytest.mark.parametrize("button", [
    '<button hidden>TUTUP</button>',
    '<button disabled>TUTUP</button>',
    '<button style="pointer-events:none">TUTUP</button>',
    '<button>TUTUP LAIN</button>',
])
def test_fraud_requires_actionable_exact_close(page, button):
    page.set_content(
        '<button onclick="window.wrongClose = true">TUTUP</button>'
        f'<section><h6>{TITLE}</h6>{button}</section>'
    )
    dashboard = Dashboard(page)
    dashboard._raise_if_session_expired = lambda **_kwargs: None
    click = dashboard.click_locator

    def fast_click(locator, **kwargs):
        kwargs["timeout_ms"] = 200
        click(locator, **kwargs)

    dashboard.click_locator = fast_click
    with pytest.raises((AssertionError, PlaywrightTimeoutError)):
        dashboard.dismiss_fraud_modal()
    assert dashboard.get_visible_precheck_modal() == "fraud"
    assert page.evaluate("window.wrongClose === undefined")
