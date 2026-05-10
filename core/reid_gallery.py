"""
Re-ID Gallery — Nhận dạng lại người dùng appearance embedding.

Flow:
    Person xuất hiện → crop ảnh → extract embedding → lưu gallery[track_id]
    Person biến mất rồi quay lại → BoTSORT gán ID mới → extract embedding
    → so cosine similarity với gallery → nếu score > threshold → map về ID cũ

Model: OSNet x0_25 (torchreid) — ~2MB, chạy được trên CPU
"""
import logging
import time
from collections import defaultdict

import numpy as np
import cv2
import torch
import torch.nn.functional as F

logger = logging.getLogger(__name__)

# ── Cấu hình ────────────────────────────────────────────────
REID_SIMILARITY_THRESHOLD = 0.72   # cosine similarity để coi là cùng người
REID_INPUT_SIZE = (256, 128)        # H x W — chuẩn Re-ID
GALLERY_MAX_EMBEDDINGS = 5          # Số embedding lưu tối đa mỗi người (lấy trung bình)
LOST_TRACK_EXPIRE = 600             # Giây trước khi xóa gallery của người biến mất (10 phút)
MIN_CROP_SIZE = 32                  # Bỏ qua crop quá nhỏ (px)
EMBED_INTERVAL = 15                 # Chỉ extract mỗi N frame để tiết kiệm CPU
EMBED_MIN_INTERVAL_SEC = 0.5        # Tối thiểu 0.5s giữa 2 lần extract cùng person
# ────────────────────────────────────────────────────────────


def _load_osnet():
    """Load OSNet x0_25 từ torchreid."""
    try:
        import torchreid
        model = torchreid.models.build_model(
            name="osnet_x0_25",
            num_classes=1000,
            pretrained=True,
        )
        model.eval()
        logger.info("✅ Re-ID model loaded: OSNet x0_25 (torchreid)")
        return model
    except ImportError:
        logger.warning("⚠️ torchreid không tìm thấy — thử cài: pip install torchreid")
        return None
    except Exception as e:
        logger.warning(f"⚠️ Không load được OSNet: {e} — dùng fallback")
        return None


def _load_mobilenet_fallback():
    """Fallback: dùng MobileNetV3 từ torchvision để extract features."""
    try:
        import torchvision.models as tv_models
        model = tv_models.mobilenet_v3_small(weights=tv_models.MobileNet_V3_Small_Weights.DEFAULT)
        # Bỏ classifier, chỉ lấy features
        model.classifier = torch.nn.Identity()
        model.eval()
        logger.info("✅ Re-ID fallback: MobileNetV3-Small (torchvision)")
        return model, 576  # output feature dim
    except Exception as e:
        logger.error(f"❌ Không load được fallback model: {e}")
        return None, 0


