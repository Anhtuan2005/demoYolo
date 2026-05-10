"""
Pose Analyzer — Phân tích tư thế nguy hiểm với YOLOv11-Pose.
"""
import logging
import math
import numpy as np
import torch
from ultralytics import YOLO
import config

logger = logging.getLogger(__name__)

# COCO Pose keypoint indices
NOSE, L_EYE, R_EYE = 0, 1, 2
L_EAR, R_EAR = 3, 4
L_SHOULDER, R_SHOULDER = 5, 6
L_ELBOW, R_ELBOW = 7, 8
L_WRIST, R_WRIST = 9, 10
L_HIP, R_HIP = 11, 12
L_KNEE, R_KNEE = 13, 14
L_ANKLE, R_ANKLE = 15, 16


def angle_between(p1, p2, p3):
    """Tính góc tại p2 giữa 3 điểm (degree)."""
    v1 = (p1[0] - p2[0], p1[1] - p2[1])
    v2 = (p3[0] - p2[0], p3[1] - p2[1])
    dot = v1[0]*v2[0] + v1[1]*v2[1]
    mag1 = math.sqrt(v1[0]**2 + v1[1]**2)
    mag2 = math.sqrt(v2[0]**2 + v2[1]**2)
    if mag1 * mag2 == 0:
        return 0
    cos_angle = max(-1, min(1, dot / (mag1 * mag2)))
    return math.degrees(math.acos(cos_angle))


class PoseAnalyzer:
    def __init__(self):
        self.model = None
        self._use_half = torch.cuda.is_available()
        self._load_model()

    def _load_model(self):
        logger.info(f"Loading pose model: {config.MODEL_POSE}")
        try:
            self.model = YOLO(config.MODEL_POSE)
            logger.info(f"✅ Pose model loaded: {config.MODEL_POSE} | {'GPU+FP16' if self._use_half else 'CPU'}")
        except Exception as e:
            logger.error(f"❌ Failed to load pose model: {e}")
            self.model = None

    def analyze(self, frame, persons=None):
        """
        Phân tích tư thế trong frame.
        persons: list[dict] từ detector (đã có track_id) — dùng để match pose → person
        Returns: dict với "dangerous_poses" list
        """
        if self.model is None:
            return {"dangerous_poses": []}

        results = self.model(frame, conf=0.4, verbose=False, half=self._use_half, imgsz=480)
        result = results[0]
        dangerous = []

        if result.keypoints is None or len(result.keypoints) == 0:
            return {"dangerous_poses": []}

        keypoints_data = result.keypoints.data.cpu().numpy()  # (N, 17, 3)
        boxes = result.boxes.xyxy.cpu().numpy() if result.boxes is not None else []

        for i, kps in enumerate(keypoints_data):
            bbox = tuple(boxes[i].astype(int)) if i < len(boxes) else None

            # Match pose bbox → tracked person bằng IoU
            trk_id = self._match_to_person(bbox, persons) if bbox and persons else None

            # Check: Arms raised high (tấn công / đe dọa)
            if self._is_arm_raised(kps):
                dangerous.append({
                    "type": "arm_raised",
                    "description": "Giơ tay cao — có thể đang tấn công/đe dọa",
                    "track_id": trk_id,
                    "bbox": bbox,
                })

            # Check: Punching/striking pose
            if self._is_striking_pose(kps):
                dangerous.append({
                    "type": "striking",
                    "description": "Tư thế đấm/đánh — hành vi tấn công",
                    "track_id": trk_id,
                    "bbox": bbox,
                })

            # Check: Kicking
            if self._is_kicking(kps):
                dangerous.append({
                    "type": "kicking",
                    "description": "Tư thế đá — hành vi tấn công",
                    "track_id": trk_id,
                    "bbox": bbox,
                })

        return {"dangerous_poses": dangerous}

    @staticmethod
    def _iou(box1, box2):
        """Tính IoU giữa 2 bbox (x1,y1,x2,y2)."""
        x1 = max(box1[0], box2[0])
        y1 = max(box1[1], box2[1])
        x2 = min(box1[2], box2[2])
        y2 = min(box1[3], box2[3])
        inter = max(0, x2-x1) * max(0, y2-y1)
        area1 = (box1[2]-box1[0]) * (box1[3]-box1[1])
        area2 = (box2[2]-box2[0]) * (box2[3]-box2[1])
        union = area1 + area2 - inter
        return inter / union if union > 0 else 0

    def _match_to_person(self, pose_bbox, persons):
        """Match pose bbox → tracked person bbox bằng IoU cao nhất."""
        best_id = None
        best_iou = 0.3  # minimum IoU threshold
        for p in persons:
            p_bbox = p.get("bbox")
            p_id = p.get("track_id")
            if not p_bbox or p_id is None:
                continue
            iou = self._iou(pose_bbox, p_bbox)
            if iou > best_iou:
                best_iou = iou
                best_id = p_id
        return best_id

    def _is_arm_raised(self, kps):
        """Kiểm tra tay giơ cao hơn đầu."""
        nose = kps[NOSE]
        l_wrist = kps[L_WRIST]
        r_wrist = kps[R_WRIST]
        l_shoulder = kps[L_SHOULDER]
        r_shoulder = kps[R_SHOULDER]

        # Cần confidence đủ
        if nose[2] < 0.3 or l_shoulder[2] < 0.3 or r_shoulder[2] < 0.3:
            return False

        # Tay trái hoặc phải cao hơn vai đáng kể
        threshold = abs(l_shoulder[1] - nose[1]) * 0.3 if l_shoulder[2] > 0.3 else 50
        left_raised = l_wrist[2] > 0.3 and l_wrist[1] < l_shoulder[1] - threshold
        right_raised = r_wrist[2] > 0.3 and r_wrist[1] < r_shoulder[1] - threshold

        return left_raised or right_raised

    def _is_striking_pose(self, kps):
        """Kiểm tra tư thế đấm — khuỷu tay duỗi thẳng, cổ tay phía trước."""
        for side in [(L_SHOULDER, L_ELBOW, L_WRIST), (R_SHOULDER, R_ELBOW, R_WRIST)]:
            s, e, w = kps[side[0]], kps[side[1]], kps[side[2]]
            if s[2] < 0.3 or e[2] < 0.3 or w[2] < 0.3:
                continue
            angle = angle_between(s[:2], e[:2], w[:2])
            # Cánh tay gần duỗi thẳng (> 150 độ) và cổ tay cao hơn khuỷu
            if angle > 150 and w[1] < e[1]:
                return True
        return False

    def _is_kicking(self, kps):
        """Kiểm tra đá — 1 chân giơ cao."""
        l_hip = kps[L_HIP]
        r_hip = kps[R_HIP]
        l_ankle = kps[L_ANKLE]
        r_ankle = kps[R_ANKLE]
        l_knee = kps[L_KNEE]
        r_knee = kps[R_KNEE]

        if l_hip[2] < 0.3 or r_hip[2] < 0.3:
            return False

        hip_y = (l_hip[1] + r_hip[1]) / 2

        # Mắt cá chân cao hơn hông (đang đá)
        if l_ankle[2] > 0.3 and l_ankle[1] < hip_y:
            return True
        if r_ankle[2] > 0.3 and r_ankle[1] < hip_y:
            return True

        # Đầu gối cao hơn hông đáng kể
        threshold = abs(hip_y - kps[NOSE][1]) * 0.4 if kps[NOSE][2] > 0.3 else 80
        if l_knee[2] > 0.3 and l_knee[1] < hip_y - threshold:
            return True
        if r_knee[2] > 0.3 and r_knee[1] < hip_y - threshold:
            return True

        return False
