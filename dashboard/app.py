"""
Flask Dashboard — Web interface cho hệ thống giám sát.
"""
import logging
import time
import json
from flask import Flask, render_template, jsonify, Response
from flask_socketio import SocketIO

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["SECRET_KEY"] = "security-ai-demo-2025"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Shared state — sẽ được set từ main.py
_shared_state = {
    "latest_frame_b64": None,
    "threat_analyzer": None,
    "tracker": None,
    "db": None,
    "fps": 0,
    "source_info": "",
}


def set_shared_state(key, value):
    _shared_state[key] = value


def get_shared_state(key):
    return _shared_state.get(key)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/events")
def api_events():
    db = _shared_state.get("db")
    if db:
        events = db.get_events(limit=50)
        return jsonify(events)
    return jsonify([])


@app.route("/api/stats")
def api_stats():
    stats = {}
    analyzer = _shared_state.get("threat_analyzer")
    tracker = _shared_state.get("tracker")
    db = _shared_state.get("db")

    if analyzer:
        stats["threat"] = analyzer.get_stats()
    if tracker:
        stats["tracking"] = tracker.get_stats()
    if db:
        stats["database"] = db.get_stats()
    stats["fps"] = _shared_state.get("fps", 0)
    stats["source"] = _shared_state.get("source_info", "")

    return jsonify(stats)


def emit_frame(frame_b64):
    """Emit frame qua SocketIO."""
    _shared_state["latest_frame_b64"] = frame_b64
    socketio.emit("video_frame", {"image": frame_b64})


def emit_event(event_dict):
    """Emit event qua SocketIO."""
    socketio.emit("threat_event", event_dict)


def emit_stats(stats):
    """Emit stats update."""
    socketio.emit("stats_update", stats)


@socketio.on("connect")
def handle_connect():
    logger.info("🌐 Dashboard client connected")
    # Gửi frame mới nhất
    if _shared_state.get("latest_frame_b64"):
        socketio.emit("video_frame", {"image": _shared_state["latest_frame_b64"]})


@socketio.on("disconnect")
def handle_disconnect():
    logger.info("🌐 Dashboard client disconnected")


def run_dashboard(host="0.0.0.0", port=5000):
    """Chạy dashboard server."""
    logger.info(f"🖥️ Dashboard starting at http://{host}:{port}")
    socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)
