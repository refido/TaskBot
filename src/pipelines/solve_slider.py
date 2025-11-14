import json
import random
from datetime import datetime
from pathlib import Path
from typing import Dict

import cv2
import numpy as np
from PIL import Image
from playwright.sync_api import Page

from src.vision.overlay import render_puzzle_overlay
from src.vision.puzzle_solver import PuzzleSolver


def _compute_slot_left_x(
    piece_img_path: Path,
    x_piece: float,
    tpl_w: int,
    *,
    alpha_thresh: int = 5,
) -> tuple[float, int]:
    """
    Recover the puzzle 'slot' left X (tile-left) in background-image pixels,
    using the SAME mask + crop logic as PuzzleSolver._crop_by_mask for
    alpha-channel pieces.

    - piece_img_path: original puzzle PNG from rc-slider-captcha.
    - x_piece: matched top-left of the CROPPED template (in bg pixels).
    - tpl_w: width of the matched template (after scaling) returned by PuzzleSolver.
    Returns: (slot_left_x_in_bg, puzzle_tile_width_in_image_px)
    """
    piece_img = cv2.imread(str(piece_img_path), cv2.IMREAD_UNCHANGED)
    if piece_img is None:
        # Load failed → safest fallback is to use x_piece directly.
        return float(x_piece), tpl_w

    h, w = piece_img.shape[:2]
    has_alpha = piece_img.ndim == 3 and piece_img.shape[2] == 4

    if not has_alpha:
        # No alpha channel → we do not know the internal crop;
        # fall back to assuming the template covers the full tile.
        puzzle_tile_width = w
        return float(x_piece), puzzle_tile_width

    # --- 1. Build mask exactly like PuzzleSolver._crop_by_mask (alpha branch) ---
    alpha = piece_img[:, :, 3]
    mask = (alpha > alpha_thresh).astype(np.uint8) * 255

    # Morphological cleanup (must match solver)
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1
    )
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=1
    )

    ys, xs = np.where(mask > 0)
    if xs.size == 0:
        # No opaque area detected after morphology; fall back safely.
        puzzle_tile_width = w
        return float(x_piece), puzzle_tile_width

    # --- 2. This bounding box is the SAME crop the solver sees before scaling ---
    alpha_x0 = int(xs.min())
    alpha_x1 = int(xs.max())
    cropped_width = alpha_x1 - alpha_x0 + 1  # width in original tile pixels

    # The template width tpl_w is this cropped_width * best_scale (from solver).
    # So scale from cropped tile coords to matched template coords is:
    scale_crop_to_tpl = tpl_w / float(cropped_width)

    # In the matched template, x=0 corresponds to x = alpha_x0 in the original tile.
    # So tile-left (x=0 in the tile) in background coordinates is:
    slot_left_x = float(x_piece) - alpha_x0 * scale_crop_to_tpl

    # Puzzle tile width AS DISPLAYED in the screenshot (full PNG width)
    puzzle_tile_width = w

    return slot_left_x, puzzle_tile_width


