from __future__ import annotations

from datetime import datetime
from pathlib import Path

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

    def solve(self, page: Page, imgs: dict[str, Path]) -> bool:
        """Solve slider CAPTCHA."""
        attempt_dir = self._create_debug_dir()
        elements = self.element_resolver.resolve(page)

        puzzle_result, puzzle_result_path = self._solve_puzzle(imgs, attempt_dir)
        boxes = self._get_bounding_boxes(elements)
        bg_dimensions = self._get_image_dimensions(imgs["background"])

        mapping = self.coord_mapper.map_coordinates(
            imgs["piece"],
            puzzle_result[0],  # x_piece
            puzzle_result[4][0],  # tpl_w
            bg_dimensions[0],
            boxes,
        )

        self._create_visualizations(
            puzzle_result=puzzle_result,
            puzzle_result_path=puzzle_result_path,
            imgs=imgs,
            mapping=mapping,
            boxes=boxes,
            bg_dimensions=bg_dimensions,
            attempt_dir=attempt_dir,
        )

        self.metadata_writer.write_metadata(
            attempt_dir, puzzle_result, mapping, bg_dimensions
        )
        self.drag_executor.execute_drag(page, mapping)
        return self.success_detector.check_success(page, elements.root)

    def _create_debug_dir(self) -> Path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        attempt_dir = Path(self.config.debug_root) / ts
        attempt_dir.mkdir(parents=True, exist_ok=True)
        return attempt_dir

    def _solve_puzzle(
        self, imgs: dict[str, Path], attempt_dir: Path
    ) -> tuple[PuzzleResult, Path]:
        puzzle_result_path = attempt_dir / "puzzle_fused_vis.jpg"
        solver = PuzzleSolver(
            gap_image_path=str(imgs["piece"]),
            bg_image_path=str(imgs["background"]),
            output_image_path=str(puzzle_result_path),
        )
        result = solver.discern_xy()
        return result, puzzle_result_path

    @staticmethod
    def _get_bounding_boxes(elements: SliderElements) -> BoundingBoxes:
        bg_bb = elements.bg_el.bounding_box()
        ctrl_bb = elements.control.bounding_box()
        knob_bb = elements.knob.bounding_box()

        if not all([bg_bb, ctrl_bb, knob_bb]):
            raise RuntimeError("Slider elements not visible")

        return BoundingBoxes(bg=bg_bb, control=ctrl_bb, knob=knob_bb)

    @staticmethod
    def _get_image_dimensions(bg_path: Path) -> tuple[int, int]:
        with Image.open(bg_path) as bg_img:
            return bg_img.width, bg_img.height

    def _create_visualizations(
        self,
        puzzle_result: PuzzleResult,
        puzzle_result_path: Path,
        imgs: dict[str, Path],
        mapping: CoordinateMapping,
        boxes: BoundingBoxes,
        bg_dimensions: tuple[int, int],
        attempt_dir: Path,
    ) -> None:
        x_piece, y_piece, _score, _scale, (tpl_w, tpl_h) = puzzle_result

        render_puzzle_overlay(
            str(imgs["background"]),
            (x_piece, y_piece),
            (tpl_w, tpl_h),
            attempt_dir / "match_overlay.jpg",
        )

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
    config = SliderConfig(
        **{k: v for k, v in kwargs.items() if hasattr(SliderConfig, k)}
    )
    solver = SliderSolver(config)
    return solver.solve(page, imgs)
