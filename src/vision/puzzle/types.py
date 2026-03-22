from __future__ import annotations

from dataclasses import dataclass

import numpy as np

ImageArray = np.ndarray
GrayImage = np.ndarray
MaskImage = np.ndarray
FloatMap = np.ndarray

Point = tuple[int, int]
PointF = tuple[float, float]
Box = tuple[int, int, int, int]
TemplateSize = tuple[int, int]
YRoi = tuple[int, int] | None


@dataclass(slots=True)
class Candidate:
    loc: Point
    match_score: float = 0.0
    complexity: float = 0.0
    combined_score: float = 0.0
    final_score: float | None = None
    template_score: float = 0.0
    gradient_score: float = 0.0
    chamfer_score: float = 0.0
    edge_iou: float = 0.0
    orb_score: float = 0.0
    orb_iou: float = 0.0
    confidence: float = 0.0


@dataclass(slots=True)
class OrbMatch:
    loc: Point
    bbox: Box
    inliers: int
    matches: int
    score: float