def _human_track(distance_px: int) -> list[int]:
    """
    Simple, accurate movement with easing - no jitter, just precision.
    """
    print(f"[_human_track] Requested distance: {distance_px}px")

    def ease_out_quad(t: float) -> float:
        return 1 - (1 - t) * (1 - t)

    sign = 1 if distance_px >= 0 else -1
    abs_dist = abs(distance_px)

    # Optimal steps for smoothness without overcomplexity
    steps = max(20, min(32, abs_dist // 6 + 15))
    print(f"[_human_track] steps={steps}, sign={sign}, abs_dist={abs_dist}")

    path: list[int] = []
    remaining = abs_dist
    accumulated_float = 0.0

    for i in range(1, steps + 1):
        t = i / steps
        target = abs_dist * ease_out_quad(t)
        delta = target - accumulated_float
        accumulated_float = target

        # Round and track what we actually moved
        move = max(1, int(round(delta))) if i < steps else remaining
        path.append(sign * move)
        remaining -= move

        if remaining <= 0:
            break

    # Final correction if needed
    actual_total = sum(path)
    expected_total = sign * abs_dist

    if actual_total != expected_total:
        correction = expected_total - actual_total
        path.append(correction)
        print(f"[_human_track] Applied correction: {correction}")

    print(f"[_human_track] Path: {len(path)} steps, Total: {sum(path)}px")
    return path


def _resolve_slider_scope(
    page: Page,
    *,
    container_selector: str = ".rc-slider-captcha, .rc-slider-captcha-embed, .rc-slider-captcha-panel",
    bg_selector: str = "img.rc-slider-captcha-jigsaw-bg",
    knob_selector: str = (
        "span.rc-slider-captcha-button.rc-slider-captcha-control-button, "
        "span.rc-slider-captcha-button.rc-slider-captcha-button-pc"
    ),
    rail_selector: str = ".rc-slider-captcha-control",
) -> Dict[str, any]:
    """Locate slider elements in the DOM."""
    print("[_resolve_slider_scope] Starting element resolution...")
    print(f"[_resolve_slider_scope] bg_selector: {bg_selector}")

    bg_el = page.locator(bg_selector).first
    bg_el.wait_for(state="visible", timeout=8000)
    print("[_resolve_slider_scope] Background element found and visible")

    root = None
    containers = page.locator(container_selector)
    containers_count = containers.count()
    print(f"[_resolve_slider_scope] Found {containers_count} container(s)")

    if containers_count > 0:
        try:
            root = containers.filter(has=bg_el).first
            root_count = root.count()
            print(f"[_resolve_slider_scope] Root element found, count: {root_count}")
        except Exception as e:
            print(f"[_resolve_slider_scope] Exception filtering containers: {e}")
            root = None

    if root is None or (hasattr(root, "count") and root.count() == 0):
        print("[_resolve_slider_scope] Root is None or empty, using XPath fallback")
        root = bg_el.locator(
            "xpath=ancestor::div[contains(@class,'rc-slider-captcha')]"
        ).first

    control = root.locator(rail_selector).first
    print("[_resolve_slider_scope] Control element located (rail_selector)")

    if control.count() == 0:
        print("[_resolve_slider_scope] Control.count() == 0, using fallback selector")
        control = root.locator("div.rc-slider-captcha-control").first

    knob = root.locator(knob_selector).first
    print("[_resolve_slider_scope] Knob element located")

    if knob.count() == 0:
        print("[_resolve_slider_scope] Knob.count() == 0, using fallback selector")
        knob = control.locator(
            "span.rc-slider-captcha-button.rc-slider-captcha-control-button"
        ).first

    try:
        root.scroll_into_view_if_needed(timeout=1000)
        root.hover()
        page.wait_for_timeout(120)
        print("[_resolve_slider_scope] Root element scrolled and hovered")
    except Exception as e:
        print(f"[_resolve_slider_scope] Exception during scroll/hover: {e}")

    control.wait_for(state="visible", timeout=6000)
    print("[_resolve_slider_scope] Control element is visible")

    try:
        knob.wait_for(state="visible", timeout=2000)
        print("[_resolve_slider_scope] Knob element is visible")
    except Exception as e:
        print(f"[_resolve_slider_scope] Exception waiting for knob visibility: {e}")

    print("[_resolve_slider_scope] Element resolution complete")
    return {"root": root, "bg_el": bg_el, "control": control, "knob": knob}


def _create_movement_diagram(
    puzzle_result_path: Path,
    x_piece: int,
    y_piece: int,
    tpl_w: int,
    tpl_h: int,
    piece_center_x: float,
    current_x: float,
    target_x_screen: float,
    distance_px: float,
    ctrl_bb_x: float,
    ctrl_bb_width: float,
    attempt_dir: Path,
    *,
    bg_img_width: int,
) -> None:
    """Create movement visualization diagram."""
    print("[_create_movement_diagram] Starting diagram creation...")

    base_img = cv2.imread(str(puzzle_result_path))
    if base_img is None:
        print(
            f"[_create_movement_diagram] ERROR: Could not read image at {puzzle_result_path}"
        )
        return

    base_h, base_w = base_img.shape[:2]
    bar_height = 80
    bar_width = base_w
    bar_bg = np.ones((bar_height, bar_width, 3), dtype=np.uint8) * 40

    margin = 20
    bar_rail_start = margin
    bar_rail_width = bar_width - 2 * margin
    bar_y_center = bar_height // 2

    u = piece_center_x / float(bg_img_width)
    piece_center_bar_x = bar_rail_start + u * bar_rail_width

    current_relative = current_x - ctrl_bb_x
    target_relative = target_x_screen - ctrl_bb_x

    current_bar_x = bar_rail_start + (current_relative / ctrl_bb_width) * bar_rail_width
    target_bar_x = bar_rail_start + (target_relative / ctrl_bb_width) * bar_rail_width

    current_bar_x = max(
        bar_rail_start, min(current_bar_x, bar_rail_start + bar_rail_width)
    )
    target_bar_x = max(
        bar_rail_start, min(target_bar_x, bar_rail_start + bar_rail_width)
    )
    piece_center_bar_x = max(
        bar_rail_start, min(piece_center_bar_x, bar_rail_start + bar_rail_width)
    )

    # Draw rail
    cv2.line(
        bar_bg,
        (bar_rail_start, bar_y_center),
        (bar_rail_start + bar_rail_width, bar_y_center),
        (100, 100, 100),
        3,
    )

    # Draw current (green)
    cv2.line(
        bar_bg,
        (int(current_bar_x), bar_y_center - 15),
        (int(current_bar_x), bar_y_center + 15),
        (0, 255, 0),
        4,
    )
    cv2.circle(bar_bg, (int(current_bar_x), bar_y_center), 8, (0, 255, 0), -1)

    # Draw target (red)
    cv2.circle(bar_bg, (int(target_bar_x), bar_y_center), 10, (0, 0, 255), -1)

    # Draw arrow
    if int(current_bar_x) != int(target_bar_x):
        cv2.arrowedLine(
            bar_bg,
            (int(current_bar_x) + 15, bar_y_center),
            (int(target_bar_x) - 15, bar_y_center),
            (0, 255, 255),
            2,
            tipLength=0.2,
        )

    # Draw piece center line
    cv2.line(
        bar_bg,
        (int(piece_center_bar_x), 0),
        (int(piece_center_bar_x), bar_height),
        (255, 0, 0),
        2,
    )

    # Labels
    cv2.putText(
        bar_bg,
        f"Distance: {distance_px:.1f}px",
        (10, 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (255, 255, 255),
        1,
    )
    cv2.putText(
        bar_bg,
        "GREEN = Current | RED = Target",
        (10, bar_height - 10),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (255, 255, 255),
        1,
    )

    final_img = np.vstack([base_img, bar_bg])
    piece_center_img_x = int(round(u * base_w))
    cv2.line(
        final_img,
        (piece_center_img_x, base_h - 5),
        (int(piece_center_bar_x), base_h + 5),
        (255, 0, 0),
        2,
    )

    output_path = attempt_dir / "movement_diagram.jpg"
    cv2.imwrite(str(output_path), final_img)
    print(f"[_create_movement_diagram] Diagram saved to {output_path}")


def solve_slider_with_puzzle(
    page: Page,
    imgs: Dict[str, Path],
    *,
    success_selector: str = ".captcha-success",
    success_text: str = "Berhasil",
    max_wait_success_ms: int = 3500,
    debug_root: str = "data_puzzle/puzzle_debug/",
) -> bool:
    """
    Solve slider CAPTCHA with human-like movement patterns.
    The ONLY coordinate that matters for solving is the horizontal
    offset of the puzzle tile (X); Y is used only to keep the mouse
    on the rail visually.
    """
    print(f"\n{'=' * 70}")
    print("[solve_slider_with_puzzle] STARTING SLIDER CAPTCHA SOLVE")
    print(f"{'=' * 70}\n")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    attempt_dir = Path(debug_root) / ts
    attempt_dir.mkdir(parents=True, exist_ok=True)
    print(f"[solve_slider_with_puzzle] Debug directory: {attempt_dir}")

    # Get slider elements
    print("[solve_slider_with_puzzle] Resolving slider elements...")
    scope = _resolve_slider_scope(page)
    bg_el = scope["bg_el"]
    control = scope["control"]
    knob = scope["knob"]
    root = scope["root"]
    print("[solve_slider_with_puzzle] Slider elements resolved successfully")

    # Solve puzzle (image space)
    bg_path = Path(imgs["background"])
    piece_path = Path(imgs["piece"])
    print(f"[solve_slider_with_puzzle] Background image: {bg_path}")
    print(f"[solve_slider_with_puzzle] Piece image: {piece_path}")

    puzzle_result_path = attempt_dir / "puzzle_fused_vis.jpg"

    print("[solve_slider_with_puzzle] Initializing PuzzleSolver...")
    solver = PuzzleSolver(
        gap_image_path=str(piece_path),
        bg_image_path=str(bg_path),
        output_image_path=str(puzzle_result_path),
    )
    x_piece, y_piece, score, best_scale, (tpl_w, tpl_h) = solver.discern_xy()
    print("[solve_slider_with_puzzle] Puzzle solved:")
    print(f"  - Position: ({x_piece}, {y_piece})")
    print(f"  - Score: {score}")
    print(f"  - Scale: {best_scale}")
    print(f"  - Template size: {tpl_w}x{tpl_h}")

    # Debug overlay
    print("[solve_slider_with_puzzle] Creating debug overlay...")
    render_puzzle_overlay(
        str(bg_path),
        (x_piece, y_piece),
        (tpl_w, tpl_h),
        attempt_dir / "match_overlay.jpg",
    )

    # Get DOM bounding boxes
    print("[solve_slider_with_puzzle] Getting element bounding boxes...")
    bg_bb = bg_el.bounding_box()
    ctrl_bb = control.bounding_box()
    knob_bb = knob.bounding_box()

    print("[solve_slider_with_puzzle] Bounding boxes:")
    print(f"  - Background: {bg_bb}")
    print(f"  - Control: {ctrl_bb}")
    print(f"  - Knob: {knob_bb}")

    if not bg_bb or not ctrl_bb or not knob_bb:
        print("[solve_slider_with_puzzle] ERROR: Bounding boxes are None!")
        raise RuntimeError("Slider elements not visible")

    # Load background image dimensions (same pixels as used in solver)
    print("[solve_slider_with_puzzle] Loading background image dimensions...")
    bg_img = Image.open(bg_path)
    bg_img_width = bg_img.width
    bg_img_height = bg_img.height
    print(
        f"[solve_slider_with_puzzle] Background dimensions: {bg_img_width}x{bg_img_height}"
    )

    # ============================================================
    # PRECISE COORDINATE MAPPING (tile-left -> knob travel)
    # ============================================================
    print("\n[solve_slider_with_puzzle] COORDINATE MAPPING:")
    print(f"{'-' * 70}")

    # Recover the puzzle slot LEFT X (backend's solution x) in image pixels.
    slot_left_x_img, puzzle_tile_w = _compute_slot_left_x(piece_path, x_piece, tpl_w)

    print("  [Slot Left X]")
    print(f"    x_piece (cropped match left) = {x_piece}")
    print(f"    puzzle_tile_w (image)        = {puzzle_tile_w}")
    print(f"    slot_left_x_img (tile-left)  = {slot_left_x_img:.2f}")

    # The tile can legally move in [0, bg_img_width - puzzle_tile_w]
    max_offset_img = max(1.0, float(bg_img_width - puzzle_tile_w))
    slot_offset_img = max(0.0, min(slot_left_x_img, max_offset_img))
    u_offset = slot_offset_img / max_offset_img

    print(f"  max_offset_img = {bg_img_width} - {puzzle_tile_w} = {max_offset_img:.2f}")
    print(f"  slot_offset_img (clamped)      = {slot_offset_img:.2f}")
    print(f"  u_offset = {slot_offset_img:.2f} / {max_offset_img:.2f} = {u_offset:.6f}")

    # Map to slider RAIL coordinates using knob travel (not full width).
    knob_bb = knob.bounding_box()
    if not knob_bb:
        raise RuntimeError("Knob not visible before drag")

    knob_w = knob_bb["width"]
    knob_h = knob_bb["height"]
    knob_half = knob_w / 2.0
    rail_x = ctrl_bb["x"]
    rail_w = ctrl_bb["width"]

    knob_travel = rail_w - knob_w
    target_x_screen = rail_x + knob_half + u_offset * knob_travel

    # Y is not used by the backend; we only keep the mouse on the rail visually.
    # For debugging, approximate a Y in the background box.
    target_y_screen = bg_bb["y"] + bg_bb["height"] / 2.0

    print(f"  rail_x = {rail_x}, rail_w = {rail_w}, knob_w = {knob_w}")
    print(f"  knob_travel = {rail_w} - {knob_w} = {knob_travel:.2f}")
    print(
        f"  target_x_screen = {rail_x} + {knob_half:.2f} + "
        f"{u_offset:.6f} * {knob_travel:.2f} = {target_x_screen:.2f}"
    )
    print(f"  target_y_screen (info) = {target_y_screen:.2f}")

    # Current knob center
    current_x = knob_bb["x"] + knob_half
    current_y = knob_bb["y"] + knob_h / 2.0

    distance_px = target_x_screen - current_x
    print(
        f"  distance_px (raw) = {target_x_screen:.2f} - {current_x:.2f} = {distance_px:.2f}"
    )
    print(f"{'-' * 70}\n")

    # Clamp knob center to rail bounds with a small margin
    margin = 4
    print(f"[solve_slider_with_puzzle] Clamping to rail bounds (margin={margin})...")
    left_limit = rail_x + knob_half + margin
    right_limit = rail_x + rail_w - knob_half - margin
    unclamped_target_x = current_x + distance_px
    clamped_target_x = max(left_limit, min(unclamped_target_x, right_limit))

    if clamped_target_x != unclamped_target_x:
        print(f"  Clamped from {unclamped_target_x:.2f} to {clamped_target_x:.2f}")

    distance_px = clamped_target_x - current_x
    print(f"  distance_px (clamped) = {distance_px:.2f}")

    # Create diagram (use slot center just for visualization)
    slot_center_img_x = slot_left_x_img + puzzle_tile_w / 2.0
    print("[solve_slider_with_puzzle] Creating movement diagram...")
    _create_movement_diagram(
        puzzle_result_path,
        x_piece,
        y_piece,
        tpl_w,
        tpl_h,
        slot_center_img_x,  # center of TILE in image space (visual only)
        current_x,
        clamped_target_x,
        distance_px,
        ctrl_bb["x"],
        ctrl_bb["width"],
        attempt_dir,
        bg_img_width=bg_img_width,
    )

    # ----------------------------------------------------------------
    # Save metadata (purely for offline analysis / tuning)
    # ----------------------------------------------------------------
    # For completeness, define a vertical center in image coordinates,
    # though it is not used by the solver or the backend.
    piece_center_y_img = y_piece + tpl_h / 2.0
    u_x = slot_center_img_x / float(bg_img_width)
    u_y = piece_center_y_img / float(bg_img_height)

    print("[solve_slider_with_puzzle] Saving metadata...")
    metadata = {
        "puzzle_result": {
            "x": x_piece,
            "y": y_piece,
            "score": score,
            "scale": best_scale,
            "template_size": [tpl_w, tpl_h],
        },
        "piece_center": {
            "x_image": float(slot_center_img_x),
            "y_image": float(piece_center_y_img),
        },
        "bg_image_dimensions": [bg_img_width, bg_img_height],
        "unitless_ratios": {"u_x": float(u_x), "u_y": float(u_y)},
        "target_screen": {
            "x": float(clamped_target_x),
            "y_background": float(target_y_screen),
        },
        "knob_current": {"x": float(current_x), "y": float(current_y)},
        "distance_to_move": float(distance_px),
        "rail_bounds_x": [float(left_limit), float(right_limit)],
        "drag_y": float(current_y),
    }
    (attempt_dir / "meta.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    print("[solve_slider_with_puzzle] Metadata saved")

    # ============================================================
    # EXECUTE DRAG WITH HUMAN-LIKE MOVEMENT
    # ============================================================
    print("\n[solve_slider_with_puzzle] EXECUTING DRAG MOVEMENT:")
    print(f"{'-' * 70}")
    print(f"[solve_slider_with_puzzle] Starting: ({current_x}, {current_y})")
    print(f"[solve_slider_with_puzzle] Target X: {clamped_target_x}")
    print("[solve_slider_with_puzzle] Using randomized human-like movement")

    # Initial pause (humans don't click instantly)
    page.wait_for_timeout(random.randint(50, 150))

    page.mouse.move(current_x, current_y)
    page.mouse.down()
    print("[solve_slider_with_puzzle] Mouse down")

    x_cur = current_x
    int_distance = int(round(distance_px))
    movement_path = _human_track(int_distance)
    print(f"[solve_slider_with_puzzle] Movement path: {len(movement_path)} steps")

    # Execute movement with precise tracking
    for step_idx, dx in enumerate(movement_path):
        x_cur += dx

        # Stay exactly on rail Y - no vertical variation
        page.mouse.move(x_cur, current_y, steps=1)

        # Minimal random pauses (0-3ms) to appear human but maintain speed
        if step_idx % random.randint(8, 12) == 0:
            page.wait_for_timeout(random.randint(0, 3))

        if step_idx % 8 == 0:
            print(f"  Step {step_idx}: x={x_cur:.1f}, dx={dx}")

    print(f"[solve_slider_with_puzzle] Final: x={x_cur}, y={current_y}")
    print(f"[solve_slider_with_puzzle] Total moved: {x_cur - current_x:.1f}px")

    # Brief pause before release (humans don't release instantly)
    page.wait_for_timeout(random.randint(30, 80))
    page.mouse.up()
    print("[solve_slider_with_puzzle] Mouse up")
    print(f"{'-' * 70}\n")

    # Allow validation
    page.wait_for_timeout(250)

    # Check success
    print(
        f"[solve_slider_with_puzzle] Checking success (max {max_wait_success_ms}ms)..."
    )

    try:
        page.locator(success_selector).first.wait_for(
            timeout=max_wait_success_ms, state="visible"
        )
        print(f"[solve_slider_with_puzzle] SUCCESS via selector '{success_selector}'!")
        print(f"{'=' * 70}\n")
        return True
    except Exception as e:
        print(f"[solve_slider_with_puzzle] CSS selector not found: {e}")

    try:
        page.get_by_text(success_text).first.wait_for(
            timeout=max_wait_success_ms, state="visible"
        )
        print(f"[solve_slider_with_puzzle] SUCCESS via text '{success_text}'!")
        print(f"{'=' * 70}\n")
        return True
    except Exception as e:
        print(f"[solve_slider_with_puzzle] Text fallback not found: {e}")

    try:
        root.wait_for(state="hidden", timeout=1500)
        print("[solve_slider_with_puzzle] Tentative SUCCESS! Root disappeared")
        print(f"{'=' * 70}\n")
        return True
    except Exception as e:
        print(f"[solve_slider_with_puzzle] Root timeout: {e}")

    print("[solve_slider_with_puzzle] FAILED: Could not solve captcha")
    print(f"{'=' * 70}\n")
    return False
