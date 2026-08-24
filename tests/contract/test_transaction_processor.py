from pathlib import Path
from types import SimpleNamespace

import pytest

from src.application.models.customer_workflow import (
    CustomerUpdateLoopError,
    PrecheckAction,
)
from src.application.services.puzzle_service import PuzzleService, PuzzleSolveOutcome
from src.application.services.transaction_prechecks import TransactionPrechecksService
from src.orchestration import transaction_processor
from src.web.session_state import SessionExpiredError


class FakePage:
    def __init__(self, url: str = "https://app.test/dashboard") -> None:
        self.url = url
        self.load_states: list[str] = []
        self.timeouts: list[int] = []
        self.visits: list[str] = []

    def wait_for_load_state(self, state: str) -> None:
        self.load_states.append(state)

    def wait_for_timeout(self, timeout_ms: int) -> None:
        self.timeouts.append(timeout_ms)

    def goto(self, url: str) -> None:
        self.visits.append(url)
        self.url = url


class FakeReporter:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.complete_calls: list[tuple[str, str, dict]] = []
        self.error_calls: list[tuple[str, str, Exception, dict]] = []
        self.failed_puzzle_calls: list[tuple[str, str, Exception, dict]] = []
        self.retry_calls: list[tuple[str, dict]] = []
        self.workflow_calls: list[tuple[str, dict]] = []
        self.out_of_stock_calls: list[tuple[str, str, dict]] = []
        self.skip_calls: list[tuple[str, str, str, dict]] = []

    def start_item(self, nik: str) -> str:
        self.started.append(nik)
        return "started-at"

    def complete(self, nik: str, started_at: str, **kwargs) -> None:
        self.complete_calls.append((nik, started_at, kwargs))

    def error(self, nik: str, started_at: str, exc: Exception, **kwargs) -> None:
        self.error_calls.append((nik, started_at, exc, kwargs))

    def failed_puzzle_solve(
        self, nik: str, started_at: str, exc: Exception, **kwargs
    ) -> None:
        self.failed_puzzle_calls.append((nik, started_at, exc, kwargs))

    def record_retry(self, nik: str, **kwargs) -> None:
        self.retry_calls.append((nik, kwargs))

    def record_workflow_event(self, nik: str, **kwargs) -> None:
        self.workflow_calls.append((nik, kwargs))

    def skip_out_of_stock(self, nik: str, started_at: str, **kwargs) -> None:
        self.out_of_stock_calls.append((nik, started_at, kwargs))

    def skip(self, nik: str, started_at: str, skip_type: str, **kwargs) -> None:
        self.skip_calls.append((nik, started_at, skip_type, kwargs))


class FakeLimiter:
    def __init__(self) -> None:
        self.wait_calls = 0
        self.success_calls = 0
        self.skip_calls = 0
        self.update_actions: list[str] = []

    def wait_if_needed(self, page) -> None:
        self.wait_calls += 1

    def record_success(self) -> None:
        self.success_calls += 1

    def record_skip(self) -> None:
        self.skip_calls += 1

    def wait_before_update_action(self, page, action: str) -> None:
        self.update_actions.append(action)


class FakeDashboard:
    def __init__(self) -> None:
        self.catat_penjualan_calls: list[str] = []
        self.stock_reads = 0

    def catat_penjualan(self, nik: str) -> None:
        self.catat_penjualan_calls.append(nik)

    def get_current_stock(self) -> str:
        self.stock_reads += 1
        return "12"


class FakeLogin:
    def __init__(self) -> None:
        self.login_calls: list[tuple[str, str]] = []

    def login(self, email_user: str, pin_user: str) -> None:
        self.login_calls.append((email_user, pin_user))


