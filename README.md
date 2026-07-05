# DVR_DOWN 🏠📷

> **Apne ghar ke CCTV cameras ko laptop par dekhein — WiFi se detect karo, live feed watch karo, body detection karo.**

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python)
![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux-lightgrey?style=flat-square)
![Apple Silicon](https://img.shields.io/badge/Apple%20M--series-MPS%20GPU-black?style=flat-square&logo=apple)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

---

## 📦 What's Inside

| Tool | File | Description |
|------|------|-------------|
| 🔍 **Network Scanner** | `home_network_security.py` | WiFi par sabhi devices dhundho, CCTV ports check karo |
| 📹 **Camera Dashboard** | `camera_dashboard.py` | Live CCTV feeds laptop par grid mein dekho |
| 🏃 **DensePose** | `densepose_demo/run_densepose.py` | Camera feed par real-time body detection |

---

## 🚀 Quick Start

### Install
```bash
git clone https://github.com/divyaannsh/DVR_DOWN.git
cd DVR_DOWN
pip install rich scapy psutil requests mediapipe opencv-python Pillow torch
```

### 1️⃣ Network Scanner — Cameras Dhundho
```bash
python3 home_network_security.py
```
- WiFi par saare devices list karta hai
- CCTV-related ports check karta hai (RTSP, HTTP, HikVision, Dahua)
- Default passwords test karta hai (security audit)
- Real-time bandwidth monitor

### 2️⃣ Camera Dashboard — Live Feed Dekho
```bash
# Auto scan + connect
python3 camera_dashboard.py

# Specific camera IP
python3 camera_dashboard.py --ip 192.168.1.100

# Direct RTSP URL
python3 camera_dashboard.py --rtsp rtsp://admin:admin@192.168.1.100:554/

# With body detection overlay
python3 camera_dashboard.py --densepose
```

### 3️⃣ DensePose — Body Detection
```bash
# Pehle setup run karo (models download honge ~45MB)
python3 densepose_demo/setup_check.py

# Demo image par run karo
python3 densepose_demo/run_densepose.py --demo

# Apni photo par
python3 densepose_demo/run_densepose.py --image photo.jpg

# Live webcam
python3 densepose_demo/run_densepose.py --webcam
```

---

## 🖥️ Camera Dashboard Controls

| Key | Action |
|-----|--------|
| `q` | Quit |
| `d` | DensePose body detection ON/OFF |
| `s` | Screenshot save karo |
| `1` - `9` | Camera ka fullscreen mode |
| `g` | Grid view par wapas aao |

---

## 🧠 DensePose — Body Parts Detected

Camera feed par yeh body parts color-coded dikhaata hai:

```
Head · Neck · Torso · Left/Right Arms
Upper Arm · Forearm · Hand
Left/Right Legs · Thigh · Shin · Foot
```

**Uses:** MediaPipe Tasks API v0.10+ with Apple MPS GPU acceleration

---

## 🔧 Supported Camera Streams

| Type | Format |
|------|--------|
| RTSP | `rtsp://user:pass@IP:554/` |
| HTTP MJPEG | `http://IP/video` |
| HikVision | `rtsp://admin:pass@IP:554/Streaming/Channels/101` |
| Dahua | `rtsp://admin:pass@IP:554/cam/realmonitor?channel=1` |
| CP Plus | `rtsp://admin:pass@IP:554/` |

---

## ⚙️ System Requirements

| Requirement | Minimum |
|------------|---------|
| Python | 3.10+ |
| RAM | 4 GB (8 GB recommended) |
| OS | macOS (Apple Silicon preferred) / Linux |
| GPU | Apple MPS (M1/M2/M3/M4) or CUDA — CPU fallback available |

---

## 📁 Project Structure

```
DVR_DOWN/
├── home_network_security.py    # Network Scanner + CCTV Checker + Monitor
├── camera_dashboard.py         # Live Camera Feed Dashboard
├── densepose_demo/
│   ├── run_densepose.py        # Body Detection Engine
│   ├── setup_check.py          # Dependency + Model Checker
│   ├── README.md               # DensePose-specific docs
│   ├── models/                 # Auto-downloaded (not in git)
│   └── outputs/                # Saved results (not in git)
├── screenshots/                # Dashboard screenshots
├── .gitignore
└── README.md
```

---

## 🔒 Ethical Use Only

> This tool is built for **monitoring your own home/property cameras only.**
> Accessing cameras you don't own or have permission to access is illegal under
> **IT Act 2000 (India)** and similar laws worldwide.

---

## 📸 Remote Access Setup

Agar aap apne ghar ke cameras ko kahi se bhi dekhna chahte hain:

1. **DVR/NVR ka IP address note karo** (DVR menu → Network Settings)
2. **Router mein Port 554 forward karo** → DVR IP par
3. **Ghar ka public IP note karo** → `whatismyip.com`
4. **PG ya office se connect karo:**
   ```bash
   python3 camera_dashboard.py --rtsp rtsp://admin:PASSWORD@PUBLIC_IP:554/
   ```

---

## 📄 License

MIT License — Free to use for personal/educational purposes.

---

*Made with ❤️ for home security monitoring*
