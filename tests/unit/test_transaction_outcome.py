from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.application.models.transaction_outcome import TransactionOutcome
from src.infrastructure.browser.page_objects import cek_penjualan_page as module


MESSAGE = (
    "Terlalu banyak permintaan\n"
    "Terdapat beberapa data yang belum lengkap. Lengkapi data dahulu untuk "
    "melanjutkan transaksi.\nTUTUP"
)


@pytest.fixture
def result_page(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    sale = module.CekPenjualan.__new__(module.CekPenjualan)

    def advance(ms):
        clock[0] += ms / 1000

    sale.page = SimpleNamespace(wait_for_timeout=Mock(side_effect=advance))
    for name in (
        "customer_data_required_modal", "zero_stock_modal",
        "transaction_blocker_alert", "kembali_button", "customer_update_success",
    ):
        setattr(sale, name, SimpleNamespace(
            is_visible=Mock(return_value=False), inner_text=Mock(return_value=MESSAGE)
        ))
    return sale


def test_waits_for_explicit_success_after_captcha_finishes(result_page):
    result_page.kembali_button.is_visible.side_effect = [False, False, True]
    outcome = result_page.wait_for_transaction_outcome()
    assert outcome == TransactionOutcome("completed", evidence="KEMBALI KE HALAMAN UTAMA")
    assert outcome.success_confirmed
    assert result_page.page.wait_for_timeout.call_count == 2


def test_blocking_modal_beats_stale_success_button(result_page):
    result_page.customer_data_required_modal.is_visible.return_value = True
    result_page.kembali_button.is_visible.return_value = True
    outcome = result_page.wait_for_transaction_outcome()
    assert outcome == TransactionOutcome("blocked", "customer_data_required", MESSAGE)
    assert not outcome.success_confirmed
    result_page.kembali_button.is_visible.assert_not_called()


def test_missing_success_times_out_instead_of_completing(result_page):
    assert result_page.wait_for_transaction_outcome(timeout_ms=250) == TransactionOutcome(
        "unknown", "confirmation_timeout"
    )
    assert sum(c.args[0] for c in result_page.page.wait_for_timeout.call_args_list) == 250


def test_customer_update_success_is_not_transaction_success(result_page):
    result_page.customer_update_success.is_visible.return_value = True
    result_page.kembali_button.is_visible.return_value = True
    outcome = result_page.wait_for_transaction_outcome()
    assert outcome.status == "unknown"
    assert outcome.reason == "customer_update_result"
    assert not outcome.success_confirmed


@pytest.mark.parametrize("message,kind", [
    ("Tidak dapat transaksi karena stok tabung kosong", "zero_stock"),
    ("Tidak dapat transaksi karena telah melebihi batas kewajaran pembelian LPG 3 kg bulan ini.", "max_kuota"),
])
def test_existing_business_rejections_keep_their_kind(result_page, message, kind):
    result_page.transaction_blocker_alert.is_visible.return_value = True
    result_page.transaction_blocker_alert.inner_text.return_value = message
    assert result_page.wait_for_transaction_outcome() == TransactionOutcome("blocked", kind, message)


def test_stock_empty_modal_is_a_stop_outcome(result_page):
    result_page.zero_stock_modal.is_visible.return_value = True
    assert result_page.wait_for_transaction_outcome() == TransactionOutcome(
        "blocked", "zero_stock", "Stok Tabung Kosong"
    )


def test_unexpected_observation_error_is_not_silently_successful(result_page):
    result_page.customer_data_required_modal.is_visible.side_effect = RuntimeError("closed")
    with pytest.raises(RuntimeError, match="closed"):
        result_page.wait_for_transaction_outcome()


def test_rejection_requires_both_observed_title_and_customer_data_message():
    # A generic rate-limit title or this title's unrelated body is not enough.
    assert module._CUSTOMER_DATA_REQUIRED_TITLE.search(MESSAGE)
    assert module._CUSTOMER_DATA_REQUIRED_MESSAGE.search(MESSAGE)
    assert not module._CUSTOMER_DATA_REQUIRED_MESSAGE.search("Terlalu banyak permintaan")
    assert not module._CUSTOMER_DATA_REQUIRED_MESSAGE.search(
        "Terlalu banyak melakukan permintaan pendaftaran untuk NIK pelanggan ini. "
        "Silakan coba lagi di hari berikutnya."
    )
