import json
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image
from playwright.sync_api import Page

from src.vision.overlay import render_puzzle_overlay
from src.vision.puzzle_solver import PuzzleSolver


@dataclass
class SliderConfig:
    """Configuration for slider CAPTCHA solving."""

    # Element selectors
    container_selector: str = (
        ".rc-slider-captcha, .rc-slider-captcha-embed, .rc-slider-captcha-panel"
    )
    bg_selector: str = "img.rc-slider-captcha-jigsaw-bg"
    knob_selector: str = (
        "span.rc-slider-captcha-button.rc-slider-captcha-control-button, "
        "span.rc-slider-captcha-button.rc-slider-captcha-button-pc"
    )
    rail_selector: str = ".rc-slider-captcha-control"

    # Success detection
    success_selector: str = ".captcha-success"
    success_text: str = "Berhasil"
    max_wait_success_ms: int = 3500

    # Movement parameters
    min_steps: int = 20
    max_steps: int = 32
    step_divisor: int = 6
    step_base: int = 15

    # Timing (milliseconds)
    initial_pause_min: int = 50
    initial_pause_max: int = 150
    step_pause_min: int = 0
    step_pause_max: int = 3
    release_pause_min: int = 30
    release_pause_max: int = 80
    validation_wait: int = 250

    # Constraints
    rail_margin: int = 4
    alpha_threshold: int = 5

    # Debugging
    debug_root: str = "data_puzzle/puzzle_debug/"


@dataclass
class SliderElements:
    """Container for slider DOM elements."""

    root: Any
    bg_el: Any
    control: Any
    knob: Any


@dataclass
class BoundingBoxes:
    """Bounding boxes for slider elements."""

    bg: Dict[str, float]
    control: Dict[str, float]
    knob: Dict[str, float]


@dataclass
class CoordinateMapping:
    """Result of coordinate mapping calculation."""

    slot_left_x_img: float
    puzzle_tile_width: int
    target_x_screen: float
    target_y_screen: float
    current_x: float
    current_y: float
    distance_px: float
    clamped_target_x: float
    rail_limits: Tuple[float, float]


class MaskProcessor:
    """Processes alpha masks to extract puzzle tile information."""

    def __init__(self, alpha_threshold: int = 5):
        self.alpha_threshold = alpha_threshold

    # Public methods
    def compute_slot_left_x(
        self, piece_img_path: Path, x_piece: float, tpl_w: int
    ) -> Tuple[float, int]:
        """
        Recover puzzle slot left X coordinate in background pixels.

        Returns: (slot_left_x_in_bg, puzzle_tile_width_in_image_px)
        """
        piece_img = cv2.imread(str(piece_img_path), cv2.IMREAD_UNCHANGED)
        if piece_img is None:
            return float(x_piece), tpl_w

        h, w = piece_img.shape[:2]
        has_alpha = piece_img.ndim == 3 and piece_img.shape[2] == 4
        if not has_alpha:
            return float(x_piece), w

        mask = self._extract_alpha_mask(piece_img)

        ys, xs = np.where(mask > 0)
        if xs.size == 0:
            return float(x_piece), w

        alpha_x0 = int(xs.min())
        alpha_x1 = int(xs.max())
        cropped_width = alpha_x1 - alpha_x0 + 1

        scale_crop_to_tpl = tpl_w / float(cropped_width)
        slot_left_x = float(x_piece) - alpha_x0 * scale_crop_to_tpl

        return slot_left_x, w

    # Private helpers
    def _extract_alpha_mask(self, img: np.ndarray) -> np.ndarray:
        """Extract and process alpha channel mask."""
        alpha = img[:, :, 3]
        mask = (alpha > self.alpha_threshold).astype(np.uint8) * 255

        mask = cv2.morphologyEx(
            mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1
        )
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=1
        )
        return mask


