from __future__ import annotations

import random

from playwright.sync_api import Page

from src.pipelines.slider.movement import MovementGenerator
from src.pipelines.slider.types import CoordinateMapping, SliderConfig


class DragExecutor:
    """Executes drag movement on page."""

    def __init__(self, config: SliderConfig, movement_gen: MovementGenerator) -> None:
        self.config = config
        self.movement_gen = movement_gen

    def execute_drag(self, page: Page, mapping: CoordinateMapping) -> None:
        """Execute drag movement with human-like behavior."""
        page.wait_for_timeout(
            random.randint(self.config.initial_pause_min, self.config.initial_pause_max)
        )

        page.mouse.move(mapping.current_x, mapping.current_y)
        page.mouse.down()

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

        page.wait_for_timeout(
            random.randint(self.config.release_pause_min, self.config.release_pause_max)
        )
        page.mouse.up()
        page.wait_for_timeout(self.config.validation_wait)
