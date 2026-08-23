from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from playwright.sync_api import Locator


class BoundingBox(TypedDict):
    x: float
    y: float
    width: float
    height: float


@dataclass(slots=True)
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
    success_poll_interval_ms: int = 100

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
    run_id: str = ""
    operator_id: str = ""
    nik: str = ""


@dataclass(slots=True)
class SliderElements:
    """Container for slider DOM elements."""

    root: Locator
    bg_el: Locator
    control: Locator
    knob: Locator


@dataclass(slots=True)
class BoundingBoxes:
    """Bounding boxes for slider elements."""

    bg: BoundingBox
    control: BoundingBox
    knob: BoundingBox


@dataclass(slots=True)
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
    rail_limits: tuple[float, float]


PuzzleResult = tuple[int, int, float, float, tuple[int, int]]