class MovementGenerator:
    """Generates human-like movement paths."""

    def __init__(self, config: SliderConfig):
        self.config = config

    # Public methods
    def generate_path(self, distance_px: int) -> List[int]:
        """Generate smooth movement path with easing."""
        print(f"[MovementGenerator] Distance: {distance_px}px")

        sign = 1 if distance_px >= 0 else -1
        abs_dist = abs(distance_px)

        steps = self._calculate_steps(abs_dist)
        print(f"[MovementGenerator] Steps: {steps}, Sign: {sign}, Distance: {abs_dist}")

        path = self._build_path(abs_dist, steps, sign)
        print(f"[MovementGenerator] Path: {len(path)} steps, Total: {sum(path)}px")
        return path

    # Private helpers
    def _calculate_steps(self, distance: int) -> int:
        return max(
            self.config.min_steps,
            min(
                self.config.max_steps,
                distance // self.config.step_divisor + self.config.step_base,
            ),
        )

    def _build_path(self, distance: int, steps: int, sign: int) -> List[int]:
        path: List[int] = []
        remaining = distance
        accumulated = 0.0

        for i in range(1, steps + 1):
            t = i / steps
            target = distance * self._ease_out_quad(t)
            delta = target - accumulated
            accumulated = target

            move = max(1, int(round(delta))) if i < steps else remaining
            path.append(sign * move)
            remaining -= move

            if remaining <= 0:
                break

        actual_total = sum(path)
        expected_total = sign * distance
        if actual_total != expected_total:
            correction = expected_total - actual_total
            path.append(correction)
            print(f"[MovementGenerator] Correction: {correction}")

        return path

    @staticmethod
    def _ease_out_quad(t: float) -> float:
        return 1 - (1 - t) * (1 - t)


class CoordinateMapper:
    """Handles coordinate transformations between image and screen space."""

    def __init__(self, config: SliderConfig, mask_processor: MaskProcessor):
        self.config = config
        self.mask_processor = mask_processor

    # Public methods
    def map_coordinates(
        self,
        piece_path: Path,
        x_piece: int,
        tpl_w: int,
        tpl_h: int,
        bg_img_width: int,
        bg_img_height: int,
        boxes: BoundingBoxes,
    ) -> CoordinateMapping:
        """Map puzzle coordinates to screen coordinates."""
        print("\n[CoordinateMapper] Starting coordinate mapping...")

        slot_left_x_img, puzzle_tile_w = self.mask_processor.compute_slot_left_x(
            piece_path, x_piece, tpl_w
        )
        print(f"  Slot left X (image): {slot_left_x_img:.2f}")
        print(f"  Puzzle tile width: {puzzle_tile_w}")

        max_offset_img = max(1.0, float(bg_img_width - puzzle_tile_w))
        slot_offset_img = max(0.0, min(slot_left_x_img, max_offset_img))
        u_offset = slot_offset_img / max_offset_img

        print(f"  Max offset: {max_offset_img:.2f}")
        print(f"  U offset: {u_offset:.6f}")

        knob_w = boxes.knob["width"]
        knob_h = boxes.knob["height"]
        knob_half = knob_w / 2.0

        rail_x = boxes.control["x"]
        rail_w = boxes.control["width"]
        knob_travel = rail_w - knob_w

        target_x_screen = rail_x + knob_half + u_offset * knob_travel
        target_y_screen = boxes.bg["y"] + boxes.bg["height"] / 2.0

        print(f"  Knob travel: {knob_travel:.2f}")
        print(f"  Target X (screen): {target_x_screen:.2f}")

        current_x = boxes.knob["x"] + knob_half
        current_y = boxes.knob["y"] + knob_h / 2.0

        distance_px = target_x_screen - current_x

        left_limit = rail_x + knob_half + self.config.rail_margin
        right_limit = rail_x + rail_w - knob_half - self.config.rail_margin

        unclamped = current_x + distance_px
        clamped_target_x = max(left_limit, min(unclamped, right_limit))
        if clamped_target_x != unclamped:
            print(f"  Clamped: {unclamped:.2f} -> {clamped_target_x:.2f}")

        distance_px = clamped_target_x - current_x
        print(f"  Final distance: {distance_px:.2f}px\n")

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


