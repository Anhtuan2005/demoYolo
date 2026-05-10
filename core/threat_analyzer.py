"""
Threat Analyzer — Phân tích mối đe dọa.
"""
import logging
import math
import time
import config

logger = logging.getLogger(__name__)


class ThreatEvent:
    def __init__(self, threat_level, description, track_ids, bbox=None, timestamp=None):
        self.threat_level = threat_level
        self.description = description
        self.track_ids = track_ids
        self.bbox = bbox
        self.timestamp = timestamp or time.time()
        self.notified = False

    def to_dict(self):
        # Ensure all values are JSON serializable (convert numpy types)
        def _safe(v):
            if hasattr(v, 'item'):
                return v.item()
            return v

        return {
            "threat_level": self.threat_level,
            "description": self.description,
            "track_ids": [_safe(x) for x in self.track_ids],
            "bbox": tuple(_safe(x) for x in self.bbox) if self.bbox else None,
            "timestamp": float(self.timestamp),
            "notified": self.notified,
        }


class ThreatAnalyzer:
    def __init__(self):
        self.events = []
        self._last_alert_by_track = {}
        self.current_threat_level = "LOW"

    def analyze(self, detections, active_tracks, pose_results=None):
        new_events = []
        persons = detections.get("persons", [])
        weapons = detections.get("weapons", [])

        # 1. Weapon near person
        for weapon in weapons:
            w_center = weapon["center"]
            closest_person = None
            min_dist = float("inf")
            for person in persons:
                p_center = person["center"]
                dist = math.sqrt((w_center[0]-p_center[0])**2 + (w_center[1]-p_center[1])**2)
                if dist < min_dist:
                    min_dist = dist
                    closest_person = person

            if closest_person and min_dist < config.PROXIMITY_THRESHOLD:
                p_id = closest_person.get("track_id", "?")
                w_id = weapon.get("track_id", "?")
                w_label = weapon.get("label", "weapon")
                p_bbox = closest_person["bbox"]
                w_bbox = weapon["bbox"]
                union_bbox = (min(p_bbox[0], w_bbox[0]), min(p_bbox[1], w_bbox[1]),
                              max(p_bbox[2], w_bbox[2]), max(p_bbox[3], w_bbox[3]))
                event = ThreatEvent("CRITICAL",
                    f"🚨 NGUY HIỂM: Người #{p_id} đang cầm {w_label}! (khoảng cách: {min_dist:.0f}px)",
                    [p_id, w_id], union_bbox)
                new_events.append(event)
            elif weapon:
                w_id = weapon.get("track_id", "?")
                w_label = weapon.get("label", "weapon")
                event = ThreatEvent("HIGH",
                    f"⚠️ CẢNH BÁO: {w_label} được phát hiện (ID #{w_id})",
                    [w_id], weapon["bbox"])
                new_events.append(event)

        # 2. Dangerous poses
        if pose_results:
            for pose_info in pose_results.get("dangerous_poses", []):
                event = ThreatEvent("HIGH",
                    f"⚠️ HÀNH VI NGUY HIỂM: {pose_info['description']} (Người #{pose_info.get('track_id', '?')})",
                    [pose_info.get("track_id")], pose_info.get("bbox"))
                new_events.append(event)

        # 3. Abnormal movement
        for trk_id, track_info in active_tracks.items():
            if track_info.label != "person":
                continue
            if track_info.speed > config.ABNORMAL_SPEED_THRESHOLD:
                event = ThreatEvent("MEDIUM",
                    f"⚡ DI CHUYỂN BẤT THƯỜNG: Người #{trk_id} ({track_info.speed:.0f} px/s)",
                    [trk_id], getattr(track_info, "bbox", None))
                new_events.append(event)

        # Update overall threat level
        if new_events:
            max_level = max(config.THREAT_LEVELS.get(e.threat_level, 0) for e in new_events)
            level_map = {v: k for k, v in config.THREAT_LEVELS.items()}
            self.current_threat_level = level_map.get(max_level, "LOW")
        else:
            levels = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
            idx = levels.index(self.current_threat_level)
            if idx > 0:
                self.current_threat_level = levels[idx - 1]

        # Filter cooldown
        filtered = []
        now = time.time()
        for event in new_events:
            key = tuple(sorted([str(x) for x in event.track_ids]))
            last_time = self._last_alert_by_track.get(key, 0)
            if now - last_time >= config.ALERT_COOLDOWN:
                self._last_alert_by_track[key] = now
                filtered.append(event)

        self.events.extend(filtered)
        return filtered

    def get_recent_events(self, limit=20):
        return [e.to_dict() for e in self.events[-limit:]]

    def get_stats(self):
        return {
            "current_threat_level": self.current_threat_level,
            "total_events": len(self.events),
            "critical_events": sum(1 for e in self.events if e.threat_level == "CRITICAL"),
            "high_events": sum(1 for e in self.events if e.threat_level == "HIGH"),
            "medium_events": sum(1 for e in self.events if e.threat_level == "MEDIUM"),
        }
