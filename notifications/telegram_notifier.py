"""
Telegram Notifier — Gửi thông báo cảnh báo qua Telegram.
"""
import logging
import time
import threading
import requests
from io import BytesIO
import config

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token=None, chat_id=None):
        self.bot_token = bot_token or config.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or config.TELEGRAM_CHAT_ID
        self.enabled = bool(self.bot_token and self.chat_id)
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self._send_queue = []

        if not self.enabled:
            logger.warning("⚠️ Telegram chưa cấu hình. Set TELEGRAM_BOT_TOKEN và TELEGRAM_CHAT_ID trong .env")
        else:
            logger.info("✅ Telegram notifier initialized")

    def send_text(self, message):
        """Gửi tin nhắn text."""
        if not self.enabled:
            logger.debug(f"[Telegram OFF] {message}")
            return False

        def _send():
            try:
                url = f"{self.base_url}/sendMessage"
                data = {
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                }
                resp = requests.post(url, data=data, timeout=10)
                if resp.status_code == 200:
                    logger.info("📱 Telegram: Text sent successfully")
                else:
                    logger.error(f"❌ Telegram error: {resp.text}")
            except Exception as e:
                logger.error(f"❌ Telegram send failed: {e}")

        threading.Thread(target=_send, daemon=True).start()
        return True

    def send_photo(self, image_bytes, caption=""):
        """Gửi ảnh kèm caption."""
        if not self.enabled:
            logger.debug(f"[Telegram OFF] Photo: {caption}")
            return False

        def _send():
            try:
                url = f"{self.base_url}/sendPhoto"
                files = {"photo": ("alert.jpg", BytesIO(image_bytes), "image/jpeg")}
                data = {
                    "chat_id": self.chat_id,
                    "caption": caption[:1024],  # Telegram limit
                    "parse_mode": "HTML",
                }
                resp = requests.post(url, files=files, data=data, timeout=30)
                if resp.status_code == 200:
                    logger.info("📱 Telegram: Photo sent successfully")
                else:
                    logger.error(f"❌ Telegram photo error: {resp.text}")
            except Exception as e:
                logger.error(f"❌ Telegram photo send failed: {e}")

        threading.Thread(target=_send, daemon=True).start()
        return True

    def send_alert(self, event, frame_bytes=None):
        """Gửi alert đầy đủ — text + ảnh."""
        threat_emoji = {
            "CRITICAL": "🔴🚨",
            "HIGH": "🟠⚠️",
            "MEDIUM": "🟡⚡",
            "LOW": "🟢ℹ️",
        }
        emoji = threat_emoji.get(event.threat_level, "⚪")
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(event.timestamp))

        caption = (
            f"{emoji} <b>CẢNH BÁO AN NINH</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Mức độ:</b> {event.threat_level}\n"
            f"📝 <b>Chi tiết:</b> {event.description}\n"
            f"🆔 <b>ID đối tượng:</b> {', '.join(str(x) for x in event.track_ids)}\n"
            f"🕐 <b>Thời gian:</b> {timestamp}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔔 Hệ thống giám sát AI"
        )

        if frame_bytes:
            self.send_photo(frame_bytes, caption)
        else:
            self.send_text(caption)

        event.notified = True
        return True

    def send_test(self):
        """Gửi tin nhắn test."""
        msg = (
            "🧪 <b>TEST — Hệ thống giám sát AI</b>\n\n"
            "✅ Kết nối Telegram thành công!\n"
            f"🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            "📹 Hệ thống sẵn sàng hoạt động."
        )
        return self.send_text(msg)
