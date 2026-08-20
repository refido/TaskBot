from functools import partial
from pathlib import Path

from playwright.sync_api import Page

from src.application.models.customer_workflow import (
    CustomerUpdateFailedError,
    CustomerUpdateLoopError,
    PrecheckAction,
)
from src.application.services.puzzle_service import PuzzleService, PuzzleSolveOutcome
from src.application.services.session_recovery import SessionRecoveryService
from src.application.services.transaction_prechecks import (
    TransactionPrechecksService,
)
from src.config import Config
from src.infrastructure.browser.page_objects.cek_penjualan_page import CekPenjualan
from src.infrastructure.browser.page_objects.dashboard_page import Dashboard
from src.infrastructure.browser.page_objects.login_page import Login
from src.infrastructure.browser.page_objects.penjualan_page import Penjualan
from src.logging_utils import log_print, logger
from src.pipelines.solve_slider import solve_slider_with_puzzle
from src.privacy import artifact_nik
from src.vision.puzzle_solver import PuzzleSolver
from src.web.helpers import Helpers
from src.web.rate_limiter import SkipRateLimiter
from src.web.reporter import TransactionReporter
from src.web.session_state import SessionExpiredError, is_login_page


class OutOfSellableStockError(RuntimeError):
    """Raised when the site reports that sellable stock is empty."""

    def __init__(self, message: str, *, reported: bool = False) -> None:
        super().__init__(message)
        self.reported = reported


class PuzzleSolveFailedError(RuntimeError):
    """Raised when the puzzle challenge could not be solved."""


