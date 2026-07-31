from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.logging_utils import log_print, logger


@dataclass(slots=True)
class PuzzleSolveOutcome:
    solved: bool
    attempts: int
    retry_count: int = 0
    retry_process: str = ""


class PuzzleService:
    """Solves the slider CAPTCHA with the current bounded retry rules."""

    def __init__(
        self,
        *,
        page,
        dashboard,
        operator_email: str,
        helpers_factory: Callable[[Any], Any],
        puzzle_solver_factory: Callable[..., Any],
        slider_solver: Callable[..., bool],
        max_attempts: int,
        max_wait_success_ms: int,
        retry_modal_timeout_ms: int,
        refresh_timeout_ms: int,
        retry_process: str,
        write_debug_artifacts: bool = False,
        log_func: Callable[..., None] = log_print,
    ) -> None:
        self.page = page
        self.dashboard = dashboard
        self.operator_email = operator_email
        self.helpers_factory = helpers_factory
        self.puzzle_solver_factory = puzzle_solver_factory
        self.slider_solver = slider_solver
        self.max_attempts = max_attempts
        self.max_wait_success_ms = max_wait_success_ms
        self.retry_modal_timeout_ms = retry_modal_timeout_ms
        self.refresh_timeout_ms = refresh_timeout_ms
        self.retry_process = retry_process
        self.write_debug_artifacts = write_debug_artifacts
        self.log_func = log_func

    def solve(self, nik: str) -> PuzzleSolveOutcome:
        attempts_used = 0
        retry_count = 0
        retry_process = ""

        for attempt_number in range(1, self.max_attempts + 1):
            attempts_used = attempt_number
            helpers = self.helpers_factory(self.page)
            bg_src, piece_src = helpers.get_puzzle_image_sources()
            piece_path = helpers.save_puzzle_piece(nik)
            bg_path = helpers.save_puzzle_bg(nik)

            result_path = (
                Path(piece_path).parent / helpers.build_puzzle_output_name(nik, "result")
                if self.write_debug_artifacts
                else None
            )

            if result_path is not None:
                self.log_func(f"Result path (abs): {result_path.resolve()}")

            solver = self.puzzle_solver_factory(
                gap_image_path=piece_path,
                bg_image_path=bg_path,
                output_image_path=str(result_path) if result_path else None,
            )
            position = solver.discern_xy()
            self.log_func(f"The position of the slide is: {position}")

            success = self.slider_solver(
                self.page,
                imgs={"background": Path(bg_path), "piece": Path(piece_path)},
                max_wait_success_ms=self.max_wait_success_ms,
                puzzle_result=position,
                puzzle_result_path=result_path,
                write_debug_artifacts=self.write_debug_artifacts,
            )
            self.log_func(f"Slider solved on attempt {attempt_number}: {success}")

            if success:
                return PuzzleSolveOutcome(
                    solved=True,
                    attempts=attempt_number,
                    retry_count=retry_count,
                    retry_process=retry_process,
                )

            if attempt_number >= self.max_attempts:
                break

            modal_title = self.dashboard.detect_failed_puzzle_modal_if_needed(
                detect_timeout=self.retry_modal_timeout_ms
            )
            if not modal_title:
                break

            retry_count += 1
            retry_process = self.retry_process
            logger.bind(
                event="transaction.puzzle_retry",
                operator=self.operator_email,
                nik=str(nik),
                retry_count=retry_count,
                retry_process=retry_process,
                modal_title=modal_title,
            ).info("Retrying failed puzzle solve")
            self.log_func(
                f"Retrying puzzle for NIK {nik} during {retry_process} "
                f"(attempt {attempt_number + 1}/{self.max_attempts})."
            )
            helpers.wait_for_puzzle_refresh(
                previous_bg_src=bg_src,
                previous_piece_src=piece_src,
                timeout_ms=self.refresh_timeout_ms,
            )

        return PuzzleSolveOutcome(
            solved=False,
            attempts=max(1, attempts_used),
            retry_count=retry_count,
            retry_process=retry_process,
        )
