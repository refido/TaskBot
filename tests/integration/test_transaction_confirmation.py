import pytest

from src.infrastructure.browser.page_objects.cek_penjualan_page import CekPenjualan
from src.pipelines.slider.success import SuccessDetector
from src.pipelines.slider.types import SliderConfig


SUCCESS = '<button>KEMBALI KE HALAMAN UTAMA</button>'
BLOCKER = (
    '<section role="dialog"><h2>Terlalu banyak permintaan</h2>'
    '<p>Terdapat beberapa data yang belum lengkap. Lengkapi data dahulu '
    'untuk melanjutkan transaksi.</p><button>TUTUP</button></section>'
)


@pytest.mark.parametrize("html,status,reason", [
    (SUCCESS, "completed", ""),
    (BLOCKER, "blocked", "customer_data_required"),
    (SUCCESS + BLOCKER, "blocked", "customer_data_required"),
    ("<p>Waiting for server</p>", "unknown", "confirmation_timeout"),
    ('<section role="dialog">Terlalu banyak permintaan<p>Try later</p></section>',
     "unknown", "confirmation_timeout"),
    ('<div hidden>' + BLOCKER + '</div>' + SUCCESS, "completed", ""),
    ('<section role="dialog">Data Pelanggan berhasil diperbarui' + SUCCESS + '</section>',
     "unknown", "customer_update_result"),
], ids=["success", "customer-data", "blocker-priority", "timeout", "different-warning",
        "stale-hidden-warning", "customer-update-is-not-sale"])
def test_hidden_captcha_requires_independent_transaction_result(page, html, status, reason):
    # Entirely local DOM reproduction; no merchant account or live transaction.
    page.set_content('<div class="rc-slider-captcha" hidden></div>' + html)
    captcha_finished = SuccessDetector(SliderConfig()).check_success(
        page, page.locator(".rc-slider-captcha")
    )
    assert captcha_finished is True
    outcome = CekPenjualan(page).wait_for_transaction_outcome(timeout_ms=200)
    assert outcome.status == status
    assert outcome.reason == reason
    assert outcome.success_confirmed is (status == "completed")