class FakePrecheckService:
    def __init__(self, *, should_skip: bool = False) -> None:
        self.action = PrecheckAction.SKIP if should_skip else PrecheckAction.CONTINUE
        self.precheck_calls: list[tuple[str, str]] = []
        self.blocker_calls: list[str] = []
        self.blocker_timeouts: list[int | None] = []
        self.blocker_customer_information: list[tuple[str, str]] = []

    def handle_pre_checks(
        self, nik: str, started_at: str, *, allow_customer_update: bool = True
    ) -> PrecheckAction:
        self.precheck_calls.append((nik, started_at))
        return self.action

    def check_transaction_blocker(
        self,
        penjualan,
        nik: str,
        started_at: str,
        stage: str,
        *,
        timeout_ms: int | None = None,
        nama_pengguna: str = "",
        jenis_pengguna: str = "",
    ):
        self.blocker_calls.append(stage)
        self.blocker_timeouts.append(timeout_ms)
        self.blocker_customer_information.append((nama_pengguna, jenis_pengguna))
        return SimpleNamespace(should_skip=False, stop_reason=None)


class FakePuzzleService:
    def __init__(self, outcome: PuzzleSolveOutcome) -> None:
        self.outcome = outcome
        self.calls: list[str] = []

    def solve(self, nik: str) -> PuzzleSolveOutcome:
        self.calls.append(nik)
        return self.outcome


class FakeSessionRecoveryService:
    def __init__(self) -> None:
        self.probe_calls: list[tuple[str, bool]] = []
        self.recovery_calls = 0
        self.restore_calls = 0
        self.reset_calls = 0
        self.logged_out_checks = 0

    def probe_if_due(self, *, reason: str, force: bool = False) -> None:
        self.probe_calls.append((reason, force))

    def handle_session_recovery(self) -> None:
        self.recovery_calls += 1

    def restore_logged_out_session(self) -> None:
        self.restore_calls += 1

    def check_if_logged_out(self) -> bool:
        self.logged_out_checks += 1
        return False

    def reset_probe(self) -> None:
        self.reset_calls += 1


def _build_processor(
    *,
    reporter: FakeReporter | None = None,
    limiter: FakeLimiter | None = None,
    dashboard: FakeDashboard | None = None,
    login: FakeLogin | None = None,
    page: FakePage | None = None,
    precheck_service=None,
    puzzle_service=None,
    session_recovery_service=None,
):
    processor = transaction_processor.TransactionProcessor.__new__(
        transaction_processor.TransactionProcessor
    )
    processor.config = SimpleNamespace(
        operator_id="operator_01",
        email_user="tester@example.com",
        pin_user="123456",
        url_application="https://app.test/",
    )
    processor.operator_id = "operator_01"
    processor.page = page or FakePage()
    processor.reporter = reporter or FakeReporter()
    processor.limiter = limiter or FakeLimiter()
    processor.dashboard = dashboard or FakeDashboard()
    processor.login = login or FakeLogin()
    processor._precheck_service = precheck_service
    processor._puzzle_service = puzzle_service
    processor._session_recovery_service = (
        session_recovery_service or FakeSessionRecoveryService()
    )
    return processor


def test_dashboard_zero_stock_records_one_terminal_row_before_stopping():
    class ZeroStockDashboard(FakeDashboard):
        def catat_penjualan(self, nik: str) -> str:
            self.catat_penjualan_calls.append(nik)
            return "zero_stock"

    reporter = FakeReporter()
    processor = _build_processor(
        reporter=reporter,
        dashboard=ZeroStockDashboard(),
    )

    with pytest.raises(transaction_processor.OutOfSellableStockError):
        processor.process_single_nik("3573051108720003")

    assert len(reporter.out_of_stock_calls) == 1
    nik, started_at, payload = reporter.out_of_stock_calls[0]
    assert nik == "3573051108720003"
    assert started_at == "started-at"
    assert "Stok Tabung Kosong" in payload["reason"]


