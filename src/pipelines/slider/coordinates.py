from __future__ import annotations

from pathlib import Path

import numpy as np

from src.pipelines.slider.mask import MaskProcessor
from src.pipelines.slider.types import (
    BoundingBoxes,
    CoordinateMapping,
    SliderConfig,
)


class CoordinateMapper:
    """Handles coordinate transformations between image and screen space."""

    def __init__(self, config: SliderConfig, mask_processor: MaskProcessor) -> None:
        self.config = config
        self.mask_processor = mask_processor

    def map_coordinates(
        self,
        piece_path: Path,
        x_piece: int,
        tpl_w: int,
        bg_img_width: int,
        boxes: BoundingBoxes,
        piece_img: np.ndarray | None = None,
    ) -> CoordinateMapping:
        """Map puzzle coordinates to screen coordinates."""

        slot_left_x_img, puzzle_tile_w = self.mask_processor.compute_slot_left_x(
            piece_path, x_piece, tpl_w, piece_img=piece_img
        )

        max_offset_img = max(1.0, float(bg_img_width - puzzle_tile_w))
        slot_offset_img = max(0.0, min(slot_left_x_img, max_offset_img))
        u_offset = slot_offset_img / max_offset_img

        knob_w = boxes.knob["width"]
        knob_h = boxes.knob["height"]
        knob_half = knob_w / 2.0

        rail_x = boxes.control["x"]
        rail_w = boxes.control["width"]
        knob_travel = rail_w - knob_w

        target_x_screen = rail_x + knob_half + u_offset * knob_travel
        target_y_screen = boxes.bg["y"] + boxes.bg["height"] / 2.0

        current_x = boxes.knob["x"] + knob_half
        current_y = boxes.knob["y"] + knob_h / 2.0

        distance_px = target_x_screen - current_x

        left_limit = rail_x + knob_half + self.config.rail_margin
        right_limit = rail_x + rail_w - knob_half - self.config.rail_margin

        unclamped = current_x + distance_px
        clamped_target_x = max(left_limit, min(unclamped, right_limit))
        distance_px = clamped_target_x - current_x

        return CoordinateMapping(
            slot_left_x_img=slot_left_x_img,
            puzzle_tile_width=puzzle_tile_w,
            target_x_screen=target_x_screen,
            target_y_screen=target_y_screen,
            current_x=current_x,
            current_y=current_y,
            distance_px=distance_px,
            clamped_target_x=clamped_target_x,
            rail_limits=(left_limit, right_limit),
        )
