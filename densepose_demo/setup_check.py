#!/usr/bin/env python3
"""
DensePose Setup Checker (MediaPipe Tasks API v0.10+)
"""
import subprocess, sys, importlib

REQUIRED = [
    ("mediapipe",  "mediapipe"),
    ("cv2",        "opencv-python"),
    ("PIL",        "Pillow"),
    ("numpy",      "numpy"),
    ("torch",      "torch"),
    ("requests",   "requests"),
    ("matplotlib", "matplotlib"),
]

def install(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

print("=" * 55)
print("  DensePose Setup Checker")
print("=" * 55)

all_ok = True
for module, pip_name in REQUIRED:
    try:
        importlib.import_module(module)
        print(f"  ✅  {pip_name}")
    except ImportError:
        print(f"  ⚙️   Installing {pip_name}…")
        try:
            install(pip_name)
            print(f"  ✅  {pip_name} installed")
        except Exception as e:
            print(f"  ❌  {pip_name}: {e}")
            all_ok = False

print("\n── Device Info ──────────────────────────")
import torch
print(f"  PyTorch : {torch.__version__}")
if torch.backends.mps.is_available():
    print("  Device  : Apple GPU (MPS) ✅ — Fast!")
elif torch.cuda.is_available():
    print(f"  Device  : CUDA GPU ✅")
else:
    print("  Device  : CPU")

print("\n── MediaPipe Tasks API Check ────────────")
try:
    import mediapipe as mp
    print(f"  MediaPipe version : {mp.__version__}")

    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision
    print(f"  Tasks API         : ✅ Available")

    # Check PoseLandmarker is accessible
    _ = mp_vision.PoseLandmarker
    print(f"  PoseLandmarker    : ✅")

    # Check ImageSegmenter
    _ = mp_vision.ImageSegmenter
    print(f"  ImageSegmenter    : ✅")

except Exception as e:
    print(f"  ❌ Error: {e}")
    all_ok = False

print("\n" + "=" * 55)
if all_ok:
    print("  ✅ All checks passed! Ready to run:\n")
    print("  python3 run_densepose.py --demo")
    print("  python3 run_densepose.py --webcam")
    print("  python3 run_densepose.py --image your_photo.jpg")
else:
    print("  ⚠️  Some issues found. Try: pip install mediapipe --upgrade")
print("=" * 55)
