import json
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
    """Handles processing of transactions with proper error handling and recovery"""

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

    def process_all_niks(self) -> None:
        """Process all NIKs from configuration"""
        for nik in self.config.nik:
            try:
                self.process_single_nik(nik)
            except Exception as e:
                print(f"Unhandled error processing NIK {nik}: {e}")
                self._handle_session_recovery()

    def process_single_nik(self, nik: str) -> None:
        """Process a single NIK transaction"""
        started_at = self.reporter.start_item(nik)
        puzzle_solved = None
        puzzle_attempts = 0

        try:
            # Check rate limiting
            self.limiter.wait_if_needed(self.page)

            # Navigate to transaction page
            self.dashboard.catat_penjualan(nik)
            self.page.wait_for_load_state("load")

            # Handle pre-checks
            if self._handle_pre_checks(nik, started_at):
                return

            # Process transaction
            penjualan = Penjualan(self.page)

            # Check for max kuota before and after cek pesanan
            if self._check_max_kuota(penjualan, nik, started_at, "before cek pesanan"):
                return

            penjualan.cek_pesanan()

            if self._check_max_kuota(penjualan, nik, started_at, "after cek pesanan"):
                return

            # Process order confirmation
            cek_penjualan = CekPenjualan(self.page)
            cek_penjualan.proses_penjualan()

            # Solve puzzle
            puzzle_solved, puzzle_attempts = self._solve_puzzle()

            if not puzzle_solved:
                raise Exception("CAPTCHA solving failed")

            # Return to dashboard
            cek_penjualan.kembali_ke_dashboard()
            self.page.wait_for_load_state("load")
            self.dashboard.get_current_stock()

            # Record success
            self.reporter.complete(
                nik,
                started_at,
                url=self.page.url,
                puzzle_solved=puzzle_solved,
                puzzle_attempts=puzzle_attempts,
            )

        except Exception as e:
            print(f"Failed processing NIK {nik}: {e}")
            self.reporter.error(
                nik,
                started_at,
                e,
                url=self.page.url,
                puzzle_solved=puzzle_solved,
                puzzle_attempts=puzzle_attempts,
            )
            self._handle_session_recovery()

    def _handle_pre_checks(self, nik: str, started_at: str) -> bool:
        """Handle pre-transaction checks. Returns True if NIK should be skipped"""
        # Check for data update needed
        if self.dashboard.close_perbarui_data_pelanggan_if_needed():
            self.limiter.record_skip()
            self.reporter.skip_needs_update(nik, started_at, url=self.page.url)
            print(f"Skipping NIK {nik} (needs data update).")
            self.page.wait_for_timeout(300)
            return True

        # Check if not registered
        if self.dashboard.close_pelanggan_tidak_terdaftar_if_needed():
            self.limiter.record_skip()
            self.reporter.skip_not_registered(nik, started_at, url=self.page.url)
            print(f"Skipping NIK {nik} (not registered).")
            self.page.wait_for_timeout(300)
            return True

        # Select jenis pelanggan if needed
        self.dashboard.select_jenis_pelanggan_if_needed()
        return False

    def _check_max_kuota(
        self, penjualan: Penjualan, nik: str, started_at: str, stage: str
    ) -> bool:
        """Check for max kuota alert. Returns True if alert present"""
        if penjualan.is_max_kuota_alert_present(timeout=1500):
            try:
                penjualan.ganti_pelanggan()
            except Exception:
                pass

            self.limiter.record_skip()
            self.reporter.skip_max_kuota(
                nik, started_at, url=self.page.url, reason=f"Max kuota {stage}"
            )
            print(f"Skipping NIK {nik} (max kuota {stage}).")
            self.page.wait_for_timeout(300)
            return True

        return False

    def _solve_puzzle(self) -> tuple[bool, int]:
        """Solve CAPTCHA puzzle. Returns (success, attempts)"""
        helpers = Helpers(self.page)
        piece_path = helpers.save_puzzle_piece()
        bg_path = helpers.save_puzzle_bg()

        # Generate result path
        out_dir = Path(piece_path).parent
        stamp = Path(piece_path).stem.replace("_image_puzzle_piece", "")
        result_path = out_dir / f"{stamp}_image_puzzle_result.png"

        print(f"Result path (abs): {result_path.resolve()}")

        # Solve puzzle
        solver = PuzzleSolver(
            gap_image_path=piece_path,
            bg_image_path=bg_path,
            output_image_path=str(result_path),
        )
        position = solver.discern_xy()
        print(f"The position of the slide is: {position}")

        # Execute slider
        success = solve_slider_with_puzzle(
            self.page,
            imgs={"background": Path(bg_path), "piece": Path(piece_path)},
            max_wait_success_ms=3500,
        )
        print(f"Slider solved: {success}")

        return success, 1

    def _handle_session_recovery(self) -> None:
        """Handle session recovery after error"""
        is_logged_out = self._check_if_logged_out()

        if is_logged_out:
            # Re-login if logged out
            self.page.goto(self.config.url_application)
            self.login.login(self.config.email_user, self.config.pin_user)
            self.page.wait_for_load_state("load")
        else:
            # Try to recover to dashboard
            try:
                self.dashboard.ensure_on_dashboard()
            except Exception:
                self.page.goto(self.config.url_application)

    def _check_if_logged_out(self) -> bool:
        """Check if user is logged out"""
        try:
            return (
                "login" in self.page.url
                or self.page.get_by_placeholder("Email").is_visible(timeout=800)
                or self.page.get_by_role("button", name="MASUK").is_visible(timeout=800)
            )
        except Exception:
            return False


