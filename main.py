"""
Main Entry Point — Hệ thống phát hiện kẻ nguy hiểm.

Usage:
    # Webcam
    python main.py --source 0 --dashboard --telegram

    # Video file
    python main.py --source video.mp4 --dashboard --telegram

    # Image
    python main.py --source image.jpg --show

    # Tất cả tính năng
    python main.py --source 0 --dashboard --telegram --pose --show
"""
import argparse
import logging
import sys
import time
import threading
import os
import platform
import cv2
import numpy as np

# Setup logging FIRST
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)-20s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

# Project imports
import config
from core.detector import ThreatDetector
from core.tracker import ObjectTracker
from core.threat_analyzer import ThreatAnalyzer
from notifications.telegram_notifier import TelegramNotifier
from database.db_manager import DatabaseManager
from utils.image_utils import (
    draw_detections, frame_to_base64, frame_to_bytes,
    save_alert_image, resize_frame,
)


class ThreadedCapture:
    """
    Đọc frame từ camera/video trong thread riêng.
    Luôn giữ frame mới nhất — main thread không bao giờ bị block bởi I/O.
    """

    def __init__(self, source):
        # Windows: dùng DirectShow thay MSMF (MSMF thường bị treo)
        if platform.system() == "Windows" and isinstance(source, int):
            self.cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
        else:
            self.cap = cv2.VideoCapture(source)
        self._frame = None
        self._ret = False
        self._lock = threading.Lock()
        self._stopped = False

        # Đọc frame đầu tiên
        self._ret, self._frame = self.cap.read()

        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        while not self._stopped:
            ret, frame = self.cap.read()
            with self._lock:
                self._ret = ret
                self._frame = frame

    def read(self):
        with self._lock:
            return self._ret, self._frame.copy() if self._frame is not None else (False, None)

    def isOpened(self):
        return self.cap.isOpened()

    def get(self, prop):
        return self.cap.get(prop)

    def set(self, prop, val):
        return self.cap.set(prop, val)

    def release(self):
        self._stopped = True
        self.cap.release()


