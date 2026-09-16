from __future__ import annotations

from datetime import datetime
from inspect import Parameter, signature
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import Page

from src.pipelines.slider.artifacts import DiagramCreator, MetadataWriter
from src.pipelines.slider.coordinates import CoordinateMapper
from src.pipelines.slider.elements import ElementResolver
from src.pipelines.slider.execution import DragExecutor
from src.pipelines.slider.mask import MaskProcessor
from src.pipelines.slider.movement import MovementGenerator
from src.pipelines.slider.success import SuccessDetector
from src.pipelines.slider.types import (
    BoundingBoxes,
    CoordinateMapping,
    PuzzleResult,
    SliderConfig,
    SliderElements,
)
from src.vision.overlay import render_puzzle_overlay
from src.vision.puzzle_solver import PuzzleSolver


class SliderSolver:
    """Main solver orchestrating all components."""

    def __init__(self, config: SliderConfig | None = None) -> None:
        self.config = config or SliderConfig()

        self.mask_processor = MaskProcessor(self.config.alpha_threshold)
        self.movement_gen = MovementGenerator(self.config)
        self.coord_mapper = CoordinateMapper(self.config, self.mask_processor)
        self.element_resolver = ElementResolver(self.config)
        self.diagram_creator = DiagramCreator()
        self.metadata_writer = MetadataWriter()
        self.drag_executor = DragExecutor(self.config, self.movement_gen)
        self.success_detector = SuccessDetector(self.config)

    def solve(
        self,
        page: Page,
        imgs: dict[str, Path],
        *,
        image_arrays: dict[str, np.ndarray] | None = None,
        puzzle_result: PuzzleResult | None = None,
        puzzle_result_path: Path | None = None,
        solver_timing_ms: dict[str, float] | None = None,
    ) -> bool:
        """Solve slider CAPTCHA."""
        attempt_dir = (
            self._create_debug_dir() if self.config.write_debug_artifacts else None
        )
        elements = self.element_resolver.resolve(page)

        if puzzle_result is None:
            puzzle_result, puzzle_result_path, solver_timing_ms = self._solve_puzzle(
                imgs, attempt_dir, image_arrays=image_arrays
            )

        boxes = self._get_bounding_boxes(elements)
        if image_arrays is None:
            bg_dimensions = self._get_image_dimensions(imgs["background"])
        else:
            bg_dimensions = self._get_image_dimensions(
                imgs["background"], image_arrays.get("background")
            )

        mapping = self.coord_mapper.map_coordinates(
            imgs["piece"],
            puzzle_result[0],  # x_piece
            puzzle_result[4][0],  # tpl_w
            bg_dimensions[0],
            boxes,
            piece_img=None if image_arrays is None else image_arrays.get("piece"),
        )

        if attempt_dir is not None:
            self._create_visualizations(
                puzzle_result=puzzle_result,
                puzzle_result_path=puzzle_result_path,
                imgs=imgs,
                mapping=mapping,
                boxes=boxes,
                bg_dimensions=bg_dimensions,
                attempt_dir=attempt_dir,
                image_arrays=image_arrays,
            )

            self.metadata_writer.write_metadata(
                attempt_dir,
                puzzle_result,
                mapping,
                bg_dimensions,
                solver_timing_ms=solver_timing_ms,
                run_id=self.config.run_id,
                operator_id=self.config.operator_id,
                nik=self.config.nik,
            )
        self.drag_executor.execute_drag(page, mapping)
        return self.success_detector.check_success(page, elements.root)

    def _create_debug_dir(self) -> Path:
        ts = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
        attempt_dir = Path(self.config.debug_root) / ts
        attempt_dir.mkdir(parents=True, exist_ok=True)
        return attempt_dir

    def _solve_puzzle(
        self,
        imgs: dict[str, Path],
        attempt_dir: Path | None,
        *,
        image_arrays: dict[str, np.ndarray] | None = None,
    ) -> tuple[PuzzleResult, Path | None, dict[str, float]]:
        puzzle_result_path = (
            attempt_dir / "puzzle_fused_vis.jpg" if attempt_dir is not None else None
        )
        solver = PuzzleSolver(
            gap_image_path=str(imgs["piece"]),
            bg_image_path=str(imgs["background"]),
            output_image_path=(
                str(puzzle_result_path) if puzzle_result_path is not None else None
            ),
            gap_image=None if image_arrays is None else image_arrays.get("piece"),
            bg_image=None if image_arrays is None else image_arrays.get("background"),
        )
        result = solver.discern_xy()
        return result, puzzle_result_path, dict(solver.timing_metrics)

    @staticmethod
    def _get_bounding_boxes(elements: SliderElements) -> BoundingBoxes:
        bg_bb = elements.bg_el.bounding_box()
        ctrl_bb = elements.control.bounding_box()
        knob_bb = elements.knob.bounding_box()

        if not all([bg_bb, ctrl_bb, knob_bb]):
            raise RuntimeError("Slider elements not visible")

        return BoundingBoxes(bg=bg_bb, control=ctrl_bb, knob=knob_bb)

    @staticmethod
    def _get_image_dimensions(
        bg_path: Path, bg_img: np.ndarray | None = None
    ) -> tuple[int, int]:
        if bg_img is not None:
            h, w = bg_img.shape[:2]
            return int(w), int(h)

        with Image.open(bg_path) as loaded_bg:
            return loaded_bg.width, loaded_bg.height

    def _create_visualizations(
        self,
        puzzle_result: PuzzleResult,
        puzzle_result_path: Path | None,
        imgs: dict[str, Path],
        mapping: CoordinateMapping,
        boxes: BoundingBoxes,
        bg_dimensions: tuple[int, int],
        attempt_dir: Path,
        image_arrays: dict[str, np.ndarray] | None = None,
    ) -> None:
        x_piece, y_piece, _score, _scale, (tpl_w, tpl_h) = puzzle_result

        render_puzzle_overlay(
            str(imgs["background"]),
            (x_piece, y_piece),
            (tpl_w, tpl_h),
            attempt_dir / "match_overlay.jpg",
            bg_img=None if image_arrays is None else image_arrays.get("background"),
        )

        if puzzle_result_path is not None:
            self.diagram_creator.create_diagram(
                puzzle_result_path=puzzle_result_path,
                mapping=mapping,
                ctrl_bb_x=boxes.control["x"],
                ctrl_bb_width=boxes.control["width"],
                bg_img_width=bg_dimensions[0],
                output_dir=attempt_dir,
            )


