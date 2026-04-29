from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from src.logging_utils import log_print

if TYPE_CHECKING:
    from src.infrastructure.browser.page_objects.dashboard_page import Dashboard
    from src.infrastructure.browser.page_objects.penjualan_page import Penjualan
    from src.web.rate_limiter import SkipRateLimiter
    from src.web.reporter import TransactionReporter


@dataclass(frozen=True)
class TransactionBlockerOutcome:
    should_skip: bool = False
    stop_reason: str | None = None


class TransactionPrechecksService:
    """Encapsulates skip-or-stop checks before and during a transaction."""

    def __init__(
        self,
        *,
        page,
        dashboard: "Dashboard",
        reporter: "TransactionReporter",
        limiter: "SkipRateLimiter",
        post_skip_cooldown_ms: int,
        max_kuota_timeout_ms: int,
        zero_stock_timeout_ms: int,
        log_func: Callable[..., None] = log_print,
    ) -> None:
        self.page = page
        self.dashboard = dashboard
        self.reporter = reporter
        self.limiter = limiter
        self.post_skip_cooldown_ms = post_skip_cooldown_ms
        self.max_kuota_timeout_ms = max_kuota_timeout_ms
        self.zero_stock_timeout_ms = zero_stock_timeout_ms
        self.log_func = log_func

    def handle_pre_checks(self, nik: str, started_at: str) -> bool:
        """Return True when a pre-check handles the NIK and processing must stop."""
        entry_outcome = self.dashboard.resolve_customer_entry()
        if entry_outcome == "under_17":
            return self._handle_under_17(nik, started_at)

        if entry_outcome == "transaction_ready":
            return False

        if entry_outcome == "customer_type_selected":
            return self._handle_customer_type_follow_up(nik, started_at)

        if entry_outcome == "precheck_modal":
            modal_name = self.dashboard.get_visible_precheck_modal()
            if modal_name is not None:
                return self._handle_precheck_modal(modal_name, nik, started_at)

        if self.dashboard.is_transaction_form_ready():
            return False

        modal_name = self.dashboard.wait_for_precheck_modal()
        if modal_name is None:
            return False

        return self._handle_precheck_modal(modal_name, nik, started_at)

    def _handle_customer_type_follow_up(self, nik: str, started_at: str) -> bool:
        follow_up_outcome = self.dashboard.wait_for_transaction_form_or_precheck_modal()
        if follow_up_outcome == "transaction_ready":
            return False
        if follow_up_outcome != "precheck_modal":
            return False

        modal_name = self.dashboard.get_visible_precheck_modal()
        if modal_name is None:
            return False
        return self._handle_precheck_modal(modal_name, nik, started_at)

    def _handle_precheck_modal(
        self, modal_name: str, nik: str, started_at: str
    ) -> bool:
        if modal_name == "not_registered":
            return self._handle_not_registered(nik, started_at)
        if modal_name == "perbarui":
            return self._handle_perbarui_data_pelanggan(nik, started_at)
        if modal_name == "invalid_registered_nik":
            return self._handle_invalid_registered_nik(nik, started_at)
        if modal_name == "cannot_transact_at_base":
            return self._handle_cannot_transact_at_base(nik, started_at)
        if modal_name == "unusual_transaction":
            return self._handle_unusual_transaction(nik, started_at)
        return False

    def _handle_under_17(self, nik: str, started_at: str) -> bool:
        under_17_reason = self.dashboard.read_under_17_validation_if_present(
            detect_timeout=500
        )
        if not under_17_reason:
            return False

        self.dashboard.reset_nik_input_or_return_to_dashboard(
            reset_action_name="clearing NIK input after under-17 validation",
            reset_log="Cleared NIK input after under-17 validation message.",
            dashboard_log="Under-17 validation handled; returned to dashboard.",
        )
        self._record_skip_and_cooldown(
            nik=nik,
            started_at=started_at,
            skip_callback=lambda: self.reporter.skip_under_17(
                nik,
                started_at,
                url=self.page.url,
            ),
            message=f"Skipping NIK {nik} ({under_17_reason}).",
        )
        return True

    def _handle_not_registered(self, nik: str, started_at: str) -> bool:
        not_registered_reason = (
            self.dashboard.read_pelanggan_tidak_terdaftar_reason_if_present(
                detect_timeout=500
            )
        )
        if not not_registered_reason:
            return False

        self.dashboard.dismiss_pelanggan_tidak_terdaftar_modal()
        self.dashboard.reset_nik_input_or_return_to_dashboard(
            reset_action_name="resetting NIK input after pelanggan modal",
            reset_log="Closed 'Pelanggan Tidak Terdaftar'; NIK input reset.",
            dashboard_log="Closed 'Pelanggan Tidak Terdaftar'; returned to dashboard.",
        )
        self._record_skip_and_cooldown(
            nik=nik,
            started_at=started_at,
            skip_callback=lambda: self.reporter.skip_not_registered(
                nik,
                started_at,
                url=self.page.url,
                reason=not_registered_reason,
            ),
            message=f"Skipping NIK {nik} ({not_registered_reason}).",
        )
        return True

    def _handle_perbarui_data_pelanggan(self, nik: str, started_at: str) -> bool:
        perbarui_action = self.dashboard.attempt_continue_perbarui_data_pelanggan()
        if perbarui_action == "continued":
            return False

        self.dashboard.dismiss_perbarui_data_pelanggan_modal()
        self.dashboard.reset_nik_input_or_return_to_dashboard(
            reset_action_name="resetting NIK input after Perbarui Data Pelanggan modal",
            reset_log="Closed 'Perbarui Data Pelanggan'; NIK input reset.",
            dashboard_log="Closed 'Perbarui Data Pelanggan'; returned to dashboard.",
        )
        needs_update_reason = (
            "Perbarui Data Pelanggan cannot continue transaction; modal closed."
            if perbarui_action == "cannot_continue"
            else "Perbarui Data Pelanggan closed; transaction skipped."
        )
        self._record_skip_and_cooldown(
            nik=nik,
            started_at=started_at,
            skip_callback=lambda: self.reporter.skip_needs_update(
                nik,
                started_at,
                url=self.page.url,
                reason=needs_update_reason,
            ),
            message=f"Skipping NIK {nik} ({needs_update_reason})",
        )
        return True

    def _handle_invalid_registered_nik(self, nik: str, started_at: str) -> bool:
        invalid_registered_nik_reason = (
            self.dashboard.read_invalid_registered_nik_reason_if_present(
                detect_timeout=500
            )
        )
        if not invalid_registered_nik_reason:
            return False

        self.dashboard.dismiss_invalid_registered_nik_modal()
        self.dashboard.reset_nik_input_or_return_to_dashboard(
            reset_action_name="resetting NIK input after warning modal",
            reset_log="Closed invalid registered-customer NIK modal; NIK input reset.",
            dashboard_log="Closed invalid registered-customer NIK modal; returned to dashboard.",
        )
        self._record_skip_and_cooldown(
            nik=nik,
            started_at=started_at,
            skip_callback=lambda: self.reporter.skip_invalid_registered_nik(
                nik,
                started_at,
                url=self.page.url,
            ),
            message=f"Skipping NIK {nik} ({invalid_registered_nik_reason}).",
        )
        return True

    def _handle_cannot_transact_at_base(self, nik: str, started_at: str) -> bool:
        cannot_transact_at_base_reason = (
            self.dashboard.read_cannot_transact_at_base_reason_if_present(
                detect_timeout=500
            )
        )
        if not cannot_transact_at_base_reason:
            return False

        self.dashboard.dismiss_cannot_transact_at_base_modal()
        self.dashboard.reset_nik_input_or_return_to_dashboard(
            reset_action_name="resetting NIK input after warning modal",
            reset_log="Closed base-restriction modal; NIK input reset.",
            dashboard_log="Closed base-restriction modal; returned to dashboard.",
        )
        self._record_skip_and_cooldown(
            nik=nik,
            started_at=started_at,
            skip_callback=lambda: self.reporter.skip_cannot_transact_at_base(
                nik,
                started_at,
                url=self.page.url,
            ),
            message=f"Skipping NIK {nik} ({cannot_transact_at_base_reason}).",
        )
        return True

    def _handle_unusual_transaction(self, nik: str, started_at: str) -> bool:
        unusual_transaction_reason = (
            self.dashboard.read_unusual_transaction_reason_if_present(
                detect_timeout=500
            )
        )
        if not unusual_transaction_reason:
            return False

        self.dashboard.dismiss_unusual_transaction_modal()
        self.dashboard.reset_nik_input_or_return_to_dashboard(
            reset_action_name="resetting NIK input after warning modal",
            reset_log="Closed unusual-transaction modal; NIK input reset.",
            dashboard_log="Closed unusual-transaction modal; returned to dashboard.",
        )
        self._record_skip_and_cooldown(
            nik=nik,
            started_at=started_at,
            skip_callback=lambda: self.reporter.skip_unusual_transaction_at_other_base(
                nik,
                started_at,
                url=self.page.url,
            ),
            message=f"Skipping NIK {nik} ({unusual_transaction_reason}).",
        )
        return True

    def check_transaction_blocker(
        self,
        penjualan: "Penjualan",
        nik: str,
        started_at: str,
        stage: str,
        timeout_ms: int | None = None,
    ) -> TransactionBlockerOutcome:
        """Return the handling outcome for a visible transaction blocker alert."""
        alert = penjualan.read_transaction_blocker_alert(
            timeout=(
                timeout_ms
                if timeout_ms is not None
                else max(self.max_kuota_timeout_ms, self.zero_stock_timeout_ms)
            )
        )
        if alert is None:
            return TransactionBlockerOutcome()

        alert_kind, alert_text = alert
        if alert_kind == "zero_stock":
            stop_reason = self._record_zero_stock_skip(
                nik=nik,
                started_at=started_at,
                stage=stage,
                alert_text=alert_text,
            )
            return TransactionBlockerOutcome(stop_reason=stop_reason)

        self._record_max_kuota_skip(
            penjualan=penjualan, nik=nik, started_at=started_at, stage=stage
        )
        return TransactionBlockerOutcome(should_skip=True)

    def check_max_kuota(
        self, penjualan: "Penjualan", nik: str, started_at: str, stage: str
    ) -> bool:
        """Return True when the transaction must be skipped for max kuota."""
        if not penjualan.is_max_kuota_alert_present(timeout=self.max_kuota_timeout_ms):
            return False

        self._record_max_kuota_skip(
            penjualan=penjualan, nik=nik, started_at=started_at, stage=stage
        )
        return True

    def check_zero_stock(
        self, penjualan: "Penjualan", nik: str, started_at: str, stage: str
    ) -> str | None:
        """Return a stop reason after recording the skip when stock is empty."""
        alert_text = penjualan.get_zero_stock_alert_text(
            timeout=self.zero_stock_timeout_ms
        )
        if not alert_text:
            return None

        if not penjualan.is_zero_stock_alert_text(alert_text):
            return None

        return self._record_zero_stock_skip(
            nik=nik,
            started_at=started_at,
            stage=stage,
            alert_text=alert_text,
        )

    def _record_max_kuota_skip(
        self, *, penjualan: "Penjualan", nik: str, started_at: str, stage: str
    ) -> None:
        try:
            penjualan.ganti_pelanggan()
        except Exception:
            # Preserve current behavior: ignore failures when attempting to switch customer.
            pass

        self._record_skip_and_cooldown(
            nik=nik,
            started_at=started_at,
            skip_callback=lambda: self.reporter.skip_max_kuota(
                nik, started_at, url=self.page.url, reason=f"Max kuota {stage}"
            ),
            message=f"Skipping NIK {nik} (max kuota {stage}).",
        )

    def _record_zero_stock_skip(
        self, *, nik: str, started_at: str, stage: str, alert_text: str
    ) -> str:
        reason = f"Sellable stock empty {stage}: {alert_text}"
        self._record_skip_and_cooldown(
            nik=nik,
            started_at=started_at,
            skip_callback=lambda: self.reporter.skip_out_of_stock(
                nik,
                started_at,
                url=self.page.url,
                reason=reason,
            ),
            message=(
                f"Stopping account run for NIK {nik} because sellable stock "
                f"is empty ({stage})."
            ),
        )
        return reason

    def _record_skip_and_cooldown(
        self,
        *,
        nik: str,
        started_at: str,
        skip_callback: Callable[[], None],
        message: str,
    ) -> None:
        self.limiter.record_skip()
        skip_callback()
        self.log_func(message)
        self.page.wait_for_timeout(self.post_skip_cooldown_ms)