def test_registration_limit_immediately_after_nik_submission_closes_and_skips_once():
    class RegistrationLimitedDashboard(FakeDashboard):
        def __init__(self) -> None:
            super().__init__()
            self.modal_open = False
            self.dismiss_calls = 0
            self.reset_calls = 0

        def catat_penjualan(self, nik: str) -> str:
            self.catat_penjualan_calls.append(nik)
            self.modal_open = True
            return "ready"

        def get_visible_customer_entry(self) -> str:
            return "precheck_modal" if self.modal_open else "unknown"

        def get_visible_precheck_modal(self):
            return "registration_request_limited" if self.modal_open else None

        def read_registration_request_limited_reason_if_present(
            self, detect_timeout=6000
        ):
            if not self.modal_open:
                return None
            return (
                "Terlalu banyak melakukan permintaan pendaftaran untuk NIK "
                "pelanggan ini. Silakan coba lagi di hari berikutnya."
            )

        def dismiss_registration_request_limited_modal(self) -> None:
            self.dismiss_calls += 1
            self.modal_open = False

        def reset_nik_input_or_return_to_dashboard(self, **_kwargs) -> None:
            self.reset_calls += 1

    class HiddenComponent:
        def is_visible(self) -> bool:
            return False

    reporter = FakeReporter()
    limiter = FakeLimiter()
    puzzle = FakePuzzleService(PuzzleSolveOutcome(solved=True, attempts=1))
    recovery = FakeSessionRecoveryService()
    dashboard = RegistrationLimitedDashboard()
    page = FakePage()
    components = [HiddenComponent() for _ in range(5)]
    prechecks = TransactionPrechecksService(
        page=page,
        dashboard=dashboard,
        reporter=reporter,
        limiter=limiter,
        post_skip_cooldown_ms=0,
        max_kuota_timeout_ms=0,
        zero_stock_timeout_ms=0,
        log_func=lambda *_args, **_kwargs: None,
        consent_page=components[0],
        customer_update_page=components[1],
        update_required_modal=components[2],
        update_confirmation_modal=components[3],
        update_success_modal=components[4],
        login_page_detector=lambda *_args, **_kwargs: False,
    )
    processor = _build_processor(
        reporter=reporter,
        limiter=limiter,
        dashboard=dashboard,
        page=page,
        precheck_service=prechecks,
        puzzle_service=puzzle,
        session_recovery_service=recovery,
    )

    processor.process_single_nik("3573051108720003")

    assert dashboard.catat_penjualan_calls == ["3573051108720003"]
    assert dashboard.dismiss_calls == 1
    assert dashboard.reset_calls == 1
    assert len(reporter.skip_calls) == 1
    assert reporter.skip_calls[0][2] == "registration_request_limited"
    assert reporter.complete_calls == []
    assert reporter.error_calls == []
    assert reporter.retry_calls == []
    assert puzzle.calls == []
    assert recovery.recovery_calls == 0
    assert limiter.update_actions == []
    assert limiter.wait_calls == 1
    assert limiter.skip_calls == 1


