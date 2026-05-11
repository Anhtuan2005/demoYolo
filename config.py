"""
Cấu hình hệ thống phát hiện kẻ nguy hiểm.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# Đường dẫn dự án
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
ALERTS_DIR = BASE_DIR / "alerts"
DATA_DIR = BASE_DIR / "data"
DB_PATH = BASE_DIR / "database" / "events.db"

ALERTS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# ============================================================
# Model Configuration
# ============================================================
MODEL_DETECT = "yolo11n.pt"                              # COCO → detect person + knife
MODEL_DETECT_CUSTOM = "runs/detect/train-7/weights/best.pt"  # Custom → detect scissors
MODEL_POSE = "yolo11s-pose.pt"                              # Pose estimation model (small)
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.35"))
IOU_THRESHOLD = 0.5

# COCO class IDs cho detection
PERSON_CLASS = 0          # COCO class 0 = person
WEAPON_CLASSES = {
    43: "knife",
    0: "scissors",        # custom model class 0 = scissors
}
TARGET_CLASSES = [0, 43]  # cho COCO model
TARGET_CLASSES_CUSTOM = [0]  # cho custom model

# ============================================================
# Tracker Configuration (BoTSORT + Re-ID)
# ============================================================
TRACKER_CONFIG = str(BASE_DIR / "botsort_reid.yaml")
TRACK_BUFFER = 60          # Số frame giữ track khi mất đối tượng
MATCH_THRESHOLD = 0.8

# ============================================================
# Threat Analysis
# ============================================================
# Khoảng cách pixel giữa person và weapon để xác định mối đe dọa
PROXIMITY_THRESHOLD = 200   # pixels
# Cooldown giữa các alert cho cùng 1 track (giây)
ALERT_COOLDOWN = 30
# Threat levels
THREAT_LEVELS = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}

# ============================================================
# Pose Analysis — Phát hiện hành vi nguy hiểm
# ============================================================
POSE_ENABLED = True
# Góc giơ tay cao (độ) — ngưỡng phát hiện tấn công
ARM_RAISE_ANGLE = 45
# Tốc độ di chuyển bất thường (pixels/frame)
ABNORMAL_SPEED_THRESHOLD = 50

# ============================================================
# Telegram Notification
# ============================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}"

# ============================================================
# Dashboard
# ============================================================
DASHBOARD_HOST = "0.0.0.0"
DASHBOARD_PORT = 5000
STREAM_FPS = 15             # FPS cho stream lên dashboard

# ============================================================
# Processing
# ============================================================
FRAME_RESIZE_WIDTH = 640    # Resize frame để tối ưu tốc độ (nhỏ hơn = nhanh hơn)
JPEG_QUALITY = 70           # Chất lượng ảnh stream