class TransactionProcessor:
    """Handles processing of transactions with error handling and recovery."""

    _LOAD_STATE: str = "load"
    _MAX_KUOTA_TIMEOUT_MS: int = 1500
    _ZERO_STOCK_TIMEOUT_MS: int = 1500
    _LOGGED_OUT_CHECK_TIMEOUT_MS: int = 800
    _POST_SKIP_COOLDOWN_MS: int = 300
    _MAX_WAIT_SUCCESS_MS: int = 3500
    _MAX_PUZZLE_ATTEMPTS: int = 5
    _PUZZLE_RETRY_MODAL_TIMEOUT_MS: int = 2500
    _PUZZLE_REFRESH_TIMEOUT_MS: int = 5000
    _PUZZLE_RETRY_PROCESS: str = "proses_penjualan"
    _PUZZLE_SOLVE_FAILED_REASON: str = "CAPTCHA solving failed"
    _SESSION_PROBE_INTERVAL_MS: int = 10 * 60 * 1000
    _MAX_SESSION_RECOVERY_RETRIES_PER_NIK: int = 1
    _MAX_GENERAL_ERROR_RETRIES_PER_NIK: int = 2
    _MAX_UPDATE_RECHECKS_PER_NIK: int = 1
    _RETRY_PROCESS: str = "process_single_nik"

    def __init__(
        self,
        config: Config,
        page: Page,
        reporter: TransactionReporter,
        limiter: SkipRateLimiter,
    ) -> None:
        self.config = config
        self.operator_id = getattr(config, "operator_id", "operator_01")
        self.page = page
        self.reporter = reporter
        self.limiter = limiter

        self.dashboard = Dashboard(page)
        self.login = Login(page)
        self._precheck_service: TransactionPrechecksService | None = None
        self._puzzle_service: PuzzleService | None = None
        self._session_recovery_service: SessionRecoveryService | None = None

    def process_all_niks(self) -> None:
        """Process all NIKs from configuration."""
        for nik in self.config.nik:
            try:
                self.process_single_nik(nik)
            except OutOfSellableStockError as exc:
                logger.bind(
                    event="transaction.out_of_stock",
                    operator_id=self.operator_id,
                    nik=str(nik),
                ).warning(str(exc))
                break
            except Exception:  # noqa: BLE001 - isolate failures between configured NIKs.
                # Preserve current behavior: continue processing other NIKs.
                logger.bind(
                    event="transaction.unhandled_error",
                    operator_id=self.operator_id,
                    nik=str(nik),
                ).exception("Unhandled error while processing NIK")
                self._handle_session_recovery()

    def process_single_nik(self, nik: str) -> None:
        """Process a single NIK transaction."""
        started_at = self.reporter.start_item(nik)
        session_retries_used = 0
        general_error_retries_used = 0
        update_rechecks_used = 0
        attempt_number = 1

        self._log_transaction_stage(nik, "started", attempt_number=attempt_number)

        while True:
            puzzle_solved: bool | None = None
            puzzle_attempts = 0
            puzzle_retry_count = 0
            puzzle_retry_process = ""

            try:
                self._log_transaction_stage(
                    nik,
                    "attempt_started",
                    attempt_number=attempt_number,
                    update_rechecks_used=update_rechecks_used,
                )
                self._probe_session_if_due(
                    reason=f"before processing NIK {nik}",
                    force=attempt_number > 1,
                )
                self._wait_for_rate_limit()
                self._probe_session_if_due(
                    reason=f"after wait before NIK {nik} navigation"
                )
                navigation_outcome = self._navigate_to_transaction(nik)
                if navigation_outcome == "registration_request_limited":
                    self._log_transaction_stage(
                        nik,
                        "customer_precheck_interrupted_navigation",
                        attempt_number=attempt_number,
                        blocker="registration_request_limited",
                    )
                else:
                    self._log_transaction_stage(
                        nik, "nik_submitted", attempt_number=attempt_number
                    )

                precheck_action = self._handle_pre_checks(
                    nik,
                    started_at,
                    allow_customer_update=(
                        update_rechecks_used < self._MAX_UPDATE_RECHECKS_PER_NIK
                    ),
                )
                self._log_transaction_stage(
                    nik,
                    "customer_prechecks_resolved",
                    attempt_number=attempt_number,
                    action=precheck_action.value,
                )
                if precheck_action is PrecheckAction.SKIP:
                    return
                if precheck_action is PrecheckAction.RESTART_AFTER_UPDATE:
                    if update_rechecks_used >= self._MAX_UPDATE_RECHECKS_PER_NIK:
                        raise CustomerUpdateLoopError(
                            "Customer update requested again after the allowed restart"
                        )
                    update_rechecks_used += 1
                    self._record_workflow_event(
                        nik,
                        "same_nik_restart_after_update",
                        reason="Customer update succeeded; restarting the same NIK",
                    )
                    logger.bind(
                        event="customer.update.restart_same_nik",
                        operator_id=self.operator_id,
                        nik=str(nik),
                        update_restart_count=update_rechecks_used,
                    ).info("Restarting the same NIK after customer update")
                    self._wait_before_update_action("restart_same_nik")
                    continue

                penjualan = Penjualan(self.page)

                self._probe_session_if_due(reason=f"before cek pesanan for NIK {nik}")
                if self._check_transaction_blocker(
                    penjualan, nik, started_at, stage="before cek pesanan"
                ):
                    return

                penjualan.cek_pesanan()
                self._log_transaction_stage(
                    nik, "order_checked", attempt_number=attempt_number
                )

                self._probe_session_if_due(reason=f"after cek pesanan for NIK {nik}")
                if self._check_transaction_blocker(
                    penjualan, nik, started_at, stage="after cek pesanan"
                ):
                    return

                cek_penjualan = CekPenjualan(self.page)
                cek_penjualan.proses_penjualan()
                self._log_transaction_stage(
                    nik, "sale_submitted", attempt_number=attempt_number
                )

                puzzle_outcome = self._solve_puzzle(nik)
                puzzle_solved = puzzle_outcome.solved
                puzzle_attempts = puzzle_outcome.attempts
                puzzle_retry_count = puzzle_outcome.retry_count
                puzzle_retry_process = puzzle_outcome.retry_process
                self._log_transaction_stage(
                    nik,
                    "puzzle_finished",
                    attempt_number=attempt_number,
                    puzzle_solved=puzzle_solved,
                    puzzle_attempts=puzzle_attempts,
                    puzzle_retry_count=puzzle_retry_count,
                )
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
                self._log_transaction_stage(
                    nik, "completed", attempt_number=attempt_number
                )
                return

            except OutOfSellableStockError as exc:
                if not exc.reported:
                    self.reporter.skip_out_of_stock(
                        nik,
                        started_at,
                        url=self.page.url,
                        reason=str(exc),
                    )
                raise
            except CustomerUpdateFailedError as exc:
                logger.bind(
                    event="customer.update.failed",
                    operator_id=self.operator_id,
                    nik=str(nik),
                    reason=str(exc),
                ).error("Automatic customer update failed")
                self._record_workflow_event(
                    nik,
                    "customer_update_failed",
                    reason=str(exc),
                )
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
                self._capture_failure_artifact(nik, "customer_update_failed")
                self._handle_session_recovery()
                return
            except PuzzleSolveFailedError as exc:
                logger.bind(
                    event="transaction.puzzle_failed",
                    operator_id=self.operator_id,
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
                return
            except SessionExpiredError as exc:
                logger.bind(
                    event="transaction.session_expired",
                    operator_id=self.operator_id,
                    nik=str(nik),
                    attempt_number=attempt_number,
                    retries_used=session_retries_used,
                    retry_limit=self._MAX_SESSION_RECOVERY_RETRIES_PER_NIK,
                ).warning(str(exc))

                if session_retries_used >= self._MAX_SESSION_RECOVERY_RETRIES_PER_NIK:
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
                    return

                session_retries_used += 1
                self._record_retry(
                    nik=nik,
                    exc=exc,
                    trigger="session_expired",
                    attempt_number=attempt_number,
                    retry_number=session_retries_used,
                    max_retries=self._MAX_SESSION_RECOVERY_RETRIES_PER_NIK,
                )
                self._handle_session_recovery()
                attempt_number += 1
                continue
            except Exception as exc:  # noqa: BLE001 - bounded general retry boundary.
                if general_error_retries_used < self._MAX_GENERAL_ERROR_RETRIES_PER_NIK:
                    general_error_retries_used += 1
                    logger.bind(
                        event="transaction.retrying_after_general_error",
                        operator_id=self.operator_id,
                        nik=str(nik),
                        attempt_number=attempt_number,
                        retry_number=general_error_retries_used,
                        retry_limit=self._MAX_GENERAL_ERROR_RETRIES_PER_NIK,
                    ).warning(str(exc))
                    self._record_retry(
                        nik=nik,
                        exc=exc,
                        trigger="general_error",
                        attempt_number=attempt_number,
                        retry_number=general_error_retries_used,
                        max_retries=self._MAX_GENERAL_ERROR_RETRIES_PER_NIK,
                    )
                    self._handle_session_recovery()
                    attempt_number += 1
                    continue

                logger.bind(
                    event="transaction.failed",
                    operator_id=self.operator_id,
                    nik=str(nik),
                    attempt_number=attempt_number,
                    retries_used=general_error_retries_used,
                    retry_limit=self._MAX_GENERAL_ERROR_RETRIES_PER_NIK,
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
                return

    def _record_retry(
        self,
        *,
        nik: str,
        exc: Exception,
        trigger: str,
        attempt_number: int,
        retry_number: int,
        max_retries: int,
    ) -> None:
        record_retry = getattr(self.reporter, "record_retry", None)
        if record_retry is None:
            return

        record_retry(
            nik,
            process=self._RETRY_PROCESS,
            trigger=trigger,
            attempt_number=attempt_number,
            retry_number=retry_number,
            max_retries=max_retries,
            exc=exc,
            url=self.page.url,
        )

    def _wait_for_rate_limit(self) -> None:
        self.limiter.wait_if_needed(self.page)

    def _wait_before_update_action(self, action: str) -> None:
        """Pace update-related actions without affecting skip pressure."""
        wait = getattr(self.limiter, "wait_before_update_action", None)
        if callable(wait):
            wait(self.page, action)

    def _capture_failure_artifact(self, nik: str, label: str) -> Path | None:
        """Capture a best-effort screenshot inside the shared run tree."""
        run_dir = getattr(getattr(self.config, "run_context", None), "run_dir", None)
        if run_dir is None:
            return None
        output_dir = Path(run_dir) / "artifacts" / "screenshots" / self.operator_id
        output_path = output_dir / f"{artifact_nik(nik)}_{label}.png"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(output_path), full_page=True)
        except Exception:  # noqa: BLE001 - diagnostics must not alter workflow handling.
            logger.bind(
                event="artifact.screenshot.failed",
                operator_id=self.operator_id,
                nik=nik,
                artifact_path=str(output_path),
            ).exception("Failed to capture workflow failure screenshot")
            return None
        logger.bind(
            event="artifact.screenshot.saved",
            operator_id=self.operator_id,
            nik=nik,
            artifact_path=str(output_path),
        ).info("Workflow failure screenshot saved")
        return output_path

    def _navigate_to_transaction(self, nik: str) -> str | None:
        outcome = self.dashboard.catat_penjualan(nik)

        if outcome == "zero_stock":
            raise OutOfSellableStockError(
                "Stok Tabung Kosong; transaction processing stopped."
            )
        return outcome

    def _return_to_dashboard(self, cek_penjualan: CekPenjualan) -> None:
        cek_penjualan.kembali_ke_dashboard()
        self.page.wait_for_load_state(self._LOAD_STATE)
        self.dashboard.get_current_stock()

    def _handle_pre_checks(
        self,
        nik: str,
        started_at: str,
        *,
        allow_customer_update: bool,
    ) -> PrecheckAction:
        return self._get_precheck_service().handle_pre_checks(
            nik,
            started_at,
            allow_customer_update=allow_customer_update,
        )

    def _record_workflow_event(self, nik: str, event: str, *, reason: str = "") -> None:
        callback = getattr(self.reporter, "record_workflow_event", None)
        if callback is not None:
            callback(
                nik,
                event=event,
                stage="transaction",
                url=self.page.url,
                reason=reason,
            )

    def _log_transaction_stage(
        self, nik: str, stage: str, *, attempt_number: int, **fields
    ) -> None:
        logger.bind(
            event=f"transaction.stage.{stage}",
            operator_id=self.operator_id,
            nik=str(nik),
            stage=stage,
            attempt_number=attempt_number,
            **fields,
        ).info(f"Transaction stage reached: {stage}")

    def _check_transaction_blocker(
        self, penjualan: Penjualan, nik: str, started_at: str, stage: str
    ) -> bool:
        outcome = self._get_precheck_service().check_transaction_blocker(
            penjualan,
            nik,
            started_at,
            stage,
        )
        if outcome.stop_reason:
            raise OutOfSellableStockError(outcome.stop_reason, reported=True)
        return outcome.should_skip

    def _solve_puzzle(self, nik: str) -> PuzzleSolveOutcome:
        return self._get_puzzle_service().solve(nik)

    def _build_puzzle_failure_reason(self, attempts: int) -> str:
        if attempts <= 1:
            return self._PUZZLE_SOLVE_FAILED_REASON
        return f"{self._PUZZLE_SOLVE_FAILED_REASON} after {attempts} attempts"

    def _handle_session_recovery(self) -> None:
        self._get_session_recovery_service().handle_session_recovery()

    def _restore_logged_out_session(self) -> None:
        self._get_session_recovery_service().restore_logged_out_session()

    def _check_if_logged_out(self) -> bool:
        return self._get_session_recovery_service().check_if_logged_out()

    def _probe_session_if_due(self, *, reason: str, force: bool = False) -> None:
        self._get_session_recovery_service().probe_if_due(
            reason=reason,
            force=force,
        )

    def _reset_session_probe(self) -> None:
        self._get_session_recovery_service().reset_probe()

    def _get_precheck_service(self) -> TransactionPrechecksService:
        service = getattr(self, "_precheck_service", None)
        if service is None:
            service = TransactionPrechecksService(
                page=self.page,
                dashboard=self.dashboard,
                reporter=self.reporter,
                limiter=self.limiter,
                post_skip_cooldown_ms=self._POST_SKIP_COOLDOWN_MS,
                max_kuota_timeout_ms=self._MAX_KUOTA_TIMEOUT_MS,
                zero_stock_timeout_ms=self._ZERO_STOCK_TIMEOUT_MS,
                log_func=log_print,
            )
            self._precheck_service = service
        return service

    def _get_puzzle_service(self) -> PuzzleService:
        service = getattr(self, "_puzzle_service", None)
        if service is None:
            helpers_factory = Helpers
            slider_solver = solve_slider_with_puzzle
            run_dir = getattr(getattr(self.config, "run_context", None), "run_dir", None)
            if run_dir is not None:
                artifact_root = Path(run_dir) / "artifacts"
                helpers_factory = partial(
                    Helpers,
                    output_dir=(
                        artifact_root / "screenshots" / self.operator_id
                    ),
                )
                slider_solver = partial(
                    solve_slider_with_puzzle,
                    debug_root=str(
                        artifact_root / "traces" / self.operator_id
                    ),
                    run_id=str(
                        getattr(self.config.run_context, "run_id", "")
                    ),
                    operator_id=self.operator_id,
                )
            service = PuzzleService(
                page=self.page,
                dashboard=self.dashboard,
                operator_email=self.operator_id,
                helpers_factory=helpers_factory,
                puzzle_solver_factory=PuzzleSolver,
                slider_solver=slider_solver,
                max_attempts=self._MAX_PUZZLE_ATTEMPTS,
                max_wait_success_ms=self._MAX_WAIT_SUCCESS_MS,
                retry_modal_timeout_ms=self._PUZZLE_RETRY_MODAL_TIMEOUT_MS,
                refresh_timeout_ms=self._PUZZLE_REFRESH_TIMEOUT_MS,
                retry_process=self._PUZZLE_RETRY_PROCESS,
                log_func=log_print,
            )
            self._puzzle_service = service
        return service

    def _get_session_recovery_service(self) -> SessionRecoveryService:
        service = getattr(self, "_session_recovery_service", None)
        if service is None:
            service = SessionRecoveryService(
                page=self.page,
                config=self.config,
                dashboard=self.dashboard,
                login=self.login,
                load_state=self._LOAD_STATE,
                logged_out_check_timeout_ms=self._LOGGED_OUT_CHECK_TIMEOUT_MS,
                session_probe_interval_ms=self._SESSION_PROBE_INTERVAL_MS,
                login_page_detector=is_login_page,
            )
            self._session_recovery_service = service
        return service
