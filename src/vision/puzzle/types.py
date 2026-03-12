from __future__ import annotations

from dataclasses import dataclass

import numpy as np

ImageArray = np.ndarray
GrayImage = np.ndarray
MaskImage = np.ndarray
FloatMap = np.ndarray

Point = tuple[int, int]
PointF = tuple[float, float]
TemplateSize = tuple[int, int]
YRoi = tuple[int, int] | None


@dataclass(slots=True)
class Candidate:
    loc: Point
    match_score: float
    complexity: float
    combined_score: float
    final_score: float | None = None
