import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.infrastructure.browser.page_objects.dashboard_page import Dashboard

TITLE = "Tidak Dapat Melakukan Transaksi"
MESSAGE = (
    "NIK teridentifikasi dengan status MENINGGAL sesuai Data Kependudukan. "
    "Apabila data tidak sesuai, konsumen dapat melakukan perubahan data ke Dinas "
    "Kependudukan dan Pencatatan Sipil terdekat. Info lebih lanjut, hubungi 135."
)


def modal_html(*, title=TITLE, message=MESSAGE, button="TUTUP"):
    return (
        f'<section role="dialog"><div><h6>{title}</h6>'
        f'<div><div class="mantine-Text-root">{message}</div></div></div>'
        "<div><button onclick=\"this.closest('section').remove()\">"
        f"{button}</button></div></section>"
    )


@pytest.mark.parametrize("aria_hidden", [False, True])
def test_cannot_transact_reads_reason_and_closes_only_visible_exact_modal(
    page, aria_hidden
):
    page.set_content(
        '<button onclick="window.wrongClose = true">TUTUP</button>'
        "<section hidden><h6>" + TITLE + "</h6><button>TUTUP</button></section>"
        f'<div aria-hidden="{str(aria_hidden).lower()}">' + modal_html() + "</div>"
    )
    dashboard = Dashboard(page)
    dashboard._raise_if_session_expired = lambda **_kwargs: None

    assert dashboard.wait_for_precheck_modal(detect_timeout=100) == "cannot_transact"
    assert dashboard.get_visible_customer_entry() == "precheck_modal"
    assert (
        dashboard.wait_for_transaction_form_or_precheck_modal(100) == "precheck_modal"
    )
    assert dashboard.read_cannot_transact_reason_if_present(100) == MESSAGE
    dashboard.dismiss_cannot_transact_modal()
    assert dashboard.get_visible_precheck_modal() is None
    assert page.evaluate("window.wrongClose === undefined")


@pytest.mark.parametrize(
    "content",
    [
        modal_html(title=TITLE + " Lain"),
        "<section><h6 hidden>" + TITLE + "</h6><button>TUTUP</button></section>",
        "<div hidden>" + modal_html() + "</div>",
        "<div>" + TITLE + "</div><button>TUTUP</button>",
    ],
)
def test_cannot_transact_ignores_hidden_or_inexact_title(page, content):
    page.set_content(content)
    assert Dashboard(page).get_visible_precheck_modal() is None


def test_invalid_registered_nik_retains_existing_mapping(page):
    page.set_content(modal_html(message="NIK pelanggan yang didaftarkan tidak valid."))
    assert Dashboard(page).get_visible_precheck_modal() == "invalid_registered_nik"


@pytest.mark.parametrize(
    "button",
    [
        "<button hidden>TUTUP</button>",
        "<button disabled>TUTUP</button>",
        '<button style="pointer-events:none">TUTUP</button>',
        "<button>TUTUP LAIN</button>",
    ],
)
def test_cannot_transact_requires_actionable_exact_close(page, button):
    page.set_content(
        '<button onclick="window.wrongClose = true">TUTUP</button>'
        f"<section><h6>{TITLE}</h6>{button}</section>"
    )
    dashboard = Dashboard(page)
    dashboard._raise_if_session_expired = lambda **_kwargs: None
    click = dashboard.click_locator

    def fast_click(locator, **kwargs):
        kwargs["timeout_ms"] = 200
        click(locator, **kwargs)

    dashboard.click_locator = fast_click
    with pytest.raises((AssertionError, PlaywrightTimeoutError)):
        dashboard.dismiss_cannot_transact_modal()
    assert dashboard.get_visible_precheck_modal() == "cannot_transact"
    assert page.evaluate("window.wrongClose === undefined")
