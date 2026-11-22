from functools import partial
from pathlib import Path

from playwright.sync_api import Page

from src.application.models.customer_workflow import (
    CustomerUpdateFailedError,
    CustomerUpdateLoopError,
    PrecheckAction,
)
from src.application.models.transaction_outcome import (
    TransactionConfirmationError,
    TransactionOutcome,
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
from src.infrastructure.browser.page_objects.penjualan_page import (
    CustomerInformation,
    Penjualan,
)
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
    _PRE_CEK_PESANAN_BLOCKER_TIMEOUT_MS: int = 300
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
        # Execution-local invariant: a confirmed NIK must never be submitted again.
        self._confirmed_success_niks: set[str] = set()
        self._unconfirmed_transaction_niks: set[str] = set()

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
        if (
            str(nik) in self._confirmed_success_niks
            or str(nik) in self._unconfirmed_transaction_niks
        ):
            return
        started_at = self.reporter.start_item(nik)
        session_retries_used = 0
        general_error_retries_used = 0
        update_rechecks_used = 0
        attempt_number = 1
        customer_information = CustomerInformation()

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
                if precheck_action is PrecheckAction.SKIP_REQUIRES_RECOVERY:
                    break
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
                customer_information = self._merge_customer_information(
                    customer_information,
                    self._read_customer_information(penjualan),
                )

                self._probe_session_if_due(reason=f"before cek pesanan for NIK {nik}")
                if self._check_transaction_blocker(
                    penjualan,
                    nik,
                    started_at,
                    stage="before cek pesanan",
                    timeout_ms=self._PRE_CEK_PESANAN_BLOCKER_TIMEOUT_MS,
                    customer_information=customer_information,
                ):
                    return

                penjualan.cek_pesanan()
                self._log_transaction_stage(
                    nik, "order_checked", attempt_number=attempt_number
                )

                self._probe_session_if_due(reason=f"after cek pesanan for NIK {nik}")
                if self._check_transaction_blocker(
                    penjualan,
                    nik,
                    started_at,
                    stage="after cek pesanan",
                    timeout_ms=max(
                        self._MAX_KUOTA_TIMEOUT_MS, self._ZERO_STOCK_TIMEOUT_MS
                    ),
                    customer_information=customer_information,
                ):
                    return

                cek_penjualan = CekPenjualan(self.page)
                cek_penjualan.proses_penjualan()
                self._log_transaction_stage(
                    nik, "sale_submitted", attempt_number=attempt_number
                )

                puzzle_outcome = self._solve_puzzle(nik)
                puzzle_solved = puzzle_outcome.solved
                if puzzle_solved:
                    # CAPTCHA completion is not sale confirmation. Observe the result
                    # outside the retry boundary so uncertainty cannot resubmit it.
                    break
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

            except OutOfSellableStockError as exc:
                if not exc.reported:
                    self.reporter.skip_out_of_stock(
                        nik,
                        started_at,
                        url=self.page.url,
                        reason=str(exc),
                        nama_pengguna=customer_information.nama_pengguna,
                        jenis_pengguna=customer_information.jenis_pengguna,
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
                    nama_pengguna=customer_information.nama_pengguna,
                    jenis_pengguna=customer_information.jenis_pengguna,
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
                    nama_pengguna=customer_information.nama_pengguna,
                    jenis_pengguna=customer_information.jenis_pengguna,
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
                        nama_pengguna=customer_information.nama_pengguna,
                        jenis_pengguna=customer_information.jenis_pengguna,
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
                    nama_pengguna=customer_information.nama_pengguna,
                    jenis_pengguna=customer_information.jenis_pengguna,
                )
                self._handle_session_recovery()
                return

        if puzzle_solved:
            self._unconfirmed_transaction_niks.add(str(nik))
            try:
                outcome = cek_penjualan.wait_for_transaction_outcome()
                if not isinstance(outcome, TransactionOutcome):
                    raise TransactionConfirmationError("Invalid transaction outcome")
            except Exception as exc:  # Observation failure must be reported, never retried.
                self._record_unconfirmed_transaction(
                    nik, started_at,
                    TransactionOutcome("unknown", "confirmation_error"),
                    puzzle_outcome, customer_information, observation_error=exc,
                )
                return

            if not outcome.success_confirmed:
                if outcome.status == "completed":
                    outcome = TransactionOutcome("unknown", "missing_success_evidence")
                self._record_unconfirmed_transaction(
                    nik, started_at, outcome, puzzle_outcome, customer_information
                )
                return

            self._unconfirmed_transaction_niks.discard(str(nik))
            self._confirmed_success_niks.add(str(nik))
            # Success is terminal even when any post-transaction operation fails.
            try:
                self._log_transaction_outcome(nik, outcome)
                self._log_transaction_stage(
                    nik,
                    "puzzle_finished",
                    attempt_number=attempt_number,
                    puzzle_solved=True,
                    puzzle_attempts=puzzle_outcome.attempts,
                    puzzle_retry_count=puzzle_outcome.retry_count,
                )
                try:
                    self._return_to_dashboard(cek_penjualan)
                except Exception as exc:  # noqa: BLE001 - still report the confirmed sale.
                    self._handle_post_processing_failure(nik, exc)

                self.reporter.complete(
                    nik,
                    started_at,
                    url=self.page.url,
                    puzzle_solved=True,
                    puzzle_attempts=puzzle_outcome.attempts,
                    puzzle_retry_count=puzzle_outcome.retry_count,
                    puzzle_retry_process=puzzle_outcome.retry_process,
                    nama_pengguna=customer_information.nama_pengguna,
                    jenis_pengguna=customer_information.jenis_pengguna,
                )
                self.limiter.record_success()
                self._log_transaction_stage(
                    nik, "completed", attempt_number=attempt_number
                )
            except Exception as exc:  # noqa: BLE001 - never retry a confirmed sale.
                self._handle_post_processing_failure(nik, exc)
            return

        # This NIK already has a terminal skip row. Recovery must stay outside
        # the transaction retry loop, even when hard navigation also fails.
        self._record_workflow_event(nik, "skipped_nik_recovery_started")
        try:
            self._handle_session_recovery()
        except Exception as exc:  # noqa: BLE001 - preserve the recorded skip on recovery failure.
            self._record_workflow_event(
                nik,
                "skipped_nik_recovery_failed",
                reason=f"Pemulihan sesi setelah skip gagal: {exc}",
            )
        else:
            self._record_workflow_event(nik, "skipped_nik_recovery_succeeded")

    def _log_transaction_outcome(self, nik: str, outcome: TransactionOutcome) -> None:
        logger.bind(
            event="transaction.outcome",
            operator_id=self.operator_id,
            nik=str(nik),
            transaction_outcome=outcome.status,
            transaction_confirmed=outcome.success_confirmed,
            reason=outcome.reason,
            evidence=outcome.evidence,
            url=self.page.url,
        ).info("Transaction outcome observed")

    def _record_unconfirmed_transaction(
        self,
        nik: str,
        started_at: str,
        outcome: TransactionOutcome,
        puzzle: PuzzleSolveOutcome,
        customer: CustomerInformation,
        *,
        observation_error: Exception | None = None,
    ) -> None:
        """Persist a rejection/unknown result before recovery, without resubmission."""
        self._log_transaction_outcome(nik, outcome)
        fields = {
            "url": self.page.url,
            "nama_pengguna": customer.nama_pengguna,
            "jenis_pengguna": customer.jenis_pengguna,
        }
        skip_methods = {
            "customer_data_required": self.reporter.skip_needs_update,
            "max_kuota": self.reporter.skip_max_kuota,
            "zero_stock": self.reporter.skip_out_of_stock,
        }
        if outcome.status == "blocked" and outcome.reason in skip_methods:
            skip_methods[outcome.reason](
                nik, started_at, reason=outcome.evidence, **fields
            )
            self._unconfirmed_transaction_niks.discard(str(nik))
            if outcome.reason == "zero_stock":
                raise OutOfSellableStockError(outcome.evidence, reported=True)
            self.limiter.record_skip()
        else:
            # Use the existing error row/schema, retaining a real traceback and
            # the cause of an observation failure. Unknown sales are not replayed.
            try:
                raise TransactionConfirmationError(
                    f"Transaction outcome unconfirmed: {outcome.reason or 'unknown'}"
                ) from observation_error
            except TransactionConfirmationError as exc:
                logger.bind(
                    event="transaction.confirmation_failed",
                    operator_id=self.operator_id,
                    nik=str(nik),
                    transaction_confirmed=False,
                    reason=outcome.reason,
                ).exception("Transaction result could not be confirmed")
                self.reporter.error(
                    nik, started_at, exc=exc,
                    puzzle_solved=True,
                    puzzle_attempts=puzzle.attempts,
                    puzzle_retry_count=puzzle.retry_count,
                    puzzle_retry_process=puzzle.retry_process,
                    **fields,
                )
        self._capture_failure_artifact(nik, "transaction_unconfirmed")
        self._handle_session_recovery()

    def _handle_post_processing_failure(self, nik: str, exc: Exception) -> None:
        logger.bind(
            event="transaction.post_processing_failed",
            operator_id=self.operator_id,
            nik=str(nik),
            transaction_confirmed=True,
        ).exception(f"Post-processing failed after confirmed transaction: {exc}")
        # Diagnostics and recovery are best effort and cannot reopen the transaction.
        for action in (
            partial(
                self._record_workflow_event,
                nik,
                "post_processing_failed",
                reason=f"Transaction confirmed; post-processing failed: {exc}",
            ),
            partial(self._capture_failure_artifact, nik, "post_processing_failed"),
            self._handle_session_recovery,
        ):
            try:
                action()
            except Exception:  # noqa: BLE001 - preserve confirmed success on cleanup failure.
                logger.bind(
                    event="transaction.post_processing_cleanup_failed",
                    operator_id=self.operator_id,
                    nik=str(nik),
                ).exception("Post-processing diagnostics or recovery failed")

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
        self,
        penjualan: Penjualan,
        nik: str,
        started_at: str,
        stage: str,
        timeout_ms: int | None = None,
        customer_information: CustomerInformation | None = None,
    ) -> bool:
        information = customer_information or CustomerInformation()
        outcome = self._get_precheck_service().check_transaction_blocker(
            penjualan,
            nik,
            started_at,
            stage,
            timeout_ms=timeout_ms,
            nama_pengguna=information.nama_pengguna,
            jenis_pengguna=information.jenis_pengguna,
        )
        if outcome.stop_reason:
            raise OutOfSellableStockError(outcome.stop_reason, reported=True)
        return outcome.should_skip

    @staticmethod
    def _read_customer_information(penjualan: Penjualan) -> CustomerInformation:
        reader = getattr(penjualan, "read_customer_information", None)
        if reader is None:
            # Lightweight compatibility doubles and legacy page objects may not
            # expose the new scraper yet.
            return CustomerInformation()

        observed = reader()
        if isinstance(observed, CustomerInformation):
            return observed
        return CustomerInformation(
            nama_pengguna=str(getattr(observed, "nama_pengguna", "") or "").strip(),
            jenis_pengguna=str(getattr(observed, "jenis_pengguna", "") or "").strip(),
        )

    @staticmethod
    def _merge_customer_information(
        current: CustomerInformation,
        observed: CustomerInformation,
    ) -> CustomerInformation:
        """Retain the last non-empty values across bounded same-NIK retries."""
        return CustomerInformation(
            nama_pengguna=observed.nama_pengguna or current.nama_pengguna,
            jenis_pengguna=observed.jenis_pengguna or current.jenis_pengguna,
        )

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
            run_dir = getattr(
                getattr(self.config, "run_context", None), "run_dir", None
            )
            if run_dir is not None:
                artifact_root = Path(run_dir) / "artifacts"
                helpers_factory = partial(
                    Helpers,
                    output_dir=(artifact_root / "screenshots" / self.operator_id),
                )
                slider_solver = partial(
                    solve_slider_with_puzzle,
                    debug_root=str(artifact_root / "traces" / self.operator_id),
                    run_id=str(getattr(self.config.run_context, "run_id", "")),
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
                write_debug_artifacts=getattr(
                    self.config, "puzzle_debug_artifacts", False
                ),
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
