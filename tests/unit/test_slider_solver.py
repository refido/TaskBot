from pathlib import Path
from types import SimpleNamespace

import src.pipelines.slider.solver as slider_solver_module
from src.pipelines.slider.solver import SliderSolver, solve_slider_with_puzzle
from src.pipelines.slider.types import CoordinateMapping, SliderConfig


class FakeBoxLocator:
    def __init__(self, box):
        self._box = box

    def bounding_box(self):
        return self._box


class FakeElementResolver:
    def resolve(self, page):
        return SimpleNamespace(
            root=object(),
            bg_el=FakeBoxLocator({"x": 0, "y": 0, "width": 300, "height": 150}),
            control=FakeBoxLocator({"x": 10, "y": 170, "width": 280, "height": 30}),
            knob=FakeBoxLocator({"x": 20, "y": 175, "width": 20, "height": 20}),
        )


class FakeCoordinateMapper:
    def map_coordinates(self, *args, **kwargs):
        return CoordinateMapping(
            slot_left_x_img=80.0,
            puzzle_tile_width=40,
            target_x_screen=100.0,
            target_y_screen=100.0,
            current_x=20.0,
            current_y=180.0,
            distance_px=80.0,
            clamped_target_x=100.0,
            rail_limits=(10.0, 290.0),
        )


class FakeDragExecutor:
    def __init__(self):
        self.calls = 0

    def execute_drag(self, page, mapping):
        self.calls += 1


class FakeSuccessDetector:
    def check_success(self, page, root):
        return True


def test_solve_slider_with_precomputed_result_skips_internal_puzzle_solve(monkeypatch):
    class FailIfPuzzleSolverConstructed:
        def __init__(self, **kwargs):
            raise AssertionError("precomputed puzzle_result should skip PuzzleSolver")

    monkeypatch.setattr(
        slider_solver_module, "PuzzleSolver", FailIfPuzzleSolverConstructed
    )

    solver = SliderSolver(SliderConfig(write_debug_artifacts=False))
    solver.element_resolver = FakeElementResolver()
    solver.coord_mapper = FakeCoordinateMapper()
    solver.drag_executor = FakeDragExecutor()
    solver.success_detector = FakeSuccessDetector()
    solver._get_image_dimensions = lambda bg_path: (300, 150)

    solved = solver.solve(
        page=object(),
        imgs={"background": Path("bg.png"), "piece": Path("piece.png")},
        puzzle_result=(80, 20, 0.98, 1.0, (40, 40)),
    )

    assert solved is True
    assert solver.drag_executor.calls == 1


def test_solve_slider_with_puzzle_forwards_precomputed_result(monkeypatch):
    captured = {}

    class FakeSolver:
        def __init__(self, config):
            captured["write_debug_artifacts"] = config.write_debug_artifacts

        def solve(self, page, imgs, *, puzzle_result=None, puzzle_result_path=None):
            captured["puzzle_result"] = puzzle_result
            captured["puzzle_result_path"] = puzzle_result_path
            return True

    monkeypatch.setattr(slider_solver_module, "SliderSolver", FakeSolver)

    result = solve_slider_with_puzzle(
        page=object(),
        imgs={"background": Path("bg.png"), "piece": Path("piece.png")},
        puzzle_result=(80, 20, 0.98, 1.0, (40, 40)),
        puzzle_result_path=Path("result.jpg"),
        write_debug_artifacts=True,
    )

    assert result is True
    assert captured == {
        "write_debug_artifacts": True,
        "puzzle_result": (80, 20, 0.98, 1.0, (40, 40)),
        "puzzle_result_path": Path("result.jpg"),
    }


def test_debug_disabled_internal_solve_does_not_require_output_path(monkeypatch):
    captured = {}

    class FakePuzzleSolver:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.timing_metrics = {"total": 4.2}

        def discern_xy(self):
            return (80, 20, 0.98, 1.0, (40, 40))

    monkeypatch.setattr(slider_solver_module, "PuzzleSolver", FakePuzzleSolver)

    solver = SliderSolver(SliderConfig(write_debug_artifacts=False))
    solver.element_resolver = FakeElementResolver()
    solver.coord_mapper = FakeCoordinateMapper()
    solver.drag_executor = FakeDragExecutor()
    solver.success_detector = FakeSuccessDetector()
    solver._get_image_dimensions = lambda bg_path: (300, 150)

    solved = solver.solve(
        page=object(),
        imgs={"background": Path("bg.png"), "piece": Path("piece.png")},
    )

    assert solved is True
    assert captured["output_image_path"] is None
    assert solver.drag_executor.calls == 1