class ElementResolver:
    """Resolves slider DOM elements."""

    _BG_VISIBLE_TIMEOUT_MS: int = 8000
    _CTRL_VISIBLE_TIMEOUT_MS: int = 6000
    _KNOB_VISIBLE_TIMEOUT_MS: int = 2000

    def __init__(self, config: SliderConfig):
        self.config = config

    # Public methods
    def resolve(self, page: Page) -> SliderElements:
        """Locate and return slider elements."""
        print("[ElementResolver] Starting resolution...")

        bg_el = page.locator(self.config.bg_selector).first
        bg_el.wait_for(state="visible", timeout=self._BG_VISIBLE_TIMEOUT_MS)
        print("[ElementResolver] Background element found")

        root = self._find_root_container(page, bg_el)
        control = self._find_control(root)
        knob = self._find_knob(root, control)

        self._prepare_elements(page, root, control, knob)

        print("[ElementResolver] Resolution complete")
        return SliderElements(root=root, bg_el=bg_el, control=control, knob=knob)

    # Private helpers
    def _find_root_container(self, page: Page, bg_el: Any) -> Any:
        containers = page.locator(self.config.container_selector)
        count = containers.count()
        print(f"[ElementResolver] Found {count} container(s)")

        if count > 0:
            try:
                root = containers.filter(has=bg_el).first
                if root.count() > 0:
                    return root
            except Exception as exc:
                print(f"[ElementResolver] Filter error: {exc}")

        print("[ElementResolver] Using XPath fallback")
        return bg_el.locator(
            "xpath=ancestor::div[contains(@class,'rc-slider-captcha')]"
        ).first

    def _find_control(self, root: Any) -> Any:
        control = root.locator(self.config.rail_selector).first
        if control.count() == 0:
            print("[ElementResolver] Using fallback control selector")
            control = root.locator("div.rc-slider-captcha-control").first
        return control

    def _find_knob(self, root: Any, control: Any) -> Any:
        knob = root.locator(self.config.knob_selector).first
        if knob.count() == 0:
            print("[ElementResolver] Using fallback knob selector")
            knob = control.locator(
                "span.rc-slider-captcha-button.rc-slider-captcha-control-button"
            ).first
        return knob

    def _prepare_elements(self, page: Page, root: Any, control: Any, knob: Any) -> None:
        try:
            root.scroll_into_view_if_needed(timeout=1000)
            root.hover()
            page.wait_for_timeout(120)
        except Exception as exc:
            print(f"[ElementResolver] Preparation error: {exc}")

        control.wait_for(state="visible", timeout=self._CTRL_VISIBLE_TIMEOUT_MS)

        try:
            knob.wait_for(state="visible", timeout=self._KNOB_VISIBLE_TIMEOUT_MS)
        except Exception as exc:
            print(f"[ElementResolver] Knob visibility error: {exc}")