def test_solve_puzzle_stops_after_five_attempts(monkeypatch):
    class DashboardWithPuzzleModal:
        def __init__(self) -> None:
            self.modal_checks = 0

        def detect_failed_puzzle_modal_if_needed(self, detect_timeout: int) -> str:
            self.modal_checks += 1
            return "Cocokan Gambar untuk Proses Keamanan Penjualan"

    class FakeHelpers:
        refresh_calls = 0
        source_index = 0

        def __init__(self, page) -> None:
            self.page = page

        def get_puzzle_image_sources(self) -> tuple[str, str]:
            FakeHelpers.source_index += 1
            current = FakeHelpers.source_index
            return f"bg-{current}", f"piece-{current}"

        def save_puzzle_piece(self, nik: str) -> str:
            return f"data_puzzle/{nik}_piece.png"

        def save_puzzle_bg(self, nik: str) -> str:
            return f"data_puzzle/{nik}_bg.png"

        def build_puzzle_output_name(self, nik: str, image_type: str) -> str:
            return f"{nik}_{image_type}.png"

        def wait_for_puzzle_refresh(
            self,
            *,
            previous_bg_src: str,
            previous_piece_src: str,
            timeout_ms: int,
        ) -> bool:
            FakeHelpers.refresh_calls += 1
            return True

    class FakePuzzleSolver:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def discern_xy(self) -> tuple[int, int]:
            return (12, 34)

    solve_calls = {"count": 0}

    def fake_solve_slider_with_puzzle(
        page, imgs, max_wait_success_ms: int, **kwargs
    ) -> bool:
        solve_calls["count"] += 1
        assert "puzzle_result" in kwargs
        return False

    monkeypatch.setattr(transaction_processor, "Helpers", FakeHelpers)
    monkeypatch.setattr(transaction_processor, "PuzzleSolver", FakePuzzleSolver)
    monkeypatch.setattr(
        transaction_processor,
        "solve_slider_with_puzzle",
        fake_solve_slider_with_puzzle,
    )
    monkeypatch.setattr(
        transaction_processor, "log_print", lambda *args, **kwargs: None
    )

    processor = _build_processor(
        dashboard=DashboardWithPuzzleModal(),
        page=object(),
    )

    outcome = processor._solve_puzzle("3174")

    assert outcome.solved is False
    assert outcome.attempts == 5
    assert outcome.retry_count == 4
    assert (
        outcome.retry_process
        == transaction_processor.TransactionProcessor._PUZZLE_RETRY_PROCESS
    )
    assert solve_calls["count"] == 5
    assert processor.dashboard.modal_checks == 4
    assert FakeHelpers.refresh_calls == 4


def test_puzzle_service_reuses_single_solver_result_with_in_memory_images():
    piece_img = object()
    bg_img = object()
    puzzle_result = (12, 34, 0.91, 1.0, (42, 33))

    class FakeHelpers:
        def __init__(self, page) -> None:
            self.page = page

        def capture_puzzle_images(self, nik: str):
            return SimpleNamespace(
                background_src=f"bg-{nik}",
                piece_src=f"piece-{nik}",
                background_path=Path("data_puzzle/bg.png"),
                piece_path=Path("data_puzzle/piece.png"),
                arrays={"background": bg_img, "piece": piece_img},
            )

        def build_puzzle_output_name(self, nik: str, image_type: str) -> str:
            return f"{nik}_{image_type}.png"

    solver_instances = []

    class FakePuzzleSolver:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            self.timing_metrics = {"total": 12.5}
            solver_instances.append(self)

        def discern_xy(self):
            return puzzle_result

    slider_calls = []

    def fake_slider(page, imgs, max_wait_success_ms: int, **kwargs) -> bool:
        slider_calls.append((page, imgs, max_wait_success_ms, kwargs))
        return True

    service = PuzzleService(
        page=object(),
        dashboard=object(),
        operator_email="tester@example.com",
        helpers_factory=FakeHelpers,
        puzzle_solver_factory=FakePuzzleSolver,
        slider_solver=fake_slider,
        max_attempts=5,
        max_wait_success_ms=3500,
        retry_modal_timeout_ms=2500,
        refresh_timeout_ms=5000,
        retry_process="proses_penjualan",
        log_func=lambda *args, **kwargs: None,
    )

    outcome = service.solve("3174")

    assert outcome == PuzzleSolveOutcome(solved=True, attempts=1)
    assert len(solver_instances) == 1
    assert solver_instances[0].kwargs["gap_image"] is piece_img
    assert solver_instances[0].kwargs["bg_image"] is bg_img
    assert solver_instances[0].kwargs["output_image_path"] == str(
        Path("data_puzzle/3174_result.png")
    )
    assert len(slider_calls) == 1
    _page, imgs, max_wait_success_ms, kwargs = slider_calls[0]
    assert imgs == {
        "background": Path("data_puzzle/bg.png"),
        "piece": Path("data_puzzle/piece.png"),
    }
    assert max_wait_success_ms == 3500
    assert kwargs["image_arrays"] == {"background": bg_img, "piece": piece_img}
    assert kwargs["puzzle_result"] == puzzle_result
    assert kwargs["puzzle_result_path"] == Path("data_puzzle/3174_result.png")
    assert kwargs["solver_timing_ms"] == {"total": 12.5}
    assert kwargs["write_debug_artifacts"] is False