class ReIDGallery:
    """
    Gallery lưu embedding của từng người đã track.
    Cho phép nhận dạng lại khi BoTSORT gán ID mới.
    """

    def __init__(self):
        self.model = None
        self.use_osnet = False
        self._embed_dim = 512
        self._frame_counter = defaultdict(int)  # track_id -> frame count
        self._last_extract_time: dict[int, float] = {}  # track_id -> last extraction timestamp
        self._device = 'cpu'

        # gallery[canonical_id] = list of embeddings (numpy, L2-normalized)
        self.gallery: dict[int, list[np.ndarray]] = {}

        # Map: botsort_id -> canonical_id (ID gốc)
        # Nếu không bị re-map thì canonical_id == botsort_id
        self.id_map: dict[int, int] = {}

        # Thời điểm last seen của canonical_id
        self.last_seen: dict[int, float] = {}

        self._load_model()

    # ── Model loading ────────────────────────────────────────

    def _load_model(self):
        """Thử load OSNet, fallback sang MobileNetV3. Tự động dùng GPU nếu có."""
        # Detect device
        if torch.cuda.is_available():
            self._device = 'cuda'
        else:
            self._device = 'cpu'
        logger.info(f"🔧 Re-ID device: {self._device}")

        osnet = _load_osnet()
        if osnet is not None:
            self.model = osnet.to(self._device)
            self.use_osnet = True
            self._embed_dim = 512
        else:
            mob, dim = _load_mobilenet_fallback()
            if mob is not None:
                self.model = mob.to(self._device)
                self.use_osnet = False
                self._embed_dim = dim
            else:
                self.model = None
                logger.error("❌ Không có Re-ID model nào hoạt động — gallery bị vô hiệu hóa")

    # ── Preprocessing ────────────────────────────────────────

    def _preprocess(self, crop: np.ndarray) -> torch.Tensor:
        """Chuẩn bị ảnh crop → tensor [1, 3, H, W]."""
        img = cv2.resize(crop, (REID_INPUT_SIZE[1], REID_INPUT_SIZE[0]))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406])
        std  = np.array([0.229, 0.224, 0.225])
        img = (img - mean) / std
        tensor = torch.from_numpy(img).permute(2, 0, 1).unsqueeze(0).float()
        return tensor

    # ── Embedding extraction ─────────────────────────────────

    @torch.no_grad()
    def extract_embedding(self, frame: np.ndarray, bbox: tuple) -> np.ndarray | None:
        """
        Crop person từ frame, extract L2-normalized embedding.

        Args:
            frame: full BGR frame
            bbox:  (x1, y1, x2, y2)

        Returns:
            numpy array shape (embed_dim,), L2-normalized — hoặc None nếu lỗi
        """
        if self.model is None:
            return None

        x1, y1, x2, y2 = bbox
        h, w = frame.shape[:2]

        # Clamp bbox
        x1 = max(0, x1); y1 = max(0, y1)
        x2 = min(w, x2); y2 = min(h, y2)

        if (x2 - x1) < MIN_CROP_SIZE or (y2 - y1) < MIN_CROP_SIZE:
            return None

        crop = frame[y1:y2, x1:x2]
        tensor = self._preprocess(crop).to(self._device)

        try:
            feat = self.model(tensor)
            if isinstance(feat, (list, tuple)):
                feat = feat[0]
            feat = feat.squeeze()
            feat = F.normalize(feat, p=2, dim=0).cpu().numpy()
            return feat
        except Exception as e:
            logger.debug(f"Embedding extraction failed: {e}")
            return None

    # ── Gallery management ───────────────────────────────────

    def _get_mean_embedding(self, canonical_id: int) -> np.ndarray | None:
        """Tính mean embedding của 1 người trong gallery."""
        embs = self.gallery.get(canonical_id)
        if not embs:
            return None
        stacked = np.stack(embs, axis=0)          # (N, D)
        mean = stacked.mean(axis=0)
        norm = np.linalg.norm(mean)
        return mean / norm if norm > 1e-6 else mean

    def _add_to_gallery(self, canonical_id: int, embedding: np.ndarray):
        """Thêm embedding vào gallery của canonical_id."""
        if canonical_id not in self.gallery:
            self.gallery[canonical_id] = []

        self.gallery[canonical_id].append(embedding)

        # Giới hạn số lượng — giữ N gần nhất
        if len(self.gallery[canonical_id]) > GALLERY_MAX_EMBEDDINGS:
            self.gallery[canonical_id] = self.gallery[canonical_id][-GALLERY_MAX_EMBEDDINGS:]

        self.last_seen[canonical_id] = time.time()

    def _find_best_match(self, embedding: np.ndarray) -> tuple[int | None, float]:
        """
        So sánh embedding với toàn bộ gallery.

        Returns:
            (canonical_id, score) của match tốt nhất, hoặc (None, 0) nếu không đủ threshold
        """
        best_id = None
        best_score = 0.0

        for cid, _ in self.gallery.items():
            mean_emb = self._get_mean_embedding(cid)
            if mean_emb is None:
                continue

            score = float(np.dot(embedding, mean_emb))  # cosine similarity (đã normalize)
            if score > best_score:
                best_score = score
                best_id = cid

        if best_score >= REID_SIMILARITY_THRESHOLD:
            return best_id, best_score
        return None, best_score

    # ── Main API ─────────────────────────────────────────────

    def resolve_id(
        self,
        botsort_id: int,
        frame: np.ndarray,
        bbox: tuple,
    ) -> tuple[int, bool]:
        """
        Giải quyết ID thực sự cho 1 detection.

        - Nếu botsort_id đã biết → trả về canonical_id tương ứng, cập nhật gallery
        - Nếu botsort_id mới → so sánh gallery → nếu match → map về canonical_id cũ
        - Nếu không match → đây là người mới, canonical_id = botsort_id

        Args:
            botsort_id: ID từ BoTSORT
            frame:      full BGR frame
            bbox:       (x1, y1, x2, y2) của person

        Returns:
            (canonical_id, is_reidentified)
            is_reidentified = True nếu vừa được nhận dạng lại
        """
        # ID đã biết → chỉ cần cập nhật gallery định kỳ
        if botsort_id in self.id_map:
            canonical_id = self.id_map[botsort_id]
            self.last_seen[canonical_id] = time.time()

            # Extract và lưu embedding định kỳ để gallery luôn fresh
            # Thêm check thời gian tối thiểu giữa 2 lần extract
            self._frame_counter[botsort_id] += 1
            now = time.time()
            last_ext = self._last_extract_time.get(botsort_id, 0)
            if (self._frame_counter[botsort_id] % EMBED_INTERVAL == 0
                    and (now - last_ext) >= EMBED_MIN_INTERVAL_SEC):
                emb = self.extract_embedding(frame, bbox)
                if emb is not None:
                    self._add_to_gallery(canonical_id, emb)
                    self._last_extract_time[botsort_id] = now

            return canonical_id, False

        # ID mới từ BoTSORT → thử Re-ID
        emb = self.extract_embedding(frame, bbox)
        if emb is None:
            # Không extract được → coi như người mới
            self.id_map[botsort_id] = botsort_id
            return botsort_id, False

        match_id, score = self._find_best_match(emb)

        if match_id is not None:
            # ✅ Re-ID thành công — map về người cũ
            self.id_map[botsort_id] = match_id
            self._add_to_gallery(match_id, emb)
            self.last_seen[match_id] = time.time()
            logger.info(
                f"🔁 Re-ID: BoTSORT #{botsort_id} → Canonical #{match_id} "
                f"(score={score:.3f})"
            )
            return match_id, True
        else:
            # Người mới hoàn toàn
            self.id_map[botsort_id] = botsort_id
            self._add_to_gallery(botsort_id, emb)
            self.last_seen[botsort_id] = time.time()
            logger.debug(f"🆕 Gallery: new person #{botsort_id} (best score={score:.3f})")
            return botsort_id, False

    def cleanup_expired(self):
        """Xóa gallery của người biến mất quá lâu."""
        now = time.time()
        expired = [
            cid for cid, ts in self.last_seen.items()
            if now - ts > LOST_TRACK_EXPIRE
        ]
        for cid in expired:
            self.gallery.pop(cid, None)
            self.last_seen.pop(cid, None)
            # Xóa các id_map trỏ về canonical_id này
            to_remove = [k for k, v in self.id_map.items() if v == cid]
            for k in to_remove:
                self.id_map.pop(k, None)
                self._frame_counter.pop(k, None)
            logger.debug(f"🗑️ Gallery: expired canonical #{cid}")

    def get_stats(self) -> dict:
        """Thống kê gallery."""
        return {
            "gallery_persons": len(self.gallery),
            "id_mappings": len(self.id_map),
            "reids_performed": sum(
                1 for k, v in self.id_map.items() if k != v
            ),
        }