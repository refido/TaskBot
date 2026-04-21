from types import SimpleNamespace

import src.orchestration.transaction_processor as transaction_processor


def test_solve_puzzle_stops_after_five_attempts(monkeypatch):
    class FakeDashboard:
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

    processor = transaction_processor.TransactionProcessor.__new__(
        transaction_processor.TransactionProcessor
    )
    processor.page = object()
    processor.config = SimpleNamespace(email_user="tester@example.com")
    processor.dashboard = FakeDashboard()

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