def test_process_single_nik_completes_and_records_success(monkeypatch):
    class FakePenjualan:
        instances = 0
        cek_pesanan_calls = 0

        def __init__(self, page) -> None:
            FakePenjualan.instances += 1

        def read_customer_information(self):
            return SimpleNamespace(
                nama_pengguna="JOHN DOE",
                jenis_pengguna="RUMAH TANGGA",
            )

        def cek_pesanan(self) -> None:
            FakePenjualan.cek_pesanan_calls += 1

    class FakeCekPenjualan:
        proses_penjualan_calls = 0
        kembali_calls = 0

        def __init__(self, page) -> None:
            self.page = page

        def proses_penjualan(self) -> None:
            FakeCekPenjualan.proses_penjualan_calls += 1

        def kembali_ke_dashboard(self) -> None:
            FakeCekPenjualan.kembali_calls += 1

    monkeypatch.setattr(transaction_processor, "Penjualan", FakePenjualan)
    monkeypatch.setattr(transaction_processor, "CekPenjualan", FakeCekPenjualan)

    reporter = FakeReporter()
    limiter = FakeLimiter()
    precheck_service = FakePrecheckService()
    puzzle_service = FakePuzzleService(
        PuzzleSolveOutcome(
            solved=True,
            attempts=2,
            retry_count=1,
            retry_process="proses_penjualan",
        )
    )
    session_recovery_service = FakeSessionRecoveryService()
    processor = _build_processor(
        reporter=reporter,
        limiter=limiter,
        precheck_service=precheck_service,
        puzzle_service=puzzle_service,
        session_recovery_service=session_recovery_service,
    )

    processor.process_single_nik("3174")

    assert reporter.complete_calls == [
        (
            "3174",
            "started-at",
            {
                "url": "https://app.test/dashboard",
                "puzzle_solved": True,
                "puzzle_attempts": 2,
                "puzzle_retry_count": 1,
                "puzzle_retry_process": "proses_penjualan",
                "nama_pengguna": "JOHN DOE",
                "jenis_pengguna": "RUMAH TANGGA",
            },
        )
    ]
    assert limiter.wait_calls == 1
    assert limiter.success_calls == 1
    assert precheck_service.precheck_calls == [("3174", "started-at")]
    assert precheck_service.blocker_calls == [
        "before cek pesanan",
        "after cek pesanan",
    ]
    assert precheck_service.blocker_timeouts == [300, 1500]
    assert precheck_service.blocker_customer_information == [
        ("JOHN DOE", "RUMAH TANGGA"),
        ("JOHN DOE", "RUMAH TANGGA"),
    ]
    assert puzzle_service.calls == ["3174"]
    assert FakePenjualan.instances == 1
    assert FakePenjualan.cek_pesanan_calls == 1
    assert FakeCekPenjualan.proses_penjualan_calls == 1
    assert FakeCekPenjualan.kembali_calls == 1
    assert session_recovery_service.recovery_calls == 0


def test_process_single_nik_stops_when_prechecks_skip(monkeypatch):
    class FailIfConstructedPenjualan:
        def __init__(self, page) -> None:
            raise AssertionError(
                "penjualan should not be constructed when prechecks skip"
            )

    monkeypatch.setattr(transaction_processor, "Penjualan", FailIfConstructedPenjualan)

    reporter = FakeReporter()
    limiter = FakeLimiter()
    precheck_service = FakePrecheckService(should_skip=True)
    session_recovery_service = FakeSessionRecoveryService()
    processor = _build_processor(
        reporter=reporter,
        limiter=limiter,
        precheck_service=precheck_service,
        puzzle_service=FakePuzzleService(PuzzleSolveOutcome(solved=True, attempts=1)),
        session_recovery_service=session_recovery_service,
    )

    processor.process_single_nik("3174")

    assert reporter.started == ["3174"]
    assert reporter.complete_calls == []
    assert reporter.error_calls == []
    assert reporter.failed_puzzle_calls == []
    assert limiter.success_calls == 0
    assert session_recovery_service.recovery_calls == 0


