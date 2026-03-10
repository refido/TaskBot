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


class TransactionProcessor:
    """Handles processing of transactions with error handling and recovery."""

    _LOAD_STATE: str = "load"
    _MAX_KUOTA_TIMEOUT_MS: int = 1500
    _LOGGED_OUT_CHECK_TIMEOUT_MS: int = 800
    _POST_SKIP_COOLDOWN_MS: int = 300
    _MAX_WAIT_SUCCESS_MS: int = 3500

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

        try:
            self._wait_for_rate_limit()
            self._navigate_to_transaction(nik)

            if self._handle_pre_checks(nik, started_at):
                return

            penjualan = Penjualan(self.page)

            if self._check_max_kuota(
                penjualan, nik, started_at, stage="before cek pesanan"
            ):
                return

            penjualan.cek_pesanan()

            if self._check_max_kuota(
                penjualan, nik, started_at, stage="after cek pesanan"
            ):
                return

            cek_penjualan = CekPenjualan(self.page)
            cek_penjualan.proses_penjualan()

            puzzle_solved, puzzle_attempts = self._solve_puzzle()
            if not puzzle_solved:
                raise Exception("CAPTCHA solving failed")

            self._return_to_dashboard(cek_penjualan)

            self.reporter.complete(
                nik,
                started_at,
                url=self.page.url,
                puzzle_solved=puzzle_solved,
                puzzle_attempts=puzzle_attempts,
            )
            self.limiter.record_success()

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
        if self.dashboard.close_perbarui_data_pelanggan_if_needed():
            self._record_skip_and_cooldown(
                nik=nik,
                started_at=started_at,
                skip_callback=lambda: self.reporter.skip_needs_update(
                    nik, started_at, url=self.page.url
                ),
                message=f"Skipping NIK {nik} (needs data update).",
            )
            return True

        if self.dashboard.close_pelanggan_tidak_terdaftar_if_needed():
            self._record_skip_and_cooldown(
                nik=nik,
                started_at=started_at,
                skip_callback=lambda: self.reporter.skip_not_registered(
                    nik, started_at, url=self.page.url
                ),
                message=f"Skipping NIK {nik} (not registered).",
            )
            return True

        self.dashboard.select_jenis_pelanggan_if_needed()
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

    def _record_skip_and_cooldown(
        self, nik: str, started_at: str, skip_callback: Callable[[], None], message: str
    ) -> None:
        # Keep order and side effects consistent with original code.
        self.limiter.record_skip()
        skip_callback()
        log_print(message)
        self.page.wait_for_timeout(self._POST_SKIP_COOLDOWN_MS)

    def _solve_puzzle(self) -> tuple[bool, int]:
        """Solve CAPTCHA puzzle. Returns (success, attempts)."""
        helpers = Helpers(self.page)
        piece_path = helpers.save_puzzle_piece()
        bg_path = helpers.save_puzzle_bg()

        out_dir = Path(piece_path).parent
        stamp = Path(piece_path).stem.replace("_image_puzzle_piece", "")
        result_path = out_dir / f"{stamp}_image_puzzle_result.png"

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
        log_print(f"Slider solved: {success}")

        # Preserve original behavior: always return attempts=1.
        return success, 1

    def _handle_session_recovery(self) -> None:
        """Handle session recovery after error."""
        if self._check_if_logged_out():
            self.page.goto(self.config.url_application)
            self.login.login(self.config.email_user, self.config.pin_user)
            self.page.wait_for_load_state(self._LOAD_STATE)
            return

        try:
            self.dashboard.ensure_on_dashboard()
        except Exception:
            self.page.goto(self.config.url_application)

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
