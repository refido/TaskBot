from types import SimpleNamespace

import src.orchestration.transaction_processor as transaction_processor
from src.application.services.puzzle_service import PuzzleSolveOutcome
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


class FakeLimiter:
    def __init__(self) -> None:
        self.wait_calls = 0
        self.success_calls = 0
        self.skip_calls = 0

    def wait_if_needed(self, page) -> None:
        self.wait_calls += 1

    def record_success(self) -> None:
        self.success_calls += 1

    def record_skip(self) -> None:
        self.skip_calls += 1


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
        self.should_skip = should_skip
        self.precheck_calls: list[tuple[str, str]] = []
        self.zero_stock_calls: list[str] = []
        self.max_kuota_calls: list[str] = []

    def handle_pre_checks(self, nik: str, started_at: str) -> bool:
        self.precheck_calls.append((nik, started_at))
        return self.should_skip

    def check_zero_stock(self, penjualan, nik: str, started_at: str, stage: str):
        self.zero_stock_calls.append(stage)
        return None

    def check_max_kuota(self, penjualan, nik: str, started_at: str, stage: str) -> bool:
        self.max_kuota_calls.append(stage)
        return False


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
        email_user="tester@example.com",
        pin_user="123456",
        url_application="https://app.test/",
    )
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

    def fake_solve_slider_with_puzzle(page, imgs, max_wait_success_ms: int) -> bool:
        solve_calls["count"] += 1
        return False

    monkeypatch.setattr(transaction_processor, "Helpers", FakeHelpers)
    monkeypatch.setattr(transaction_processor, "PuzzleSolver", FakePuzzleSolver)
    monkeypatch.setattr(
        transaction_processor,
        "solve_slider_with_puzzle",
        fake_solve_slider_with_puzzle,
    )
    monkeypatch.setattr(transaction_processor, "log_print", lambda *args, **kwargs: None)

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


def test_process_single_nik_completes_and_records_success(monkeypatch):
    class FakePenjualan:
        instances = 0
        cek_pesanan_calls = 0

        def __init__(self, page) -> None:
            FakePenjualan.instances += 1

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
            },
        )
    ]
    assert limiter.wait_calls == 1
    assert limiter.success_calls == 1
    assert precheck_service.precheck_calls == [("3174", "started-at")]
    assert precheck_service.zero_stock_calls == [
        "before cek pesanan",
        "after cek pesanan",
    ]
    assert precheck_service.max_kuota_calls == [
        "before cek pesanan",
        "after cek pesanan",
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
            raise AssertionError("penjualan should not be constructed when prechecks skip")

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

        def handle_pre_checks(self, nik: str, started_at: str) -> bool:
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
