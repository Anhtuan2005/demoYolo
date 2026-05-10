"""
YOLOv11 Detection Engine — Phát hiện đối tượng nguy hiểm.

Sử dụng YOLOv11 để phát hiện:
- Người (person)
- Vũ khí (knife, scissors)
"""
import logging
from ultralytics import YOLO
import numpy as np
import torch

import config

logger = logging.getLogger(__name__)


class ThreatDetector:
    """Engine phát hiện đối tượng nguy hiểm sử dụng YOLOv11."""

    def __init__(self, model_path: str = None, confidence: float = None):
        self.model_path = model_path or config.MODEL_DETECT
        self.confidence = confidence or config.CONFIDENCE_THRESHOLD
        self.model = None
        self._use_half = False
        self._load_model()

    def _load_model(self):
    logger.info(f"Loading detection model: {self.model_path}")
    try:
        self.model = YOLO(self.model_path)
        self.weapon_model = YOLO(config.MODEL_WEAPONS)  # ← thêm dòng này

        if torch.cuda.is_available():
            self._use_half = True
        else:
            self._use_half = False

        logger.info(f"✅ Models loaded | Device: {self.model.device}")
    except Exception as e:
        logger.error(f"❌ Failed to load model: {e}")
        raise

    def detect(self, frame: np.ndarray) -> dict:
        """
        Phát hiện đối tượng trong frame.

        Args:
            frame: BGR image (numpy array)

        Returns:
            dict với keys:
                - persons: list[dict] — thông tin người phát hiện được
                - weapons: list[dict] — thông tin vũ khí phát hiện được
                - raw_results: ultralytics Results object
        """
        results = self.model(
            frame,
            conf=self.confidence,
            iou=config.IOU_THRESHOLD,
            classes=config.TARGET_CLASSES,
            verbose=False,
            half=self._use_half,
            imgsz=640,
        )

        result = results[0]
        persons = []
        weapons = []

        if result.boxes is not None and len(result.boxes) > 0:
            boxes = result.boxes.xyxy.cpu().numpy()
            confidences = result.boxes.conf.cpu().numpy()
            class_ids = result.boxes.cls.cpu().numpy().astype(int)

            for i, (box, conf, cls_id) in enumerate(zip(boxes, confidences, class_ids)):
                x1, y1, x2, y2 = int(box[0]), int(box[1]), int(box[2]), int(box[3])
                detection = {
                    "bbox": (x1, y1, x2, y2),
                    "confidence": float(conf),
                    "class_id": int(cls_id),
                    "center": (int((x1 + x2) / 2), int((y1 + y2) / 2)),
                }

                if cls_id == config.PERSON_CLASS:
                    detection["label"] = "person"
                    persons.append(detection)
                elif cls_id in config.WEAPON_CLASSES:
                    detection["label"] = config.WEAPON_CLASSES[cls_id]
                    weapons.append(detection)

        return {
            "persons": persons,
            "weapons": weapons,
            "raw_results": result,
        }

    def detect_with_tracking(self, frame: np.ndarray, tracker_config: str = None) -> dict:
        """
        Phát hiện + tracking sử dụng BoTSORT với Re-ID.

        Args:
            frame: BGR image
            tracker_config: đường dẫn file cấu hình tracker

        Returns:
            dict với tracked objects
        """
        tracker = tracker_config or config.TRACKER_CONFIG

        results = self.model.track(
            frame,
            conf=self.confidence,
            iou=config.IOU_THRESHOLD,
            classes=config.TARGET_CLASSES,
            tracker=tracker,
            persist=True,
            verbose=False,
            half=self._use_half,
            imgsz=640,
        )

        result = results[0]
        persons = []
        weapons = []

        if result.boxes is not None and len(result.boxes) > 0:
            boxes = result.boxes.xyxy.cpu().numpy()
            confidences = result.boxes.conf.cpu().numpy()
            class_ids = result.boxes.cls.cpu().numpy().astype(int)
            track_ids = (
                result.boxes.id.cpu().numpy().astype(int)
                if result.boxes.id is not None
                else [None] * len(boxes)
            )

            for box, conf, cls_id, trk_id in zip(boxes, confidences, class_ids, track_ids):
                x1, y1, x2, y2 = int(box[0]), int(box[1]), int(box[2]), int(box[3])
                detection = {
                    "bbox": (x1, y1, x2, y2),
                    "confidence": float(conf),
                    "class_id": int(cls_id),
                    "track_id": int(trk_id) if trk_id is not None else None,
                    "center": (int((x1 + x2) / 2), int((y1 + y2) / 2)),
                }

                if cls_id == config.PERSON_CLASS:
                    detection["label"] = "person"
                    persons.append(detection)
                elif cls_id in config.WEAPON_CLASSES:
                    detection["label"] = config.WEAPON_CLASSES[cls_id]
                    weapons.append(detection)

        return {
            "persons": persons,
            "weapons": weapons,
            "raw_results": result,
        }
