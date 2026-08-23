from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from src.pipelines.slider.types import CoordinateMapping, PuzzleResult


class DiagramCreator:
    """Creates movement visualization diagrams."""

    def create_diagram(
        self,
        puzzle_result_path: Path,
        mapping: CoordinateMapping,
        ctrl_bb_x: float,
        ctrl_bb_width: float,
        bg_img_width: int,
        output_dir: Path,
    ) -> None:
        """Create and save movement diagram."""
        base_img = cv2.imread(str(puzzle_result_path))
        if base_img is None:
            return

        base_w = base_img.shape[1]
        bar = self._create_bar(base_w, mapping, ctrl_bb_x, ctrl_bb_width, bg_img_width)
        final_img = self._combine_images(base_img, bar, mapping, bg_img_width)

        output_path = output_dir / "movement_diagram.jpg"
        cv2.imwrite(str(output_path), final_img)

    def _create_bar(
        self,
        width: int,
        mapping: CoordinateMapping,
        ctrl_bb_x: float,
        ctrl_bb_width: float,
        bg_img_width: int,
    ) -> np.ndarray:
        bar_height = 80
        bar_bg = np.ones((bar_height, width, 3), dtype=np.uint8) * 40

        margin = 20
        rail_start = margin
        rail_width = width - 2 * margin
        y_center = bar_height // 2

        piece_center_x = mapping.slot_left_x_img + mapping.puzzle_tile_width / 2.0
        u = piece_center_x / float(bg_img_width)
        piece_center_bar_x = rail_start + u * rail_width

        current_rel = mapping.current_x - ctrl_bb_x
        target_rel = mapping.clamped_target_x - ctrl_bb_x

        current_bar_x = rail_start + (current_rel / ctrl_bb_width) * rail_width
        target_bar_x = rail_start + (target_rel / ctrl_bb_width) * rail_width

        current_bar_x = max(rail_start, min(current_bar_x, rail_start + rail_width))
        target_bar_x = max(rail_start, min(target_bar_x, rail_start + rail_width))
        piece_center_bar_x = max(
            rail_start, min(piece_center_bar_x, rail_start + rail_width)
        )

        self._draw_rail(bar_bg, rail_start, rail_width, y_center)
        self._draw_current(bar_bg, current_bar_x, y_center)
        self._draw_target(bar_bg, target_bar_x, y_center)
        self._draw_arrow(bar_bg, current_bar_x, target_bar_x, y_center)
        self._draw_piece_center(bar_bg, piece_center_bar_x, bar_height)
        self._draw_labels(bar_bg, mapping.distance_px, bar_height)

        return bar_bg

    @staticmethod
    def _draw_rail(img: np.ndarray, start: int, width: int, y: int) -> None:
        cv2.line(img, (start, y), (start + width, y), (100, 100, 100), 3)

    @staticmethod
    def _draw_current(img: np.ndarray, x: float, y: int) -> None:
        x_int = int(x)
        cv2.line(img, (x_int, y - 15), (x_int, y + 15), (0, 255, 0), 4)
        cv2.circle(img, (x_int, y), 8, (0, 255, 0), -1)

    @staticmethod
    def _draw_target(img: np.ndarray, x: float, y: int) -> None:
        cv2.circle(img, (int(x), y), 10, (0, 0, 255), -1)

    @staticmethod
    def _draw_arrow(img: np.ndarray, start_x: float, end_x: float, y: int) -> None:
        if int(start_x) != int(end_x):
            cv2.arrowedLine(
                img,
                (int(start_x) + 15, y),
                (int(end_x) - 15, y),
                (0, 255, 255),
                2,
                tipLength=0.2,
            )

    @staticmethod
    def _draw_piece_center(img: np.ndarray, x: float, height: int) -> None:
        cv2.line(img, (int(x), 0), (int(x), height), (255, 0, 0), 2)

    @staticmethod
    def _draw_labels(img: np.ndarray, distance: float, height: int) -> None:
        cv2.putText(
            img,
            f"Distance: {distance:.1f}px",
            (10, 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            1,
        )
        cv2.putText(
            img,
            "GREEN = Current | RED = Target",
            (10, height - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            1,
        )

    @staticmethod
    def _combine_images(
        base_img: np.ndarray,
        bar: np.ndarray,
        mapping: CoordinateMapping,
        bg_img_width: int,
    ) -> np.ndarray:
        base_h, base_w = base_img.shape[:2]
        final = np.vstack([base_img, bar])

        piece_center_x = mapping.slot_left_x_img + mapping.puzzle_tile_width / 2.0
        u = piece_center_x / float(bg_img_width)
        piece_center_img_x = round(u * base_w)

        margin = 20
        rail_start = margin
        rail_width = base_w - 2 * margin
        piece_center_bar_x = rail_start + u * rail_width

        cv2.line(
            final,
            (piece_center_img_x, base_h - 5),
            (int(piece_center_bar_x), base_h + 5),
            (255, 0, 0),
            2,
        )
        return final


class MetadataWriter:
    """Writes metadata for debugging."""

    def write_metadata(
        self,
        output_dir: Path,
        puzzle_result: PuzzleResult,
        mapping: CoordinateMapping,
        bg_dimensions: tuple[int, int],
        solver_timing_ms: dict[str, float] | None = None,
        run_id: str = "",
        operator_id: str = "",
        nik: str = "",
    ) -> None:
        """Save solving metadata."""
        x_piece, y_piece, score, scale, (tpl_w, tpl_h) = puzzle_result
        bg_img_width, bg_img_height = bg_dimensions

        piece_center_x = mapping.slot_left_x_img + mapping.puzzle_tile_width / 2.0
        piece_center_y = y_piece + tpl_h / 2.0

        metadata = {
            "run_id": run_id,
            "operator_id": operator_id,
            "nik": nik,
            "puzzle_result": {
                "x": x_piece,
                "y": y_piece,
                "score": score,
                "scale": scale,
                "template_size": [tpl_w, tpl_h],
            },
            "piece_center": {
                "x_image": float(piece_center_x),
                "y_image": float(piece_center_y),
            },
            "bg_image_dimensions": [bg_img_width, bg_img_height],
            "unitless_ratios": {
                "u_x": float(piece_center_x / bg_img_width),
                "u_y": float(piece_center_y / bg_img_height),
            },
            "target_screen": {
                "x": float(mapping.clamped_target_x),
                "y_background": float(mapping.target_y_screen),
            },
            "knob_current": {
                "x": float(mapping.current_x),
                "y": float(mapping.current_y),
            },
            "distance_to_move": float(mapping.distance_px),
            "rail_bounds_x": list(mapping.rail_limits),
            "drag_y": float(mapping.current_y),
        }
        if solver_timing_ms:
            metadata["solver_timing_ms"] = {
                key: round(float(value), 3)
                for key, value in sorted(solver_timing_ms.items())
            }

        (output_dir / "meta.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )
