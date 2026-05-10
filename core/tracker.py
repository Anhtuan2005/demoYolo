"""
Object Tracker — Theo dõi đối tượng với BoTSORT + Re-ID Gallery.

Tích hợp ReIDGallery để nhận dạng lại người sau khi mất track.
"""
import logging
import time
from collections import defaultdict, deque

from core.reid_gallery import ReIDGallery

logger = logging.getLogger(__name__)


class TrackInfo:
    """Thông tin theo dõi 1 đối tượng."""

    def __init__(self, track_id: int, label: str):
        self.track_id = track_id
        self.label = label
        self.first_seen = time.time()
        self.last_seen = time.time()
        self.positions = deque(maxlen=100)
        self.velocities = deque(maxlen=50)
        self.threat_level = "LOW"
        self.alert_count = 0
        self.last_alert_time = 0

    def update(self, center: tuple, bbox: tuple):
        now = time.time()
        if self.positions:
            prev = self.positions[-1]
            dt = now - self.last_seen
            if dt > 0:
                vx = (center[0] - prev[0]) / dt
                vy = (center[1] - prev[1]) / dt
                self.velocities.append((vx, vy))
        self.positions.append(center)
        self.last_seen = now
        self.bbox = bbox

    @property
    def speed(self) -> float:
        if not self.velocities:
            return 0.0
        recent = list(self.velocities)[-10:]
        avg_vx = sum(v[0] for v in recent) / len(recent)
        avg_vy = sum(v[1] for v in recent) / len(recent)
        return (avg_vx**2 + avg_vy**2) ** 0.5

    @property
    def duration(self) -> float:
        return self.last_seen - self.first_seen

    def can_alert(self, cooldown: float) -> bool:
        return (time.time() - self.last_alert_time) >= cooldown

    def mark_alerted(self):
        self.last_alert_time = time.time()
        self.alert_count += 1


class ObjectTracker:
    """
    Quản lý tracking history cho tất cả đối tượng.
    Tích hợp ReIDGallery: khi BoTSORT gán ID mới cho người đã biết,
    gallery sẽ map về canonical ID cũ — giữ nguyên lịch sử.
    """

    def __init__(self):
        self.tracks: dict[int, TrackInfo] = {}
        self.track_history = defaultdict(lambda: deque(maxlen=50))
        self._lost_tracks: dict[int, float] = {}
        self.total_persons_detected = 0
        self.total_weapons_detected = 0
        self._cleanup_counter = 0

        self.reid = ReIDGallery()
        logger.info("🔍 Re-ID Gallery initialized")

    def update(self, detections: dict, frame=None) -> dict[int, TrackInfo]:
        """
        Cập nhật tracking từ detection results.

        Args:
            detections: output từ ThreatDetector.detect_with_tracking()
            frame:      current BGR frame (cần cho Re-ID embedding)
        """
        active_ids = set()

        # ── Persons ─────────────────────────────────────────
        for det in detections["persons"]:
            raw_id = det.get("track_id")
            if raw_id is None:
                continue

            if frame is not None:
                canonical_id, was_reidentified = self.reid.resolve_id(
                    raw_id, frame, det["bbox"]
                )
            else:
                canonical_id, was_reidentified = raw_id, False

            det["track_id"] = canonical_id
            active_ids.add(canonical_id)

            if canonical_id not in self.tracks:
                self.tracks[canonical_id] = TrackInfo(canonical_id, "person")
                self.total_persons_detected += 1
                if was_reidentified:
                    logger.info(f"🔁 Re-ID: Person #{canonical_id} returned (was #{raw_id})")
                else:
                    logger.info(f"🆕 New person tracked: ID #{canonical_id}")
            elif was_reidentified:
                logger.info(f"🔁 Re-ID: merged BoTSORT #{raw_id} → #{canonical_id}")

            self.tracks[canonical_id].update(det["center"], det["bbox"])
            self.track_history[canonical_id].append(det["center"])

            if canonical_id in self._lost_tracks:
                del self._lost_tracks[canonical_id]

        # ── Weapons ─────────────────────────────────────────
        for det in detections["weapons"]:
            trk_id = det.get("track_id")
            if trk_id is None:
                continue
            active_ids.add(trk_id)

            if trk_id not in self.tracks:
                self.tracks[trk_id] = TrackInfo(trk_id, det["label"])
                self.total_weapons_detected += 1
                logger.warning(f"⚠️ Weapon detected and tracked: {det['label']} ID #{trk_id}")

            self.tracks[trk_id].update(det["center"], det["bbox"])
            self.track_history[trk_id].append(det["center"])

        # ── Lost track management ────────────────────────────
        now = time.time()
        for trk_id in list(self.tracks.keys()):
            if trk_id not in active_ids:
                if trk_id not in self._lost_tracks:
                    self._lost_tracks[trk_id] = now

        for trk_id in list(self._lost_tracks.keys()):
            if now - self._lost_tracks[trk_id] > 60:
                self.tracks.pop(trk_id, None)
                self.track_history.pop(trk_id, None)
                del self._lost_tracks[trk_id]

        # ── Periodic gallery cleanup ─────────────────────────
        self._cleanup_counter += 1
        if self._cleanup_counter % 500 == 0:
            self.reid.cleanup_expired()

        return {tid: self.tracks[tid] for tid in active_ids if tid in self.tracks}

    def get_active_persons(self) -> list[TrackInfo]:
        now = time.time()
        return [t for t in self.tracks.values()
                if t.label == "person" and (now - t.last_seen) < 2]

    def get_active_weapons(self) -> list[TrackInfo]:
        now = time.time()
        return [t for t in self.tracks.values()
                if t.label != "person" and (now - t.last_seen) < 2]

    def get_stats(self) -> dict:
        reid_stats = self.reid.get_stats()
        return {
            "active_tracks": len([t for t in self.tracks.values()
                                   if (time.time() - t.last_seen) < 2]),
            "total_persons": self.total_persons_detected,
            "total_weapons": self.total_weapons_detected,
            "active_persons": len(self.get_active_persons()),
            "active_weapons": len(self.get_active_weapons()),
            **reid_stats,
        }