import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from src.config import Config
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
    """Handles processing of transactions with proper error handling and recovery."""

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
    ):
        self.config = config
        self.page = page
        self.reporter = reporter
        self.limiter = limiter

        self.dashboard = Dashboard(page)
        self.login = Login(page)

    # Public methods (external API)
    def process_all_niks(self) -> None:
        """Process all NIKs from configuration."""
        for nik in self.config.nik:
            try:
                self.process_single_nik(nik)
            except Exception as exc:
                # Preserve current behavior: continue processing other NIKs.
                print(f"Unhandled error processing NIK {nik}: {exc}")
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

        except Exception as exc:
            print(f"Failed processing NIK {nik}: {exc}")
            self.reporter.error(
                nik,
                started_at,
                exc,
                url=self.page.url,
                puzzle_solved=puzzle_solved,
                puzzle_attempts=puzzle_attempts,
            )
            self._handle_session_recovery()

    # Private helpers (workflow steps)
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
        self, nik: str, started_at: str, skip_callback, message: str
    ) -> None:
        # Keep order and side effects consistent with original code.
        self.limiter.record_skip()
        skip_callback()
        print(message)
        self.page.wait_for_timeout(self._POST_SKIP_COOLDOWN_MS)

    def _solve_puzzle(self) -> tuple[bool, int]:
        """Solve CAPTCHA puzzle. Returns (success, attempts)."""
        helpers = Helpers(self.page)
        piece_path = helpers.save_puzzle_piece()
        bg_path = helpers.save_puzzle_bg()

        out_dir = Path(piece_path).parent
        stamp = Path(piece_path).stem.replace("_image_puzzle_piece", "")
        result_path = out_dir / f"{stamp}_image_puzzle_result.png"

        print(f"Result path (abs): {result_path.resolve()}")

        # Manual wait for human interaction
        # helpers.wait_for_human_interaction(timeout=5000)

        solver = PuzzleSolver(
            gap_image_path=piece_path,
            bg_image_path=bg_path,
            output_image_path=str(result_path),
        )
        position = solver.discern_xy()
        print(f"The position of the slide is: {position}")

        success = solve_slider_with_puzzle(
            self.page,
            imgs={"background": Path(bg_path), "piece": Path(piece_path)},
            max_wait_success_ms=self._MAX_WAIT_SUCCESS_MS,
        )
        print(f"Slider solved: {success}")

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


class BrowserSession:
    """Manages browser lifecycle and initialization."""

    def __init__(self, config: Config):
        self.config = config
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    # Public methods (external API)
    def __enter__(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.firefox.launch(headless=True)
        # self.browser = self.playwright.firefox.launch(headless=False, slow_mo=50)
        # self.browser = self.playwright.firefox.launch(headless=False)
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Best-effort cleanup; do not raise from cleanup.
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass

        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass

        try:
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass

    def initialize_session(self) -> None:
        """Initialize browser session with login."""
        if not self.page:
            # Defensive: should never happen when used as a context manager.
            raise RuntimeError(
                "BrowserSession.page is not initialized. Use BrowserSession as a context manager."
            )

        self.page.goto(self.config.url_application)

        login = Login(self.page)
        login.login(self.config.email_user, self.config.pin_user)
        self.page.wait_for_load_state("load")

        dashboard = Dashboard(self.page)
        profile_name = dashboard.get_profile_name()
        dashboard.assert_profile_name_is(profile_name)
        dashboard.get_current_stock()


class ReportStructurePrinter:
    """Prints report folder structure for an operator."""

    def __init__(self, reports_root: Path = Path("reports")):
        self.reports_root = reports_root

    # Public methods
    def print_for_operator(self, email_user: str) -> None:
        safe_operator = TransactionReporter._sanitize_folder_name(email_user)
        operator_dir = self.reports_root / safe_operator

        if not operator_dir.exists():
            print(f"No reports found for operator: {email_user}")
            return

        print(f"\nReport Structure for {email_user}:")
        print(f"{'=' * 60}")
        print(f"Root: {operator_dir}")

        date_folders = sorted([d for d in operator_dir.iterdir() if d.is_dir()])

        for date_folder in date_folders:
            if date_folder.name == "operator_summary.json":
                continue

            print(f"\n  📅 {date_folder.name}/")

            run_folders = sorted([r for r in date_folder.iterdir() if r.is_dir()])
            for run_folder in run_folders:
                print(f"    🏃 {run_folder.name}/")

                key_files = ["items.csv", "analytics.json", "run_meta.json"]
                for file_name in key_files:
                    file_path = run_folder / file_name
                    if file_path.exists():
                        size = file_path.stat().st_size
                        print(f"      📄 {file_name} ({size:,} bytes)")

        self._print_operator_summary(operator_dir)

        print(f"{'=' * 60}\n")

    # Private helpers
    def _print_operator_summary(self, operator_dir: Path) -> None:
        summary_path = operator_dir / "operator_summary.json"
        if not summary_path.exists():
            return

        print("\n  📊 operator_summary.json")
        try:
            with summary_path.open("r", encoding="utf-8") as file_handle:
                summary = json.load(file_handle)
                # Preserve original output/keys (even though label wording is a bit off).
                print(
                    f"     Total Runs: {summary['aggregated_stats']['total_transactions']}"
                )
                print(
                    f"     Completed: {summary['aggregated_stats']['total_completed']}"
                )
                print(
                    f"     Success Rate: {summary['aggregated_stats']['success_rate_percent']}%"
                )
        except Exception as exc:
            print(f"     Error reading summary: {exc}")


def print_report_structure(email_user: str):
    """
    Print the report folder structure for an operator.

    Args:
        email_user: Operator email to check
    """
    ReportStructurePrinter().print_for_operator(email_user)


def run_account(config: Config) -> tuple[str, bool]:
    """
    Run a full transaction workflow for one account.

    Each call creates its own BrowserSession (and sync_playwright) so it can be
    executed safely inside a thread.
    """
    reporter = TransactionReporter(operator=config.email_user)
    limiter = SkipRateLimiter(
        max_skips=10, window_seconds=60, min_cooldown=60, jitter_seconds=5
    )

    is_successful = True

    print(f"[{config.email_user}] Starting run with {len(config.nik)} NIK(s).")

    try:
        with BrowserSession(config) as session:
            session.initialize_session()
            processor = TransactionProcessor(config, session.page, reporter, limiter)
            processor.process_all_niks()
    except Exception as exc:
        is_successful = False
        print(f"[{config.email_user}] Fatal error: {exc}")
    finally:
        reporter.write_files()
        reporter.print_summary()
        print_report_structure(config.email_user)

    return config.email_user, is_successful


def main():
    """Main entry point."""
    config = Config()
    account_configs = config.account_configs()

    if not account_configs:
        raise ValueError(
            "No account configuration found. Set EMAIL/PIN/NIK or EMAIL_1/PIN_1/NIK_1."
        )

    if len(account_configs) == 1:
        run_account(account_configs[0])
        return

    print(f"Running {len(account_configs)} accounts concurrently using threads.")

    with ThreadPoolExecutor(
        max_workers=len(account_configs), thread_name_prefix="taskbot-account"
    ) as executor:
        future_to_email = {
            executor.submit(run_account, account_config): account_config.email_user
            for account_config in account_configs
        }

        for future in as_completed(future_to_email):
            email = future_to_email[future]
            try:
                _, is_successful = future.result()
                status = "completed" if is_successful else "completed with errors"
                print(f"[{email}] Thread {status}.")
            except Exception as exc:
                print(f"[{email}] Thread crashed unexpectedly: {exc}")


if __name__ == "__main__":
    main()
