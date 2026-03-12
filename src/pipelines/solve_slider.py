"""
Backward-compatible slider pipeline exports.

Implementation lives under `src.pipelines.slider`.
"""

from src.pipelines.slider.artifacts import DiagramCreator, MetadataWriter
from src.pipelines.slider.coordinates import CoordinateMapper
from src.pipelines.slider.elements import ElementResolver
from src.pipelines.slider.execution import DragExecutor
from src.pipelines.slider.mask import MaskProcessor
from src.pipelines.slider.movement import MovementGenerator
from src.pipelines.slider.solver import SliderSolver, solve_slider_with_puzzle
from src.pipelines.slider.success import SuccessDetector
from src.pipelines.slider.types import (
    BoundingBoxes,
    CoordinateMapping,
    SliderConfig,
    SliderElements,
)

__all__ = [
    "BoundingBoxes",
    "CoordinateMapper",
    "CoordinateMapping",
    "DiagramCreator",
    "DragExecutor",
    "ElementResolver",
    "MaskProcessor",
    "MetadataWriter",
    "MovementGenerator",
    "SliderConfig",
    "SliderElements",
    "SliderSolver",
    "SuccessDetector",
    "solve_slider_with_puzzle",
]
