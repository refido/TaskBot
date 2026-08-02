from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from inspect import Parameter, signature
from pathlib import Path
from typing import Any

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
        self.log_func = log_func

    def solve(self, nik: str) -> PuzzleSolveOutcome:
        attempts_used = 0
        retry_count = 0
        retry_process = ""

        for attempt_number in range(1, self.max_attempts + 1):
            attempts_used = attempt_number
            helpers = self.helpers_factory(self.page)
            capture_images = getattr(helpers, "capture_puzzle_images", None)
            image_arrays = None
            if callable(capture_images):
                bundle = capture_images(nik)
                bg_src, piece_src = bundle.background_src, bundle.piece_src
                bg_path = bundle.background_path
                piece_path = bundle.piece_path
                image_arrays = bundle.arrays
            else:
                bg_src, piece_src = helpers.get_puzzle_image_sources()
                piece_path = Path(helpers.save_puzzle_piece(nik))
                bg_path = Path(helpers.save_puzzle_bg(nik))

            out_dir = Path(piece_path).parent
            result_path = out_dir / helpers.build_puzzle_output_name(nik, "result")

            self.log_func(f"Result path (abs): {result_path.resolve()}")

            solver_kwargs: dict[str, Any] = {
                "gap_image_path": piece_path,
                "bg_image_path": bg_path,
                "output_image_path": str(result_path),
            }
            if image_arrays is not None:
                solver_kwargs["gap_image"] = image_arrays.get("piece")
                solver_kwargs["bg_image"] = image_arrays.get("background")

            solver = self.puzzle_solver_factory(**solver_kwargs)
            position = solver.discern_xy()
            self.log_func(f"The position of the slide is: {position}")
            timing_metrics = getattr(solver, "timing_metrics", None)
            if timing_metrics:
                self.log_func(f"Puzzle solve timing (ms): {dict(timing_metrics)}")

            success = self._call_slider_solver(
                imgs={"background": Path(bg_path), "piece": Path(piece_path)},
                image_arrays=image_arrays,
                puzzle_result=position,
                puzzle_result_path=result_path,
                solver_timing_ms=(
                    dict(timing_metrics) if isinstance(timing_metrics, dict) else None
                ),
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

    def _call_slider_solver(
        self,
        *,
        imgs: dict[str, Path],
        image_arrays: dict[str, Any] | None,
        puzzle_result: Any,
        puzzle_result_path: Path,
        solver_timing_ms: dict[str, float] | None,
    ) -> bool:
        kwargs: dict[str, Any] = {"max_wait_success_ms": self.max_wait_success_ms}
        optional_kwargs: dict[str, Any] = {
            "image_arrays": image_arrays,
            "puzzle_result": puzzle_result,
            "puzzle_result_path": puzzle_result_path,
            "solver_timing_ms": solver_timing_ms,
        }

        try:
            params = signature(self.slider_solver).parameters
        except TypeError, ValueError:
            params = {}

        accepts_kwargs = any(
            param.kind == Parameter.VAR_KEYWORD for param in params.values()
        )
        for key, value in optional_kwargs.items():
            if value is not None and (accepts_kwargs or key in params):
                kwargs[key] = value

        return bool(self.slider_solver(self.page, imgs=imgs, **kwargs))
