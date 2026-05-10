# 🛡️ AI Security Monitor — Hệ Thống Phát Hiện Kẻ Nguy Hiểm

Hệ thống giám sát an ninh thời gian thực sử dụng AI, phát hiện vũ khí và hành vi nguy hiểm, tự động gửi cảnh báo qua Telegram.

## 🚀 Công Nghệ

| Thành phần | Công nghệ |
|---|---|
| Phát hiện đối tượng | **YOLOv11** (ultralytics) |
| Theo dõi đối tượng | **BoTSORT** + **Re-ID** |
| Phân tích tư thế | **YOLOv11-Pose** |
| Thông báo di động | **Telegram Bot API** |
| Web Dashboard | **Flask** + **SocketIO** |
| Database | **SQLite** |

## 📋 Yêu Cầu

- Python 3.10+
- NVIDIA GPU (RTX 2050 trở lên khuyến nghị)
- CUDA Toolkit 12.1+

## ⚡ Cài Đặt

### 1. Clone & cài đặt dependencies

```bash
cd DemoYolov11

# Cài PyTorch với CUDA (cho RTX 2050)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# Cài các dependencies còn lại
pip install -r requirements.txt
```

### 2. Cấu hình Telegram Bot

1. Mở Telegram, tìm **@BotFather**
2. Gửi `/newbot` → đặt tên → nhận **Bot Token**
3. Mở bot của bạn, gửi 1 tin nhắn bất kỳ
4. Truy cập: `https://api.telegram.org/bot<TOKEN>/getUpdates`
5. Tìm `"chat":{"id": XXXXXXX}` → đó là **Chat ID**

### 3. Tạo file `.env`

```bash
copy .env.example .env
```

Sửa file `.env`:
```
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=987654321
```

## 🎮 Sử Dụng

### Webcam (Mặc định)
```bash
python main.py --source 0 --show
```

### Video file
```bash
python main.py --source path/to/video.mp4 --show
```

### Ảnh
```bash
python main.py --source path/to/image.jpg --show
```

### Đầy đủ tính năng (Demo)
```bash
python main.py --source 0 --dashboard --telegram --pose --show
```

### Chỉ Dashboard (không hiển thị cửa sổ OpenCV)
```bash
python main.py --source 0 --dashboard --telegram --pose
```
→ Mở trình duyệt: **http://localhost:5000**

## 🎯 Tham Số

| Tham số | Mô tả | Mặc định |
|---|---|---|
| `--source` | Webcam (0), video file, hoặc image | `0` |
| `--dashboard` | Bật web dashboard | OFF |
| `--telegram` | Bật gửi Telegram alert | OFF |
| `--pose` | Bật phân tích tư thế | OFF |
| `--show` | Hiển thị cửa sổ OpenCV | OFF |
| `--confidence` | Ngưỡng tin cậy (0-1) | `0.45` |
| `--model` | Đường dẫn model YOLO | `yolo11s.pt` |
| `--port` | Port dashboard | `5000` |

## 🔍 Tính Năng Phát Hiện

1. **Phát hiện vũ khí**: Dao, kéo (COCO pretrained)
2. **Theo dõi đối tượng**: BoTSORT với Re-ID — giữ ID ngay cả khi bị che khuất
3. **Phân tích khoảng cách**: Người cầm vũ khí → CRITICAL alert
4. **Phân tích tư thế**: Giơ tay tấn công, đá, đấm (YOLOv11-Pose)
5. **Di chuyển bất thường**: Phát hiện chạy nhanh đáng ngờ

## 📊 Mức Độ Cảnh Báo

| Level | Mô tả | Hành động |
|---|---|---|
| 🟢 LOW | An toàn | Giám sát |
| 🟡 MEDIUM | Di chuyển bất thường | Chú ý |
| 🟠 HIGH | Vũ khí phát hiện / Tư thế nguy hiểm | Cảnh báo |
| 🔴 CRITICAL | Người cầm vũ khí | Telegram + Âm thanh |

## 📁 Cấu Trúc Dự Án

```
DemoYolov11/
├── main.py                  # Entry point
├── config.py                # Cấu hình
├── requirements.txt         # Dependencies
├── botsort_reid.yaml        # Tracker config (BoTSORT + Re-ID)
├── .env                     # Telegram credentials
├── core/                    # Core AI modules
│   ├── detector.py          # YOLOv11 detection
│   ├── tracker.py           # Object tracking
│   ├── threat_analyzer.py   # Threat analysis
│   └── pose_analyzer.py     # Pose estimation
├── notifications/
│   └── telegram_notifier.py # Telegram alerts
├── dashboard/               # Web dashboard
│   ├── app.py               # Flask server
│   ├── templates/index.html # Dashboard UI
│   └── static/              # CSS + JS
├── database/
│   └── db_manager.py        # SQLite storage
├── utils/
│   └── image_utils.py       # Image processing
└── alerts/                  # Saved alert images
```