class BrowserSession:
    """Manages browser lifecycle and initialization"""

    def __init__(self, config: Config):
        self.config = config
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    def __enter__(self):
        """Enter context manager"""
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.firefox.launch(headless=False)
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager"""
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def initialize_session(self) -> None:
        """Initialize browser session with login"""
        self.page.goto(self.config.url_application)

        login = Login(self.page)
        login.login(self.config.email_user, self.config.pin_user)
        self.page.wait_for_load_state("load")

        dashboard = Dashboard(self.page)
        profile_name = dashboard.get_profile_name()
        dashboard.assert_profile_name_is(profile_name)
        dashboard.get_current_stock()


def print_report_structure(email_user: str):
    """
    Print the report folder structure for an operator.

    Args:
        email_user: Operator email to check
    """
    from src.web.reporter import TransactionReporter

    # Get sanitized folder name
    safe_operator = TransactionReporter._sanitize_folder_name(email_user)
    operator_dir = Path("reports") / safe_operator

    if not operator_dir.exists():
        print(f"No reports found for operator: {email_user}")
        return

    print(f"\nReport Structure for {email_user}:")
    print(f"{'=' * 60}")
    print(f"Root: {operator_dir}")

    # List all date folders
    date_folders = sorted([d for d in operator_dir.iterdir() if d.is_dir()])

    for date_folder in date_folders:
        if date_folder.name == "operator_summary.json":
            continue

        print(f"\n  📅 {date_folder.name}/")

        # List all run folders
        run_folders = sorted([r for r in date_folder.iterdir() if r.is_dir()])

        for run_folder in run_folders:
            print(f"    🏃 {run_folder.name}/")

            # List key files
            key_files = ["items.csv", "analytics.json", "run_meta.json"]
            for file in key_files:
                file_path = run_folder / file
                if file_path.exists():
                    size = file_path.stat().st_size
                    print(f"      📄 {file} ({size:,} bytes)")

    # Show operator summary if exists
    summary_path = operator_dir / "operator_summary.json"
    if summary_path.exists():
        print("\n  📊 operator_summary.json")
        try:
            with summary_path.open("r") as f:
                summary = json.load(f)
                print(
                    f"     Total Runs: {summary['aggregated_stats']['total_transactions']}"
                )
                print(
                    f"     Completed: {summary['aggregated_stats']['total_completed']}"
                )
                print(
                    f"     Success Rate: {summary['aggregated_stats']['success_rate_percent']}%"
                )
        except Exception as e:
            print(f"     Error reading summary: {e}")

    print(f"{'=' * 60}\n")


def main():
    """Main entry point"""
    config = Config()
    reporter = TransactionReporter(operator=config.email_user)
    limiter = SkipRateLimiter(
        max_skips=10, window_seconds=60, min_cooldown=60, jitter_seconds=5
    )

    with BrowserSession(config) as session:
        session.initialize_session()

        processor = TransactionProcessor(config, session.page, reporter, limiter)
        processor.process_all_niks()

    # Generate final report
    reporter.write_files()
    reporter.print_summary()

    # Print folder structure for easy navigation
    print_report_structure(config.email_user)


if __name__ == "__main__":
    main()
