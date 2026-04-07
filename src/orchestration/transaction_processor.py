from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from playwright.sync_api import Page

from src.config import Config
from src.logging_utils import log_print, logger
from src.pipelines.solve_slider import solve_slider_with_puzzle
from src.vision.puzzle_solver import PuzzleSolver
from src.web.helpers import Helpers
from src.web.pages.cek_penjualan import CekPenjualan
from src.web.pages.dashboard import Dashboard
from src.web.pages.login import Login
from src.web.pages.penjualan import Penjualan
from src.web.rate_limiter import SkipRateLimiter
from src.web.reporter import TransactionReporter


class OutOfSellableStockError(RuntimeError):
    """Raised when the site reports that sellable stock is empty."""


class PuzzleSolveFailedError(RuntimeError):
    """Raised when the puzzle challenge could not be solved."""


@dataclass(slots=True)
class PuzzleSolveOutcome:
    solved: bool
    attempts: int
    retry_count: int = 0
    retry_process: str = ""


class TransactionProcessor:
    """Handles processing of transactions with error handling and recovery."""

    _LOAD_STATE: str = "load"
    _MAX_KUOTA_TIMEOUT_MS: int = 1500
    _ZERO_STOCK_TIMEOUT_MS: int = 1500
    _LOGGED_OUT_CHECK_TIMEOUT_MS: int = 800
    _POST_SKIP_COOLDOWN_MS: int = 300
    _MAX_WAIT_SUCCESS_MS: int = 3500
    _MAX_PUZZLE_RETRIES: int = 1
    _PUZZLE_RETRY_MODAL_TIMEOUT_MS: int = 2500
    _PUZZLE_REFRESH_TIMEOUT_MS: int = 5000
    _PUZZLE_RETRY_PROCESS: str = "proses_penjualan"
    _PUZZLE_SOLVE_FAILED_REASON: str = "CAPTCHA solving failed"

    def __init__(
        self,
        config: Config,
        page: Page,
        reporter: TransactionReporter,
        limiter: SkipRateLimiter,
    ) -> None:
        self.config = config
        self.page = page
        self.reporter = reporter
        self.limiter = limiter

        self.dashboard = Dashboard(page)
        self.login = Login(page)

    def process_all_niks(self) -> None:
        """Process all NIKs from configuration."""
        for nik in self.config.nik:
            try:
                self.process_single_nik(nik)
            except OutOfSellableStockError as exc:
                logger.bind(
                    event="transaction.out_of_stock",
                    operator=self.config.email_user,
                    nik=str(nik),
                ).warning(str(exc))
                break
            except Exception:
                # Preserve current behavior: continue processing other NIKs.
                logger.bind(
                    event="transaction.unhandled_error",
                    operator=self.config.email_user,
                    nik=str(nik),
                ).exception("Unhandled error while processing NIK")
                self._handle_session_recovery()

    def process_single_nik(self, nik: str) -> None:
        """Process a single NIK transaction."""
        started_at = self.reporter.start_item(nik)
        puzzle_solved: Optional[bool] = None
        puzzle_attempts = 0
        puzzle_retry_count = 0
        puzzle_retry_process = ""

        try:
            self._wait_for_rate_limit()
            self._navigate_to_transaction(nik)

            if self._handle_pre_checks(nik, started_at):
                return

            penjualan = Penjualan(self.page)

            self._check_zero_stock_and_stop(
                penjualan, nik, started_at, stage="before cek pesanan"
            )

            if self._check_max_kuota(
                penjualan, nik, started_at, stage="before cek pesanan"
            ):
                return

            penjualan.cek_pesanan()

            self._check_zero_stock_and_stop(
                penjualan, nik, started_at, stage="after cek pesanan"
            )

            if self._check_max_kuota(
                penjualan, nik, started_at, stage="after cek pesanan"
            ):
                return

            cek_penjualan = CekPenjualan(self.page)
            cek_penjualan.proses_penjualan()

            puzzle_outcome = self._solve_puzzle(nik)
            puzzle_solved = puzzle_outcome.solved
            puzzle_attempts = puzzle_outcome.attempts
            puzzle_retry_count = puzzle_outcome.retry_count
            puzzle_retry_process = puzzle_outcome.retry_process
            if not puzzle_solved:
                raise PuzzleSolveFailedError(
                    self._build_puzzle_failure_reason(puzzle_attempts)
                )

            self._return_to_dashboard(cek_penjualan)

            self.reporter.complete(
                nik,
                started_at,
                url=self.page.url,
                puzzle_solved=puzzle_solved,
                puzzle_attempts=puzzle_attempts,
                puzzle_retry_count=puzzle_retry_count,
                puzzle_retry_process=puzzle_retry_process,
            )
            self.limiter.record_success()

        except OutOfSellableStockError:
            raise
        except PuzzleSolveFailedError as exc:
            logger.bind(
                event="transaction.puzzle_failed",
                operator=self.config.email_user,
                nik=str(nik),
            ).warning(str(exc))
            self.reporter.failed_puzzle_solve(
                nik,
                started_at,
                exc=exc,
                url=self.page.url,
                puzzle_attempts=puzzle_attempts,
                puzzle_retry_count=puzzle_retry_count,
                puzzle_retry_process=puzzle_retry_process,
            )
            self._handle_session_recovery()
        except Exception as exc:
            logger.bind(
                event="transaction.failed",
                operator=self.config.email_user,
                nik=str(nik),
            ).exception("Failed processing NIK")
            self.reporter.error(
                nik,
                started_at,
                exc=exc,
                url=self.page.url,
                puzzle_solved=puzzle_solved,
                puzzle_attempts=puzzle_attempts,
                puzzle_retry_count=puzzle_retry_count,
                puzzle_retry_process=puzzle_retry_process,
            )
            self._handle_session_recovery()

    def _wait_for_rate_limit(self) -> None:
        self.limiter.wait_if_needed(self.page)

    def _navigate_to_transaction(self, nik: str) -> None:
        self.dashboard.catat_penjualan(nik)
        self.page.wait_for_load_state(self._LOAD_STATE)

    def _return_to_dashboard(self, cek_penjualan: CekPenjualan) -> None:
        cek_penjualan.kembali_ke_dashboard()
        self.page.wait_for_load_state(self._LOAD_STATE)
        self.dashboard.get_current_stock()

    def _handle_pre_checks(self, nik: str, started_at: str) -> bool:
        """Handle pre-transaction checks. Returns True if NIK should be skipped."""
        under_17_reason = self.dashboard.detect_under_17_nik_if_needed()
        if under_17_reason:
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

        self.dashboard.select_jenis_pelanggan_if_needed()

        invalid_registered_nik_reason = (
            self.dashboard.close_invalid_registered_nik_if_needed()
        )
        if invalid_registered_nik_reason:
            self._record_skip_and_cooldown(
                nik=nik,
                started_at=started_at,
                skip_callback=lambda: self.reporter.skip_invalid_registered_nik(
                    nik,
                    started_at,
                    url=self.page.url,
                ),
                message=(f"Skipping NIK {nik} ({invalid_registered_nik_reason})."),
            )
            return True

        unusual_transaction_reason = (
            self.dashboard.close_unusual_transaction_if_needed()
        )
        if unusual_transaction_reason:
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

        cannot_transact_at_base_reason = (
            self.dashboard.close_cannot_transact_at_base_if_needed()
        )
        if cannot_transact_at_base_reason:
            self._record_skip_and_cooldown(
                nik=nik,
                started_at=started_at,
                skip_callback=lambda: self.reporter.skip_cannot_transact_at_base(
                    nik,
                    started_at,
                    url=self.page.url,
                ),
                message=(
                    "Skipping NIK "
                    f"{nik} ({cannot_transact_at_base_reason})."
                ),
            )
            return True

        needs_update_reason = self.dashboard.close_perbarui_data_pelanggan_if_needed()
        if needs_update_reason:
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

        not_registered_reason = (
            self.dashboard.close_pelanggan_tidak_terdaftar_if_needed()
        )
        if not_registered_reason:
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

        return False

    def _check_max_kuota(
        self, penjualan: Penjualan, nik: str, started_at: str, stage: str
    ) -> bool:
        """Check for max kuota alert. Returns True if alert present."""
        if not penjualan.is_max_kuota_alert_present(timeout=self._MAX_KUOTA_TIMEOUT_MS):
            return False

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
        return True

    def _check_zero_stock_and_stop(
        self, penjualan: Penjualan, nik: str, started_at: str, stage: str
    ) -> None:
        alert_text = penjualan.get_zero_stock_alert_text(
            timeout=self._ZERO_STOCK_TIMEOUT_MS
        )
        if not alert_text:
            return

        if not penjualan.is_zero_stock_alert_text(alert_text):
            return

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
            message=f"Stopping account run for NIK {nik} because sellable stock is empty ({stage}).",
        )
        raise OutOfSellableStockError(reason)

    def _record_skip_and_cooldown(
        self, nik: str, started_at: str, skip_callback: Callable[[], None], message: str
    ) -> None:
        # Keep order and side effects consistent with original code.
        self.limiter.record_skip()
        skip_callback()
        log_print(message)
        self.page.wait_for_timeout(self._POST_SKIP_COOLDOWN_MS)

    def _solve_puzzle(self, nik: str) -> PuzzleSolveOutcome:
        """Solve CAPTCHA puzzle with a bounded retry on failed challenges."""
        max_attempts = 1 + self._MAX_PUZZLE_RETRIES
        retry_count = 0
        retry_process = ""

        for attempt_number in range(1, max_attempts + 1):
            helpers = Helpers(self.page)
            bg_src, piece_src = helpers.get_puzzle_image_sources()
            piece_path = helpers.save_puzzle_piece(nik)
            bg_path = helpers.save_puzzle_bg(nik)

            out_dir = Path(piece_path).parent
            result_path = out_dir / helpers.build_puzzle_output_name(nik, "result")

            log_print(f"Result path (abs): {result_path.resolve()}")

            solver = PuzzleSolver(
                gap_image_path=piece_path,
                bg_image_path=bg_path,
                output_image_path=str(result_path),
            )
            position = solver.discern_xy()
            log_print(f"The position of the slide is: {position}")

            success = solve_slider_with_puzzle(
                self.page,
                imgs={"background": Path(bg_path), "piece": Path(piece_path)},
                max_wait_success_ms=self._MAX_WAIT_SUCCESS_MS,
            )
            log_print(f"Slider solved on attempt {attempt_number}: {success}")

            if success:
                return PuzzleSolveOutcome(
                    solved=True,
                    attempts=attempt_number,
                    retry_count=retry_count,
                    retry_process=retry_process,
                )

            if attempt_number >= max_attempts:
                break

            modal_title = self.dashboard.detect_failed_puzzle_modal_if_needed(
                detect_timeout=self._PUZZLE_RETRY_MODAL_TIMEOUT_MS
            )
            if not modal_title:
                break

            retry_count += 1
            retry_process = self._PUZZLE_RETRY_PROCESS
            logger.bind(
                event="transaction.puzzle_retry",
                operator=self.config.email_user,
                nik=str(nik),
                retry_count=retry_count,
                retry_process=retry_process,
                modal_title=modal_title,
            ).info("Retrying failed puzzle solve")
            log_print(
                f"Retrying puzzle for NIK {nik} during {retry_process} "
                f"({retry_count}/{self._MAX_PUZZLE_RETRIES})."
            )
            helpers.wait_for_puzzle_refresh(
                previous_bg_src=bg_src,
                previous_piece_src=piece_src,
                timeout_ms=self._PUZZLE_REFRESH_TIMEOUT_MS,
            )

        return PuzzleSolveOutcome(
            solved=False,
            attempts=max(1, retry_count + 1),
            retry_count=retry_count,
            retry_process=retry_process,
        )

    def _build_puzzle_failure_reason(self, attempts: int) -> str:
        if attempts <= 1:
            return self._PUZZLE_SOLVE_FAILED_REASON
        return f"{self._PUZZLE_SOLVE_FAILED_REASON} after {attempts} attempts"

    def _handle_session_recovery(self) -> None:
        """Handle session recovery after error."""
        if self._check_if_logged_out():
            self._restore_logged_out_session()
            return

        try:
            self.dashboard.ensure_on_dashboard()
            return
        except Exception:
            self.page.goto(self.config.url_application)
            self.page.wait_for_load_state(self._LOAD_STATE)

        if self._check_if_logged_out():
            self._restore_logged_out_session()
            return

        self.dashboard.ensure_on_dashboard()

    def _restore_logged_out_session(self) -> None:
        """Restore a valid logged-in dashboard session."""
        self.page.goto(self.config.url_application)
        self.page.wait_for_load_state(self._LOAD_STATE)
        self.login.login(self.config.email_user, self.config.pin_user)
        self.page.wait_for_load_state(self._LOAD_STATE)
        self.dashboard.ensure_on_dashboard()

    def _check_if_logged_out(self) -> bool:
        """Check if user is logged out."""
        try:
            return (
                "login" in self.page.url
                or self.page.get_by_placeholder("Email").is_visible(
                    timeout=self._LOGGED_OUT_CHECK_TIMEOUT_MS
                )
                or self.page.get_by_role("button", name="MASUK").is_visible(
                    timeout=self._LOGGED_OUT_CHECK_TIMEOUT_MS
                )
            )
        except Exception:
            return False
