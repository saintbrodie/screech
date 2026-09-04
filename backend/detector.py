from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

from .config import Settings


@dataclass
class Detection:
    xyxy: tuple[float, float, float, float]
    confidence: float
    area_ratio: float


@dataclass
class DetectionSummary:
    hawk_count: int
    identity: str
    behavior: str
    confidence: float | None
    detections: list[Detection]
    raw_status: str


class HawkDetector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model: YOLO | None = None
        self.cy_history: deque[float] = deque(maxlen=settings.behavior_history)

    def load(self) -> None:
        self.model = YOLO(self.settings.model_path)

    def _identity(self, area_ratio: float) -> str:
        if self.settings.identity_mode != "size":
            return "unknown"

        lower = self.settings.female_area_ratio - self.settings.identity_deadband
        upper = self.settings.female_area_ratio + self.settings.identity_deadband
        if area_ratio >= upper:
            return "freya"
        if area_ratio <= lower:
            return "finn"
        return "unknown"

    def analyze(self, frame: np.ndarray) -> DetectionSummary:
        if self.model is None:
            raise RuntimeError("Detector model is not loaded")

        results = self.model.predict(
            frame,
            classes=[14],
            conf=self.settings.detector_confidence,
            verbose=False,
        )
        boxes = results[0].boxes
        height, width = frame.shape[:2]
        frame_area = float(height * width)

        detections: list[Detection] = []
        for box in boxes:
            xyxy = box.xyxy[0].cpu().numpy().astype(float)
            area = max(0.0, (xyxy[2] - xyxy[0]) * (xyxy[3] - xyxy[1]))
            area_ratio = area / frame_area
            if area_ratio < self.settings.min_box_area_ratio:
                continue
            confidence = float(box.conf[0].cpu().item()) if box.conf is not None else 0.0
            detections.append(
                Detection(
                    tuple(float(v) for v in xyxy),
                    confidence,
                    float(area_ratio),
                )
            )

        hawk_count = len(detections)
        confidence = max((d.confidence for d in detections), default=None)
        identity = "unknown"
        behavior = "Unknown"

        if hawk_count > 0:
            behavior = "Incubating / Resting"

        if hawk_count == 1:
            detection = detections[0]
            identity = self._identity(detection.area_ratio)
            _, y1, _, y2 = detection.xyxy
            cy_ratio = ((y1 + y2) / 2.0) / float(height)
            self.cy_history.append(cy_ratio)

            if len(self.cy_history) >= 2:
                movement = float(np.std(np.asarray(self.cy_history)))
                if movement >= self.settings.movement_stddev_ratio:
                    behavior = "Active / Moving"
        else:
            self.cy_history.clear()

        if hawk_count == 0:
            raw_status = "No hawk detected in latest scan"
        elif hawk_count >= 2:
            raw_status = f"{hawk_count} birds detected in latest scan"
        elif identity == "freya":
            raw_status = "Latest scan resembles Freya (size heuristic)"
        elif identity == "finn":
            raw_status = "Latest scan resembles Finn (size heuristic)"
        else:
            raw_status = "One hawk detected; identity uncertain"

        return DetectionSummary(
            hawk_count=hawk_count,
            identity=identity,
            behavior=behavior,
            confidence=confidence,
            detections=detections,
            raw_status=raw_status,
        )

    @staticmethod
    def annotate(frame: np.ndarray, summary: DetectionSummary) -> np.ndarray:
        annotated = frame.copy()
        for detection in summary.detections:
            x1, y1, x2, y2 = (int(v) for v in detection.xyxy)
            label = f"bird {detection.confidence:.2f}"
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(
                annotated,
                label,
                (x1, max(20, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
        return annotated

    @staticmethod
    def save_image(path: Path, frame: np.ndarray) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(path), frame):
            raise RuntimeError(f"Could not write image to {path}")

    def save_crops(self, base_name: str, frame: np.ndarray, summary: DetectionSummary, directory: Path) -> list[Path]:
        saved: list[Path] = []
        height, width = frame.shape[:2]
        for index, detection in enumerate(summary.detections, start=1):
            x1, y1, x2, y2 = (int(v) for v in detection.xyxy)
            x1 = max(0, min(width - 1, x1))
            x2 = max(1, min(width, x2))
            y1 = max(0, min(height - 1, y1))
            y2 = max(1, min(height, y2))
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            path = directory / f"{base_name}_{index}.jpg"
            self.save_image(path, crop)
            saved.append(path)
        return saved