def parse_args():
    parser = argparse.ArgumentParser(
        description="🛡️ AI Security Monitor — Hệ thống phát hiện kẻ nguy hiểm",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ:
  python main.py --source 0                    # Webcam
  python main.py --source video.mp4            # Video file
  python main.py --source image.jpg            # Ảnh
  python main.py --source 0 --dashboard        # Webcam + Web Dashboard
  python main.py --source 0 --telegram         # Webcam + Telegram alerts
  python main.py --source 0 --dashboard --telegram --pose --show
        """,
    )
    parser.add_argument("--source", type=str, default="0",
                        help="Nguồn video: 0 (webcam), path to video, path to image")
    parser.add_argument("--dashboard", action="store_true",
                        help="Bật web dashboard (http://localhost:5000)")
    parser.add_argument("--telegram", action="store_true",
                        help="Bật gửi thông báo Telegram")
    parser.add_argument("--pose", action="store_true",
                        help="Bật phân tích tư thế (YOLOv11-Pose)")
    parser.add_argument("--show", action="store_true",
                        help="Hiển thị cửa sổ OpenCV")
    parser.add_argument("--confidence", type=float, default=None,
                        help="Confidence threshold (default: 0.45)")
    parser.add_argument("--model", type=str, default=None,
                        help="Model path (default: yolo11m.pt)")
    parser.add_argument("--port", type=int, default=5000,
                        help="Dashboard port (default: 5000)")
    return parser.parse_args()


def detect_source_type(source: str) -> str:
    """Phân biệt loại nguồn: webcam, video, image."""
    if source.isdigit():
        return "webcam"

    ext = os.path.splitext(source)[1].lower()
    image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff"}
    video_exts = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".webm"}

    if ext in image_exts:
        return "image"
    elif ext in video_exts:
        return "video"
    else:
        return "video"  # Default to video


def process_image(args, detector, analyzer, tracker, notifier, db):
    """Xử lý ảnh đơn lẻ."""
    logger.info(f"📷 Processing image: {args.source}")
    frame = cv2.imread(args.source)
    if frame is None:
        logger.error(f"❌ Cannot read image: {args.source}")
        return

    frame = resize_frame(frame)

    # Detect (no tracking for single image)
    detections = detector.detect(frame)

    # Analyze
    events = analyzer.analyze(detections, {})

    # Draw
    annotated = frame.copy()
    draw_detections(annotated, detections, threat_events=events)

    # Log results
    n_persons = len(detections["persons"])
    n_weapons = len(detections["weapons"])
    logger.info(f"📊 Results: {n_persons} persons, {n_weapons} weapons, {len(events)} threats")

    for event in events:
        logger.warning(f"   {event.description}")
        if args.telegram:
            frame_bytes = frame_to_bytes(annotated, quality=90)
            notifier.send_alert(event, frame_bytes)
        db.add_event(event, save_alert_image(annotated, event))

    # Show
    if args.show:
        cv2.imshow("AI Security Monitor — Image", annotated)
        logger.info("Press any key to close...")
        cv2.waitKey(0)
        cv2.destroyAllWindows()

    # Save result
    output_path = os.path.splitext(args.source)[0] + "_result.jpg"
    cv2.imwrite(output_path, annotated)
    logger.info(f"💾 Result saved: {output_path}")


def process_video(args, detector, analyzer, tracker, notifier, db, pose_analyzer=None):
    """Xử lý video hoặc webcam (main loop)."""
    # Dashboard imports
    dashboard_app = None
    if args.dashboard:
        from dashboard.app import app, socketio, set_shared_state, emit_frame, emit_event, emit_stats
        set_shared_state("threat_analyzer", analyzer)
        set_shared_state("tracker", tracker)
        set_shared_state("db", db)
        dashboard_app = (app, socketio, emit_frame, emit_event, emit_stats, set_shared_state)

    source = int(args.source) if args.source.isdigit() else args.source
    source_type = "webcam" if args.source.isdigit() else "video"

    logger.info(f"📹 Opening {source_type}: {source}")

    # Video file dùng cap thường (để có thể replay)
    # Webcam dùng threaded capture (giảm latency)
    use_threaded = (source_type == "webcam")
    if use_threaded:
        cap = ThreadedCapture(source)
    elif platform.system() == "Windows" and isinstance(source, int):
        cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
    else:
        cap = cv2.VideoCapture(source)

    if not cap.isOpened():
        logger.error(f"❌ Cannot open source: {source}")
        return

    # Get video info
    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if source_type == "video" else 0
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30

    source_info = f"{source_type.upper()} | {orig_w}x{orig_h}"
    if total_frames > 0:
        source_info += f" | {total_frames} frames"
    logger.info(f"   {source_info}")

    if dashboard_app:
        dashboard_app[5]("source_info", source_info)

    # Start dashboard in background thread
    if dashboard_app:
        def run_dash():
            from dashboard.app import run_dashboard
            run_dashboard(host="0.0.0.0", port=args.port)
        dash_thread = threading.Thread(target=run_dash, daemon=True)
        dash_thread.start()
        logger.info(f"🖥️  Dashboard: http://localhost:{args.port}")

    # ========== MAIN PROCESSING LOOP ==========
    frame_idx = 0
    fps_counter = 0
    fps_start = time.time()
    current_fps = 0
    # Adaptive frame skip: nếu FPS quá thấp, skip frame để giữ real-time
    process_every_n = 1  # Ban đầu process mọi frame
    TARGET_FPS = 12      # Mục tiêu tối thiểu

    logger.info("=" * 60)
    logger.info("🟢 System started — Press 'q' to quit")
    logger.info("=" * 60)

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                if source_type == "video":
                    logger.info("📼 Video ended. Replaying...")
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                else:
                    logger.error("❌ Camera frame read failed")
                    break

            frame_idx += 1

            # ── Adaptive frame skip ──────────────────────────────
            if frame_idx % process_every_n != 0:
                continue

            frame = resize_frame(frame)

            # === Profiling timers ===
            t0 = time.perf_counter()

            # === Detection + Tracking ===
            detections = detector.detect_with_tracking(frame)
            t1 = time.perf_counter()

            # === Update tracker ===
            active_tracks = tracker.update(detections, frame=frame)
            t2 = time.perf_counter()

            # === Pose analysis ===
            pose_results = None
            if pose_analyzer and frame_idx % 5 == 0:  # Every 5 frames to save compute
                pose_results = pose_analyzer.analyze(frame, detections.get("persons"))

            # === Threat analysis ===
            events = analyzer.analyze(detections, active_tracks, pose_results)
            t3 = time.perf_counter()

            # === Draw annotations ===
            annotated = frame.copy()
            draw_detections(annotated, detections, active_tracks, events)
            t4 = time.perf_counter()

            # === Handle threat events ===
            for event in events:
                # Save alert image
                img_path = save_alert_image(annotated, event)
                db.add_event(event, img_path)

                # Send Telegram
                if args.telegram:
                    frame_bytes = frame_to_bytes(annotated, quality=85)
                    notifier.send_alert(event, frame_bytes)

                # Emit to dashboard
                if dashboard_app:
                    dashboard_app[3](event.to_dict())  # emit_event

            # === Stream to dashboard ===
            if dashboard_app and frame_idx % max(1, int(src_fps / config.STREAM_FPS)) == 0:
                frame_b64 = frame_to_base64(annotated)
                dashboard_app[2](frame_b64)  # emit_frame
            t5 = time.perf_counter()

            # === Log profiling mỗi 50 frames ===
            if frame_idx % 50 == 0:
                logger.info(
                    f"⏱️ PROFILE f#{frame_idx} | "
                    f"YOLO: {(t1-t0)*1000:.0f}ms | "
                    f"Tracker+ReID: {(t2-t1)*1000:.0f}ms | "
                    f"Analysis: {(t3-t2)*1000:.0f}ms | "
                    f"Draw: {(t4-t3)*1000:.0f}ms | "
                    f"Stream: {(t5-t4)*1000:.0f}ms | "
                    f"TOTAL: {(t5-t0)*1000:.0f}ms"
                )

            # === FPS calculation + adaptive skip ===
            fps_counter += 1
            elapsed = time.time() - fps_start
            if elapsed >= 1.0:
                current_fps = int(fps_counter / elapsed)
                fps_counter = 0
                fps_start = time.time()

                # Adaptive: nếu FPS < target, tăng skip
                if current_fps < TARGET_FPS and process_every_n < 3:
                    process_every_n += 1
                    logger.info(f"⚡ FPS low ({current_fps}), skip every {process_every_n} frames")
                elif current_fps > TARGET_FPS * 1.5 and process_every_n > 1:
                    process_every_n -= 1
                    logger.info(f"✅ FPS recovered ({current_fps}), process every {process_every_n} frames")

                if dashboard_app:
                    stats = {
                        "fps": current_fps,
                        "tracking": tracker.get_stats(),
                        "threat": analyzer.get_stats(),
                        "source": source_info,
                    }
                    dashboard_app[4](stats)  # emit_stats
                    dashboard_app[5]("fps", current_fps)

            # === Show OpenCV window ===
            if args.show:
                # Draw FPS on frame
                cv2.putText(annotated, f"FPS: {current_fps}", (10, annotated.shape[0] - 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                cv2.imshow("AI Security Monitor", annotated)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    logger.info("👋 User quit")
                    break

            # Progress log (mỗi 100 frames)
            if frame_idx % 100 == 0:
                t_stats = tracker.get_stats()
                logger.info(
                    f"Frame {frame_idx} | FPS: {current_fps} | "
                    f"Persons: {t_stats['active_persons']} | "
                    f"Weapons: {t_stats['active_weapons']} | "
                    f"Threat: {analyzer.current_threat_level}"
                )

    except KeyboardInterrupt:
        logger.info("👋 Interrupted by user")
    finally:
        cap.release()
        if args.show:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
        logger.info("🔴 System stopped")


def main():
    args = parse_args()

    # Banner
    print("\n" + "=" * 60)
    print("  🛡️  AI SECURITY MONITOR")
    print("  YOLOv11 + BoTSORT Re-ID + Telegram Alerts")
    print("=" * 60 + "\n")

    # Override config
    if args.confidence:
        config.CONFIDENCE_THRESHOLD = args.confidence

    # Initialize components
    logger.info("🔧 Initializing components...")

    # 1. Detector
    model_path = args.model or config.MODEL_DETECT
    detector = ThreatDetector(model_path=model_path, confidence=config.CONFIDENCE_THRESHOLD)

    # 2. Tracker
    tracker = ObjectTracker()

    # 3. Threat Analyzer
    analyzer = ThreatAnalyzer()

    # 4. Database
    db = DatabaseManager()

    # 5. Telegram
    notifier = TelegramNotifier()
    if args.telegram:
        if notifier.enabled:
            notifier.send_text("🟢 <b>Hệ thống giám sát AI đã khởi động!</b>\n📹 Nguồn: " + args.source)
        else:
            logger.warning("⚠️ Telegram chưa cấu hình! Tạo file .env từ .env.example")

    # 6. Pose Analyzer (optional)
    pose_analyzer = None
    if args.pose:
        from core.pose_analyzer import PoseAnalyzer
        pose_analyzer = PoseAnalyzer()

    logger.info("✅ All components initialized!")
    logger.info(f"   Source: {args.source}")
    logger.info(f"   Dashboard: {'ON' if args.dashboard else 'OFF'}")
    logger.info(f"   Telegram: {'ON' if args.telegram else 'OFF'}")
    logger.info(f"   Pose Analysis: {'ON' if args.pose else 'OFF'}")
    logger.info(f"   OpenCV Window: {'ON' if args.show else 'OFF'}")

    # Determine source type and process
    source_type = detect_source_type(args.source)

    if source_type == "image":
        process_image(args, detector, analyzer, tracker, notifier, db)
    else:
        process_video(args, detector, analyzer, tracker, notifier, db, pose_analyzer)


if __name__ == "__main__":
    main()
