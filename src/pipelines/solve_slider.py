import json
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Dict

from PIL import Image
from playwright.sync_api import Page

from src.vision.overlay import render_puzzle_overlay
from src.vision.puzzle_solver import PuzzleSolver


def _human_track(distance_px: int) -> list[int]:
    """Human-like easing with jitter and micro-corrections."""

    def ease_out_quad(t: float) -> float:
        return 1 - (1 - t) * (1 - t)

    steps, overshoot = 28, 6
    last, path = 0.0, []
    for i in range(1, steps + 1):
        t = i / steps
        target = distance_px * ease_out_quad(t)
        move = (target - last) + random.uniform(-0.6, 0.6)
        last += move
        path.append(int(round(move)))
    path += [overshoot, -overshoot // 2, overshoot // 3, -1]
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
    bg_el = page.locator(bg_selector).first
    bg_el.wait_for(state="visible", timeout=8000)

    root = None
    containers = page.locator(container_selector)
    if containers.count() > 0:
        try:
            root = containers.filter(has=bg_el).first
            _ = root.count()
        except Exception:
            root = None
    if root is None or (hasattr(root, "count") and root.count() == 0):
        root = bg_el.locator(
            "xpath=ancestor::div[contains(@class,'rc-slider-captcha')]"
        ).first

    control = root.locator(rail_selector).first
    if control.count() == 0:
        control = root.locator("div.rc-slider-captcha-control").first

    knob = root.locator(knob_selector).first
    if knob.count() == 0:
        knob = control.locator(
            "span.rc-slider-captcha-button.rc-slider-captcha-control-button"
        ).first

    try:
        root.scroll_into_view_if_needed(timeout=1000)
        root.hover()
        page.wait_for_timeout(120)
    except Exception:
        pass

    control.wait_for(state="visible", timeout=6000)
    try:
        knob.wait_for(state="visible", timeout=2000)
    except Exception:
        pass

    return {"root": root, "bg_el": bg_el, "control": control, "knob": knob}


def solve_slider_with_puzzle(
    page: Page,
    imgs: Dict[str, Path],
    *,
    success_selector: str = ".captcha-success, text=Berhasil",
    bias_px: float = 0.0,
    max_wait_success_ms: int = 3500,
    debug_root: str = "data_puzzle/puzzle_debug/",
) -> bool:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    attempt_dir = Path(debug_root) / ts
    attempt_dir.mkdir(parents=True, exist_ok=True)

    scope = _resolve_slider_scope(page)
    bg_el, control, knob, root = (
        scope["bg_el"],
        scope["control"],
        scope["knob"],
        scope["root"],
    )

    bg_path = Path(imgs["background"])
    piece_path = Path(imgs["piece"])

    # Run a single, authoritative match
    solver = PuzzleSolver(
        gap_image_path=str(piece_path),
        bg_image_path=str(bg_path),
        output_image_path=str(attempt_dir / "puzzle_fused_vis.jpg"),
    )
    x, y, score, best_scale, (tpl_w, tpl_h) = solver.discern_xy()

    # Debug overlay aligned with solver geometry
    render_puzzle_overlay(
        str(bg_path), (x, y), (tpl_w, tpl_h), attempt_dir / "match_overlay.jpg"
    )

    # Convert to CSS pixels for dragging
    bg_img = Image.open(bg_path)
    bg_bb = bg_el.bounding_box()
    ctrl_bb = control.bounding_box()
    if not bg_bb or not ctrl_bb:
        raise RuntimeError("Slider background/control is not visible.")
    scale_css_per_img = bg_bb["width"] / float(bg_img.width)

    knob_bb = knob.bounding_box() if knob.count() > 0 else None
    if knob_bb:
        start_x = knob_bb["x"] + knob_bb["width"] / 2.0
        start_y = knob_bb["y"] + knob_bb["height"] / 2.0
    else:
        start_x = ctrl_bb["x"] + 12
        start_y = ctrl_bb["y"] + ctrl_bb["height"] / 2.0

    # Use the matched template width (not the raw piece width) for center
    piece_center_image_px = x + (tpl_w / 2.0)
    piece_center_css_px = piece_center_image_px * scale_css_per_img
    target_x = bg_bb["x"] + piece_center_css_px + float(bias_px)

    # Clamp to rail
    margin = 4
    left_bound = ctrl_bb["x"] + margin
    right_bound = ctrl_bb["x"] + ctrl_bb["width"] - margin
    target_x = max(left_bound, min(right_bound, target_x))

    # Persist geometry
    (attempt_dir / "meta.json").write_text(
        json.dumps(
            {
                "x": x,
                "y": y,
                "score": score,
                "best_scale": best_scale,
                "tpl_w": tpl_w,
                "tpl_h": tpl_h,
                "scale_css_per_img": float(scale_css_per_img),
                "start_x_css": float(start_x),
                "start_y_css": float(start_y),
                "target_x_css": float(target_x),
                "distance_css_px": int(round(target_x - start_x)),
                "rail_bounds_css": [float(left_bound), float(right_bound)],
                "bias_px": float(bias_px),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Drag with human-like micro-jitter
    page.mouse.move(start_x, start_y)
    page.mouse.down()
    x_cur = start_x
    for dx in _human_track(int(round(target_x - start_x))):
        x_cur += dx
        page.mouse.move(x_cur, start_y + random.randint(-1, 1), steps=2)
        time.sleep(random.uniform(0.01, 0.03))
    page.mouse.up()

    # Success checks + small nudges
    try:
        page.locator(success_selector).first.wait_for(timeout=max_wait_success_ms)
        return True
    except Exception:
        pass
    try:
        root.wait_for(state="hidden", timeout=1200)
        return True
    except Exception:
        for adjust in (4, -6):
            page.mouse.move(x_cur, start_y)
            page.mouse.down()
            page.mouse.move(x_cur + adjust, start_y, steps=2)
            page.mouse.up()
            try:
                page.locator(success_selector).first.wait_for(timeout=1200)
                return True
            except Exception:
                continue
        return False
