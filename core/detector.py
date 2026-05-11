"""
YOLOv11 Detection Engine — Phát hiện đối tượng nguy hiểm.

Sử dụng 2 model song song:
- Model COCO (yolo11n.pt)   → phát hiện person (class 0) + knife (class 43)
- Model Custom (best.pt)    → phát hiện scissors (class 0)
"""
import logging
from ultralytics import YOLO
import numpy as np
import torch

import config

logger = logging.getLogger(__name__)


class ThreatDetector:
    """Engine phát hiện đối tượng nguy hiểm sử dụng YOLOv11 (dual model)."""

    def __init__(self, model_path: str = None, confidence: float = None):
        self.model_path = model_path or config.MODEL_DETECT
        self.custom_model_path = getattr(config, "MODEL_DETECT_CUSTOM", None)
        self.confidence = confidence or config.CONFIDENCE_THRESHOLD
        self.model = None         # COCO model: person + knife
        self.model_custom = None  # Custom model: scissors
        self._use_half = False
        self._load_model()

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _load_model(self):
        """Load cả 2 model. Tự động dùng GPU + FP16 nếu có."""
        try:
            # --- Model 1: COCO (person + knife) ---
            logger.info(f"Loading COCO model: {self.model_path}")
            self.model = YOLO(self.model_path)

            if torch.cuda.is_available():
                self._use_half = True
                logger.info("✅ COCO model loaded | GPU + FP16")
            else:
                logger.info("✅ COCO model loaded | CPU")

            # --- Model 2: Custom (scissors) ---
            if self.custom_model_path:
                logger.info(f"Loading custom scissors model: {self.custom_model_path}")
                self.model_custom = YOLO(self.custom_model_path)
                logger.info("✅ Custom scissors model loaded")
            else:
                logger.warning("⚠️  MODEL_DETECT_CUSTOM not set in config — scissors detection disabled")

        except Exception as e:
            logger.error(f"❌ Failed to load model: {e}")
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_coco_boxes(self, result, persons: list, weapons: list):
        """Parse kết quả từ COCO model → person & knife."""
        if result.boxes is None or len(result.boxes) == 0:
            return

        boxes       = result.boxes.xyxy.cpu().numpy()
        confidences = result.boxes.conf.cpu().numpy()
        class_ids   = result.boxes.cls.cpu().numpy().astype(int)

        for box, conf, cls_id in zip(boxes, confidences, class_ids):
            x1, y1, x2, y2 = int(box[0]), int(box[1]), int(box[2]), int(box[3])
            det = {
                "bbox":       (x1, y1, x2, y2),
                "confidence": float(conf),
                "class_id":   int(cls_id),
                "center":     (int((x1 + x2) / 2), int((y1 + y2) / 2)),
            }

            if cls_id == 0:   # person
                det["label"] = "person"
                persons.append(det)
            elif cls_id == 43:  # knife
                det["label"] = "knife"
                weapons.append(det)

    def _parse_coco_boxes_tracked(self, result, persons: list, weapons: list):
        """Parse kết quả tracking từ COCO model → person & knife (có track_id)."""
        if result.boxes is None or len(result.boxes) == 0:
            return

        boxes       = result.boxes.xyxy.cpu().numpy()
        confidences = result.boxes.conf.cpu().numpy()
        class_ids   = result.boxes.cls.cpu().numpy().astype(int)
        track_ids   = (
            result.boxes.id.cpu().numpy().astype(int)
            if result.boxes.id is not None
            else [None] * len(boxes)
        )

        for box, conf, cls_id, trk_id in zip(boxes, confidences, class_ids, track_ids):
            x1, y1, x2, y2 = int(box[0]), int(box[1]), int(box[2]), int(box[3])
            det = {
                "bbox":       (x1, y1, x2, y2),
                "confidence": float(conf),
                "class_id":   int(cls_id),
                "track_id":   int(trk_id) if trk_id is not None else None,
                "center":     (int((x1 + x2) / 2), int((y1 + y2) / 2)),
            }

            if cls_id == 0:   # person
                det["label"] = "person"
                persons.append(det)
            elif cls_id == 43:  # knife
                det["label"] = "knife"
                weapons.append(det)

    def _parse_scissors_boxes(self, result, weapons: list):
        """Parse kết quả từ custom model → scissors (class 0 trong model custom)."""
        if result.boxes is None or len(result.boxes) == 0:
            return

        boxes       = result.boxes.xyxy.cpu().numpy()
        confidences = result.boxes.conf.cpu().numpy()

        for box, conf in zip(boxes, confidences):
            x1, y1, x2, y2 = int(box[0]), int(box[1]), int(box[2]), int(box[3])
            weapons.append({
                "bbox":       (x1, y1, x2, y2),
                "confidence": float(conf),
                "class_id":   76,        # giữ COCO class ID 76 để tương thích với threat_analyzer
                "center":     (int((x1 + x2) / 2), int((y1 + y2) / 2)),
                "label":      "scissors",
            })

    def _parse_scissors_boxes_tracked(self, result, weapons: list):
        """Parse kết quả tracking từ custom model → scissors (có track_id)."""
        if result.boxes is None or len(result.boxes) == 0:
            return

        boxes       = result.boxes.xyxy.cpu().numpy()
        confidences = result.boxes.conf.cpu().numpy()
        track_ids   = (
            result.boxes.id.cpu().numpy().astype(int)
            if result.boxes.id is not None
            else [None] * len(boxes)
        )

        for box, conf, trk_id in zip(boxes, confidences, track_ids):
            x1, y1, x2, y2 = int(box[0]), int(box[1]), int(box[2]), int(box[3])
            weapons.append({
                "bbox":       (x1, y1, x2, y2),
                "confidence": float(conf),
                "class_id":   76,        # giữ COCO class ID 76 để tương thích với threat_analyzer
                "track_id":   int(trk_id) if trk_id is not None else None,
                "center":     (int((x1 + x2) / 2), int((y1 + y2) / 2)),
                "label":      "scissors",
            })

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, frame: np.ndarray) -> dict:
        """
        Phát hiện đối tượng trong frame (không tracking — dùng cho ảnh đơn).

        Args:
            frame: BGR image (numpy array)

        Returns:
            dict:
                - persons:     list[dict]
                - weapons:     list[dict]  (knife + scissors gộp chung)
                - raw_results: ultralytics Results object (từ COCO model)
        """
        persons: list = []
        weapons: list = []

        # --- Model 1: COCO → person + knife ---
        results_coco = self.model(
            frame,
            conf=self.confidence,
            iou=config.IOU_THRESHOLD,
            classes=[0, 43],          # person, knife
            verbose=False,
            half=self._use_half,
            imgsz=640,
        )
        result_coco = results_coco[0]
        self._parse_coco_boxes(result_coco, persons, weapons)

        # --- Model 2: Custom → scissors ---
        if self.model_custom is not None:
            results_custom = self.model_custom(
                frame,
                conf=self.confidence,
                iou=config.IOU_THRESHOLD,
                classes=[0],          # scissors
                verbose=False,
                half=self._use_half,
                imgsz=640,
            )
            self._parse_scissors_boxes(results_custom[0], weapons)

        return {
            "persons":     persons,
            "weapons":     weapons,
            "raw_results": result_coco,
        }

    def detect_with_tracking(self, frame: np.ndarray, tracker_config: str = None) -> dict:
        """
        Phát hiện + tracking sử dụng BoTSORT với Re-ID (dùng cho video/webcam).

        Args:
            frame:          BGR image
            tracker_config: đường dẫn file cấu hình tracker

        Returns:
            dict với tracked objects (có track_id)
        """
        tracker = tracker_config or config.TRACKER_CONFIG

        persons: list = []
        weapons: list = []

        # --- Model 1: COCO → person + knife (có tracking) ---
        results_coco = self.model.track(
            frame,
            conf=self.confidence,
            iou=config.IOU_THRESHOLD,
            classes=[0, 43],          # person, knife
            tracker=tracker,
            persist=True,
            verbose=False,
            half=self._use_half,
            imgsz=640,
        )
        result_coco = results_coco[0]
        self._parse_coco_boxes_tracked(result_coco, persons, weapons)

        # --- Model 2: Custom → scissors (có tracking) ---
        if self.model_custom is not None:
            results_custom = self.model_custom.track(
                frame,
                conf=self.confidence,
                iou=config.IOU_THRESHOLD,
                classes=[0],          # scissors
                tracker=tracker,
                persist=True,
                verbose=False,
                half=self._use_half,
                imgsz=640,
            )
            self._parse_scissors_boxes_tracked(results_custom[0], weapons)

        return {
            "persons":     persons,
            "weapons":     weapons,
            "raw_results": result_coco,
        }