def test_inline_transaction_blocker_stops_before_cek_pesanan_and_puzzle(monkeypatch):
    class FailIfCheckedPenjualan:
        def __init__(self, page) -> None:
            self.page = page

        def cek_pesanan(self) -> None:
            raise AssertionError("CEK PESANAN must not run after a transaction blocker")

    class BlockingPrechecks(FakePrecheckService):
        def check_transaction_blocker(
            self,
            penjualan,
            nik: str,
            started_at: str,
            stage: str,
            **_kwargs,
        ):
            self.blocker_calls.append(stage)
            return SimpleNamespace(should_skip=True, stop_reason=None)

    monkeypatch.setattr(transaction_processor, "Penjualan", FailIfCheckedPenjualan)
    reporter = FakeReporter()
    prechecks = BlockingPrechecks()
    puzzle_service = FakePuzzleService(PuzzleSolveOutcome(solved=True, attempts=1))
    processor = _build_processor(
        reporter=reporter,
        precheck_service=prechecks,
        puzzle_service=puzzle_service,
    )

    processor.process_single_nik("3573051108720003")

    assert prechecks.blocker_calls == ["before cek pesanan"]
    assert puzzle_service.calls == []
    assert reporter.complete_calls == []
    assert reporter.error_calls == []
    assert reporter.retry_calls == []


def test_successful_update_restarts_same_nik_without_consuming_retry_budgets(
    monkeypatch,
):
    class RestartingPrechecks(FakePrecheckService):
        def __init__(self) -> None:
            super().__init__()
            self.actions = iter(
                [PrecheckAction.RESTART_AFTER_UPDATE, PrecheckAction.CONTINUE]
            )
            self.allow_flags = []

        def handle_pre_checks(
            self, nik: str, started_at: str, *, allow_customer_update: bool = True
        ) -> PrecheckAction:
            self.precheck_calls.append((nik, started_at))
            self.allow_flags.append(allow_customer_update)
            return next(self.actions)

    class FakePenjualan:
        def __init__(self, page) -> None:
            self.page = page

        def cek_pesanan(self) -> None:
            return None

    class FakeCekPenjualan:
        def __init__(self, page) -> None:
            self.page = page

        def proses_penjualan(self) -> None:
            return None

        def kembali_ke_dashboard(self) -> None:
            return None

    monkeypatch.setattr(transaction_processor, "Penjualan", FakePenjualan)
    monkeypatch.setattr(transaction_processor, "CekPenjualan", FakeCekPenjualan)
    reporter = FakeReporter()
    limiter = FakeLimiter()
    prechecks = RestartingPrechecks()
    recovery = FakeSessionRecoveryService()
    processor = _build_processor(
        reporter=reporter,
        limiter=limiter,
        precheck_service=prechecks,
        puzzle_service=FakePuzzleService(PuzzleSolveOutcome(solved=True, attempts=1)),
        session_recovery_service=recovery,
    )

    processor.process_single_nik("3573051108720003")

    assert processor.dashboard.catat_penjualan_calls == [
        "3573051108720003",
        "3573051108720003",
    ]
    assert reporter.started == ["3573051108720003"]
    assert prechecks.allow_flags == [True, False]
    assert len(reporter.complete_calls) == 1
    assert reporter.retry_calls == []
    assert recovery.recovery_calls == 0
    assert limiter.wait_calls == 2
    assert limiter.update_actions == ["restart_same_nik"]
    assert limiter.skip_calls == 0
    assert [event[1]["event"] for event in reporter.workflow_calls] == [
        "same_nik_restart_after_update"
    ]


def test_nik_navigation_does_not_wait_for_document_load_state():
    page = FakePage()
    processor = _build_processor(page=page)

    processor._navigate_to_transaction("3573051108720003")

    assert processor.dashboard.catat_penjualan_calls == ["3573051108720003"]
    assert page.load_states == []


