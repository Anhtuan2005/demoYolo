"""
Image Utils — Xử lý hình ảnh cho detection và dashboard.
"""
import cv2
import numpy as np
import time
import base64
from pathlib import Path
import config

# Màu sắc theo threat level (BGR)
COLORS = {
    "person": (0, 200, 0),       # Xanh lá
    "knife": (0, 0, 255),        # Đỏ
    "scissors": (0, 100, 255),   # Cam
    "weapon": (0, 0, 255),       # Đỏ
    "CRITICAL": (0, 0, 255),     # Đỏ
    "HIGH": (0, 100, 255),       # Cam
    "MEDIUM": (0, 255, 255),     # Vàng
    "LOW": (0, 200, 0),          # Xanh
    "track": (255, 200, 0),      # Cyan
}


def draw_detections(frame, detections, active_tracks=None, threat_events=None):
    """Vẽ bounding boxes, track IDs, threat indicators lên frame."""
    overlay = frame.copy()

    # Vẽ persons
    for det in detections.get("persons", []):
        x1, y1, x2, y2 = det["bbox"]
        trk_id = det.get("track_id")
        conf = det["confidence"]
        color = COLORS["person"]

        # Kiểm tra nếu person liên quan đến threat
        is_threat = False
        if threat_events:
            for ev in threat_events:
                if trk_id in ev.track_ids and ev.threat_level in ("CRITICAL", "HIGH"):
                    color = COLORS[ev.threat_level]
                    is_threat = True
                    break

        # Vẽ bbox
        thickness = 3 if is_threat else 2
        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, thickness)

        # Label
        label = f"Person"
        if trk_id is not None:
            label += f" #{trk_id}"
        label += f" {conf:.0%}"

        # Background cho label
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
        cv2.rectangle(overlay, (x1, y1 - th - 10), (x1 + tw + 8, y1), color, -1)
        cv2.putText(overlay, label, (x1 + 4, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

        # Vẽ track trail
        if active_tracks and trk_id and trk_id in active_tracks:
            track = active_tracks[trk_id]
            positions = list(track.positions)
            for j in range(1, len(positions)):
                alpha = j / len(positions)
                pt1 = (int(positions[j-1][0]), int(positions[j-1][1]))
                pt2 = (int(positions[j][0]), int(positions[j][1]))
                cv2.line(overlay, pt1, pt2, COLORS["track"], max(1, int(alpha * 3)))

    # Vẽ weapons
    for det in detections.get("weapons", []):
        x1, y1, x2, y2 = det["bbox"]
        trk_id = det.get("track_id")
        label_name = det.get("label", "weapon")
        conf = det["confidence"]
        color = COLORS.get(label_name, COLORS["weapon"])

        # Vẽ bbox nhấp nháy cho weapon
        if int(time.time() * 4) % 2 == 0:
            cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 3)
        cv2.rectangle(overlay, (x1-2, y1-2), (x2+2, y2+2), color, 1)

        # Danger icon
        label = f"⚠ {label_name.upper()}"
        if trk_id is not None:
            label += f" #{trk_id}"
        label += f" {conf:.0%}"

        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
        cv2.rectangle(overlay, (x1, y1 - th - 10), (x1 + tw + 8, y1), color, -1)
        cv2.putText(overlay, label, (x1 + 4, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    # Blend overlay
    cv2.addWeighted(overlay, 0.9, frame, 0.1, 0, frame)

    # HUD — info bar
    draw_hud(frame, detections, threat_events)

    return frame


def draw_hud(frame, detections, threat_events=None):
    """Vẽ HUD overlay với thông tin hệ thống."""
    h, w = frame.shape[:2]

    # Top bar background
    cv2.rectangle(frame, (0, 0), (w, 40), (0, 0, 0), -1)
    cv2.rectangle(frame, (0, 0), (w, 40), (50, 50, 50), 1)

    # System info
    n_persons = len(detections.get("persons", []))
    n_weapons = len(detections.get("weapons", []))
    timestamp = time.strftime("%H:%M:%S")

    info_text = f"AI SECURITY | {timestamp} | Persons: {n_persons} | Weapons: {n_weapons}"
    cv2.putText(frame, info_text, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 1)

    # Threat level indicator
    if threat_events:
        max_level = max((ev.threat_level for ev in threat_events),
                       key=lambda x: config.THREAT_LEVELS.get(x, 0), default="LOW")
        color = COLORS.get(max_level, COLORS["LOW"])
        cv2.circle(frame, (w - 25, 20), 12, color, -1)
        cv2.putText(frame, max_level, (w - 130, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)


def frame_to_base64(frame, quality=None):
    """Encode frame to base64 JPEG string."""
    q = quality or config.JPEG_QUALITY
    _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, q])
    return base64.b64encode(buffer).decode("utf-8")


def frame_to_bytes(frame, quality=None):
    """Encode frame to JPEG bytes."""
    q = quality or config.JPEG_QUALITY
    _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, q])
    return buffer.tobytes()


def crop_object(frame, bbox, padding=20):
    """Crop đối tượng từ frame với padding."""
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    x1 = max(0, x1 - padding)
    y1 = max(0, y1 - padding)
    x2 = min(w, x2 + padding)
    y2 = min(h, y2 + padding)
    return frame[y1:y2, x1:x2].copy()


def save_alert_image(frame, event, detections=None):
    """Lưu ảnh alert với timestamp."""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"alert_{event.threat_level}_{timestamp}.jpg"
    filepath = config.ALERTS_DIR / filename
    cv2.imwrite(str(filepath), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return str(filepath)


def resize_frame(frame, target_width=None):
    """Resize frame giữ tỷ lệ."""
    tw = target_width or config.FRAME_RESIZE_WIDTH
    h, w = frame.shape[:2]
    if w <= tw:
        return frame
    ratio = tw / w
    new_h = int(h * ratio)
    return cv2.resize(frame, (tw, new_h))