def solve_slider_with_puzzle(
    page: Page, imgs: dict[str, Path], **kwargs: object
) -> bool:
    """
    Convenience function maintaining backward compatibility.

    Solve slider CAPTCHA with human-like movement patterns.
    """
    puzzle_result = kwargs.pop("puzzle_result", None)
    raw_puzzle_result_path = kwargs.pop("puzzle_result_path", None)
    puzzle_result_path = (
        Path(raw_puzzle_result_path) if raw_puzzle_result_path is not None else None
    )
    config = SliderConfig(
        **{k: v for k, v in kwargs.items() if hasattr(SliderConfig, k)}
    )
    solver = SliderSolver(config)
    image_arrays = kwargs.get("image_arrays")
    solver_timing_ms = kwargs.get("solver_timing_ms")
    optional_solve_kwargs: dict[str, object] = {
        "image_arrays": image_arrays if isinstance(image_arrays, dict) else None,
        "puzzle_result": puzzle_result if isinstance(puzzle_result, tuple) else None,
        "puzzle_result_path": puzzle_result_path,
        "solver_timing_ms": (
            solver_timing_ms if isinstance(solver_timing_ms, dict) else None
        ),
    }

    try:
        solve_params = signature(solver.solve).parameters
    except (TypeError, ValueError):
        solve_params = {}
    accepts_kwargs = any(
        param.kind == Parameter.VAR_KEYWORD for param in solve_params.values()
    )
    solve_kwargs = {
        key: value
        for key, value in optional_solve_kwargs.items()
        if value is not None and (accepts_kwargs or key in solve_params)
    }
    return solver.solve(page, imgs, **solve_kwargs)