def test_repeated_update_after_same_nik_restart_is_terminal_without_retry():
    class RepeatingUpdatePrechecks(FakePrecheckService):
        def __init__(self) -> None:
            super().__init__()
            self.allow_flags = []

        def handle_pre_checks(
            self, nik: str, started_at: str, *, allow_customer_update: bool = True
        ) -> PrecheckAction:
            self.precheck_calls.append((nik, started_at))
            self.allow_flags.append(allow_customer_update)
            if len(self.precheck_calls) == 1:
                return PrecheckAction.RESTART_AFTER_UPDATE
            raise CustomerUpdateLoopError("same NIK still requires customer update")

    reporter = FakeReporter()
    recovery = FakeSessionRecoveryService()
    prechecks = RepeatingUpdatePrechecks()
    processor = _build_processor(
        reporter=reporter,
        precheck_service=prechecks,
        puzzle_service=FakePuzzleService(PuzzleSolveOutcome(solved=True, attempts=1)),
        session_recovery_service=recovery,
    )

    processor.process_single_nik("3573051108720003")

    assert processor.dashboard.catat_penjualan_calls == [
        "3573051108720003",
        "3573051108720003",
    ]
    assert prechecks.allow_flags == [True, False]
    assert len(reporter.error_calls) == 1
    assert reporter.complete_calls == []
    assert reporter.retry_calls == []
    assert recovery.recovery_calls == 1
    assert [event[1]["event"] for event in reporter.workflow_calls] == [
        "same_nik_restart_after_update",
        "customer_update_failed",
    ]


def test_process_single_nik_reports_failed_puzzle_and_recovers(monkeypatch):
    class FakePenjualan:
        def __init__(self, page) -> None:
            self.page = page

        def cek_pesanan(self) -> None:
            return None

    class FakeCekPenjualan:
        def __init__(self, page) -> None:
            self.page = page

        def proses_penjualan(self) -> None:
            return None

        def kembali_ke_dashboard(self) -> None:
            return None

    monkeypatch.setattr(transaction_processor, "Penjualan", FakePenjualan)
    monkeypatch.setattr(transaction_processor, "CekPenjualan", FakeCekPenjualan)

    reporter = FakeReporter()
    puzzle_service = FakePuzzleService(
        PuzzleSolveOutcome(
            solved=False,
            attempts=5,
            retry_count=4,
            retry_process="proses_penjualan",
        )
    )
    session_recovery_service = FakeSessionRecoveryService()
    processor = _build_processor(
        reporter=reporter,
        precheck_service=FakePrecheckService(),
        puzzle_service=puzzle_service,
        session_recovery_service=session_recovery_service,
    )

    processor.process_single_nik("3174")

    assert len(reporter.failed_puzzle_calls) == 1
    nik, started_at, exc, payload = reporter.failed_puzzle_calls[0]
    assert (nik, started_at) == ("3174", "started-at")
    assert "after 5 attempts" in str(exc)
    assert payload["puzzle_attempts"] == 5
    assert payload["puzzle_retry_count"] == 4
    assert payload["puzzle_retry_process"] == "proses_penjualan"
    assert session_recovery_service.recovery_calls == 1


def test_process_single_nik_retries_once_after_session_expired_then_errors():
    class ExpiringPrecheckService(FakePrecheckService):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        def handle_pre_checks(
            self, nik: str, started_at: str, *, allow_customer_update: bool = True
        ) -> PrecheckAction:
            self.attempts += 1
            raise SessionExpiredError(f"expired attempt {self.attempts}")

    reporter = FakeReporter()
    session_recovery_service = FakeSessionRecoveryService()
    processor = _build_processor(
        reporter=reporter,
        precheck_service=ExpiringPrecheckService(),
        puzzle_service=FakePuzzleService(PuzzleSolveOutcome(solved=True, attempts=1)),
        session_recovery_service=session_recovery_service,
    )

    processor.process_single_nik("3174")

    assert len(reporter.error_calls) == 1
    nik, started_at, exc, payload = reporter.error_calls[0]
    assert (nik, started_at) == ("3174", "started-at")
    assert isinstance(exc, SessionExpiredError)
    assert payload["puzzle_solved"] is None
    assert payload["puzzle_attempts"] == 0
    assert session_recovery_service.recovery_calls == 2