class DiagramCreator:
    """Creates movement visualization diagrams."""

    # Public methods
    def create_diagram(
        self,
        puzzle_result_path: Path,
        x_piece: int,
        y_piece: int,
        tpl_w: int,
        tpl_h: int,
        mapping: CoordinateMapping,
        ctrl_bb_x: float,
        ctrl_bb_width: float,
        bg_img_width: int,
        output_dir: Path,
    ) -> None:
        """Create and save movement diagram."""
        print("[DiagramCreator] Creating diagram...")

        base_img = cv2.imread(str(puzzle_result_path))
        if base_img is None:
            print(f"[DiagramCreator] ERROR: Cannot read {puzzle_result_path}")
            return

        base_h, base_w = base_img.shape[:2]
        bar = self._create_bar(base_w, mapping, ctrl_bb_x, ctrl_bb_width, bg_img_width)
        final_img = self._combine_images(base_img, bar, base_w, mapping, bg_img_width)

        output_path = output_dir / "movement_diagram.jpg"
        cv2.imwrite(str(output_path), final_img)
        print(f"[DiagramCreator] Diagram saved to {output_path}")

    # Private helpers
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

    def _draw_rail(self, img: np.ndarray, start: int, width: int, y: int) -> None:
        cv2.line(img, (start, y), (start + width, y), (100, 100, 100), 3)

    def _draw_current(self, img: np.ndarray, x: float, y: int) -> None:
        x_int = int(x)
        cv2.line(img, (x_int, y - 15), (x_int, y + 15), (0, 255, 0), 4)
        cv2.circle(img, (x_int, y), 8, (0, 255, 0), -1)

    def _draw_target(self, img: np.ndarray, x: float, y: int) -> None:
        cv2.circle(img, (int(x), y), 10, (0, 0, 255), -1)

    def _draw_arrow(
        self, img: np.ndarray, start_x: float, end_x: float, y: int
    ) -> None:
        if int(start_x) != int(end_x):
            cv2.arrowedLine(
                img,
                (int(start_x) + 15, y),
                (int(end_x) - 15, y),
                (0, 255, 255),
                2,
                tipLength=0.2,
            )

    def _draw_piece_center(self, img: np.ndarray, x: float, height: int) -> None:
        cv2.line(img, (int(x), 0), (int(x), height), (255, 0, 0), 2)

    def _draw_labels(self, img: np.ndarray, distance: float, height: int) -> None:
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

    def _combine_images(
        self,
        base_img: np.ndarray,
        bar: np.ndarray,
        base_w: int,
        mapping: CoordinateMapping,
        bg_img_width: int,
    ) -> np.ndarray:
        base_h = base_img.shape[0]
        final = np.vstack([base_img, bar])

        piece_center_x = mapping.slot_left_x_img + mapping.puzzle_tile_width / 2.0
        u = piece_center_x / float(bg_img_width)
        piece_center_img_x = int(round(u * base_w))

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

    # Public methods
    def write_metadata(
        self,
        output_dir: Path,
        puzzle_result: Tuple[int, int, float, float, Tuple[int, int]],
        mapping: CoordinateMapping,
        bg_dimensions: Tuple[int, int],
    ) -> None:
        """Save solving metadata."""
        x_piece, y_piece, score, scale, (tpl_w, tpl_h) = puzzle_result
        bg_img_width, bg_img_height = bg_dimensions

        piece_center_x = mapping.slot_left_x_img + mapping.puzzle_tile_width / 2.0
        piece_center_y = y_piece + tpl_h / 2.0

        metadata = {
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

        (output_dir / "meta.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )


class DragExecutor:
    """Executes drag movement on page."""

    def __init__(self, config: SliderConfig, movement_gen: MovementGenerator):
        self.config = config
        self.movement_gen = movement_gen

    # Public methods
    def execute_drag(self, page: Page, mapping: CoordinateMapping) -> None:
        """Execute drag movement with human-like behavior."""
        print("\n[DragExecutor] Executing drag movement...")
        print(f"  Start: ({mapping.current_x:.1f}, {mapping.current_y:.1f})")
        print(f"  Target X: {mapping.clamped_target_x:.1f}")

        page.wait_for_timeout(
            random.randint(self.config.initial_pause_min, self.config.initial_pause_max)
        )

        page.mouse.move(mapping.current_x, mapping.current_y)
        page.mouse.down()
        print("[DragExecutor] Mouse down")

        int_distance = int(round(mapping.distance_px))
        path = self.movement_gen.generate_path(int_distance)

        x_cur = mapping.current_x
        for step_idx, dx in enumerate(path):
            x_cur += dx
            page.mouse.move(x_cur, mapping.current_y, steps=1)

            if step_idx % random.randint(8, 12) == 0:
                page.wait_for_timeout(
                    random.randint(
                        self.config.step_pause_min, self.config.step_pause_max
                    )
                )

            if step_idx % 8 == 0:
                print(f"  Step {step_idx}: x={x_cur:.1f}, dx={dx}")

        print(f"[DragExecutor] Final: x={x_cur:.1f}, y={mapping.current_y:.1f}")
        print(f"[DragExecutor] Total moved: {x_cur - mapping.current_x:.1f}px")

        page.wait_for_timeout(
            random.randint(self.config.release_pause_min, self.config.release_pause_max)
        )
        page.mouse.up()
        print("[DragExecutor] Mouse up\n")

        page.wait_for_timeout(self.config.validation_wait)


class SuccessDetector:
    """Detects CAPTCHA success."""

    _ROOT_HIDDEN_TIMEOUT_MS: int = 1500

    def __init__(self, config: SliderConfig):
        self.config = config

    # Public methods
    def check_success(self, page: Page, root: Any) -> bool:
        """Check if CAPTCHA was solved successfully."""
        print(
            f"[SuccessDetector] Checking success (timeout: {self.config.max_wait_success_ms}ms)..."
        )

        if self._check_by_selector(page):
            return True
        if self._check_by_text(page):
            return True
        if self._check_root_hidden(root):
            return True

        print("[SuccessDetector] FAILED: Could not detect success")
        return False

    # Private helpers
    def _check_by_selector(self, page: Page) -> bool:
        try:
            page.locator(self.config.success_selector).first.wait_for(
                timeout=self.config.max_wait_success_ms, state="visible"
            )
            print(
                f"[SuccessDetector] SUCCESS via selector '{self.config.success_selector}'!"
            )
            return True
        except Exception as exc:
            print(f"[SuccessDetector] Selector not found: {exc}")
            return False

    def _check_by_text(self, page: Page) -> bool:
        try:
            page.get_by_text(self.config.success_text).first.wait_for(
                timeout=self.config.max_wait_success_ms, state="visible"
            )
            print(f"[SuccessDetector] SUCCESS via text '{self.config.success_text}'!")
            return True
        except Exception as exc:
            print(f"[SuccessDetector] Text not found: {exc}")
            return False

    def _check_root_hidden(self, root: Any) -> bool:
        try:
            root.wait_for(state="hidden", timeout=self._ROOT_HIDDEN_TIMEOUT_MS)
            print("[SuccessDetector] SUCCESS! Root disappeared")
            return True
        except Exception as exc:
            print(f"[SuccessDetector] Root timeout: {exc}")
            return False


class SliderSolver:
    """Main solver orchestrating all components."""

    def __init__(self, config: Optional[SliderConfig] = None):
        self.config = config or SliderConfig()

        self.mask_processor = MaskProcessor(self.config.alpha_threshold)
        self.movement_gen = MovementGenerator(self.config)
        self.coord_mapper = CoordinateMapper(self.config, self.mask_processor)
        self.element_resolver = ElementResolver(self.config)
        self.diagram_creator = DiagramCreator()
        self.metadata_writer = MetadataWriter()
        self.drag_executor = DragExecutor(self.config, self.movement_gen)
        self.success_detector = SuccessDetector(self.config)

    # Public methods (external API via solve_slider_with_puzzle)
    def solve(self, page: Page, imgs: Dict[str, Path]) -> bool:
        """Solve slider CAPTCHA."""
        print(f"\n{'=' * 70}")
        print("[SliderSolver] STARTING SLIDER CAPTCHA SOLVE")
        print(f"{'=' * 70}\n")

        attempt_dir = self._create_debug_dir()
        elements = self.element_resolver.resolve(page)

        puzzle_result, puzzle_result_path = self._solve_puzzle(imgs, attempt_dir)
        boxes = self._get_bounding_boxes(elements)
        bg_dimensions = self._get_image_dimensions(imgs["background"])

        mapping = self.coord_mapper.map_coordinates(
            imgs["piece"],
            puzzle_result[0],  # x_piece
            puzzle_result[4][0],  # tpl_w
            puzzle_result[4][1],  # tpl_h
            bg_dimensions[0],
            bg_dimensions[1],
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

        success = self.success_detector.check_success(page, elements.root)

        print(f"{'=' * 70}\n")
        return success

    # Private helpers (orchestration steps)
    def _create_debug_dir(self) -> Path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        attempt_dir = Path(self.config.debug_root) / ts
        attempt_dir.mkdir(parents=True, exist_ok=True)
        print(f"[SliderSolver] Debug directory: {attempt_dir}")
        return attempt_dir

    def _solve_puzzle(
        self, imgs: Dict[str, Path], attempt_dir: Path
    ) -> Tuple[Tuple[int, int, float, float, Tuple[int, int]], Path]:
        print("[SliderSolver] Solving puzzle...")

        puzzle_result_path = attempt_dir / "puzzle_fused_vis.jpg"
        solver = PuzzleSolver(
            gap_image_path=str(imgs["piece"]),
            bg_image_path=str(imgs["background"]),
            output_image_path=str(puzzle_result_path),
        )

        result = solver.discern_xy()
        x_piece, y_piece, score, scale, (tpl_w, tpl_h) = result

        print(f"  Position: ({x_piece}, {y_piece})")
        print(f"  Score: {score:.4f}")
        print(f"  Scale: {scale:.2f}")
        print(f"  Template: {tpl_w}x{tpl_h}")

        return result, puzzle_result_path

    def _get_bounding_boxes(self, elements: SliderElements) -> BoundingBoxes:
        print("[SliderSolver] Getting bounding boxes...")

        bg_bb = elements.bg_el.bounding_box()
        ctrl_bb = elements.control.bounding_box()
        knob_bb = elements.knob.bounding_box()

        if not all([bg_bb, ctrl_bb, knob_bb]):
            raise RuntimeError("Slider elements not visible")

        return BoundingBoxes(bg=bg_bb, control=ctrl_bb, knob=knob_bb)

    def _get_image_dimensions(self, bg_path: Path) -> Tuple[int, int]:
        bg_img = Image.open(bg_path)
        return bg_img.width, bg_img.height

    def _create_visualizations(
        self,
        puzzle_result: Tuple[int, int, float, float, Tuple[int, int]],
        puzzle_result_path: Path,
        imgs: Dict[str, Path],
        mapping: CoordinateMapping,
        boxes: BoundingBoxes,
        bg_dimensions: Tuple[int, int],
        attempt_dir: Path,
    ) -> None:
        print("[SliderSolver] Creating visualizations...")

        x_piece, y_piece, _score, _scale, (tpl_w, tpl_h) = puzzle_result

        render_puzzle_overlay(
            str(imgs["background"]),
            (x_piece, y_piece),
            (tpl_w, tpl_h),
            attempt_dir / "match_overlay.jpg",
        )

        self.diagram_creator.create_diagram(
            puzzle_result_path=puzzle_result_path,
            x_piece=x_piece,
            y_piece=y_piece,
            tpl_w=tpl_w,
            tpl_h=tpl_h,
            mapping=mapping,
            ctrl_bb_x=boxes.control["x"],
            ctrl_bb_width=boxes.control["width"],
            bg_img_width=bg_dimensions[0],
            output_dir=attempt_dir,
        )


def solve_slider_with_puzzle(page: Page, imgs: Dict[str, Path], **kwargs) -> bool:
    """
    Convenience function maintaining backward compatibility.

    Solve slider CAPTCHA with human-like movement patterns.
    """
    config = SliderConfig(
        **{k: v for k, v in kwargs.items() if hasattr(SliderConfig, k)}
    )
    solver = SliderSolver(config)
    return solver.solve(page, imgs)
