from __future__ import annotations

from src.pipelines.slider.types import SliderConfig


class MovementGenerator:
    """Generates human-like movement paths."""

    def __init__(self, config: SliderConfig) -> None:
        self.config = config

    def generate_path(self, distance_px: int) -> list[int]:
        """Generate smooth movement path with easing."""
        sign = 1 if distance_px >= 0 else -1
        abs_dist = abs(distance_px)

        steps = self._calculate_steps(abs_dist)
        return self._build_path(abs_dist, steps, sign)

    def _calculate_steps(self, distance: int) -> int:
        return max(
            self.config.min_steps,
            min(
                self.config.max_steps,
                distance // self.config.step_divisor + self.config.step_base,
            ),
        )

    def _build_path(self, distance: int, steps: int, sign: int) -> list[int]:
        path: list[int] = []
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

        return path

    @staticmethod
    def _ease_out_quad(t: float) -> float:
        return 1 - (1 - t) * (1 - t)