def test_process_single_nik_retries_general_errors_twice_then_completes(monkeypatch):
    class FlakyPenjualan:
        cek_pesanan_calls = 0

        def __init__(self, page) -> None:
            self.page = page

        def cek_pesanan(self) -> None:
            FlakyPenjualan.cek_pesanan_calls += 1
            if FlakyPenjualan.cek_pesanan_calls <= 2:
                raise RuntimeError(
                    f"transient attempt {FlakyPenjualan.cek_pesanan_calls}"
                )

    class FakeCekPenjualan:
        def __init__(self, page) -> None:
            self.page = page

        def proses_penjualan(self) -> None:
            return None

        def kembali_ke_dashboard(self) -> None:
            return None

    monkeypatch.setattr(transaction_processor, "Penjualan", FlakyPenjualan)
    monkeypatch.setattr(transaction_processor, "CekPenjualan", FakeCekPenjualan)

    reporter = FakeReporter()
    limiter = FakeLimiter()
    puzzle_service = FakePuzzleService(PuzzleSolveOutcome(solved=True, attempts=1))
    session_recovery_service = FakeSessionRecoveryService()
    processor = _build_processor(
        reporter=reporter,
        limiter=limiter,
        precheck_service=FakePrecheckService(),
        puzzle_service=puzzle_service,
        session_recovery_service=session_recovery_service,
    )

    processor.process_single_nik("3174")

    assert len(reporter.retry_calls) == 2
    assert [call[0] for call in reporter.retry_calls] == ["3174", "3174"]
    first_retry = reporter.retry_calls[0][1]
    second_retry = reporter.retry_calls[1][1]
    assert first_retry["trigger"] == "general_error"
    assert first_retry["process"] == "process_single_nik"
    assert first_retry["attempt_number"] == 1
    assert first_retry["retry_number"] == 1
    assert first_retry["max_retries"] == 2
    assert second_retry["attempt_number"] == 2
    assert second_retry["retry_number"] == 2
    assert reporter.error_calls == []
    assert len(reporter.complete_calls) == 1
    assert limiter.wait_calls == 3
    assert puzzle_service.calls == ["3174"]
    assert session_recovery_service.recovery_calls == 2


def test_process_single_nik_errors_after_general_retry_limit(monkeypatch):
    class FailingPenjualan:
        cek_pesanan_calls = 0

        def __init__(self, page) -> None:
            self.page = page

        def cek_pesanan(self) -> None:
            FailingPenjualan.cek_pesanan_calls += 1
            raise RuntimeError(f"still failing {FailingPenjualan.cek_pesanan_calls}")

    monkeypatch.setattr(transaction_processor, "Penjualan", FailingPenjualan)

    reporter = FakeReporter()
    limiter = FakeLimiter()
    session_recovery_service = FakeSessionRecoveryService()
    processor = _build_processor(
        reporter=reporter,
        limiter=limiter,
        precheck_service=FakePrecheckService(),
        puzzle_service=FakePuzzleService(PuzzleSolveOutcome(solved=True, attempts=1)),
        session_recovery_service=session_recovery_service,
    )

    processor.process_single_nik("3174")

    assert FailingPenjualan.cek_pesanan_calls == 3
    assert len(reporter.retry_calls) == 2
    assert [call[1]["retry_number"] for call in reporter.retry_calls] == [1, 2]
    assert len(reporter.error_calls) == 1
    nik, started_at, exc, payload = reporter.error_calls[0]
    assert (nik, started_at) == ("3174", "started-at")
    assert isinstance(exc, RuntimeError)
    assert payload["puzzle_solved"] is None
    assert limiter.wait_calls == 3
    assert session_recovery_service.recovery_calls == 3
