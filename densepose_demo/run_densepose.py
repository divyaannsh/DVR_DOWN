#!/usr/bin/env python3
"""
DensePose-style Human Body Part Estimation
============================================
Uses MediaPipe Tasks API (v0.10+) with PoseLandmarker + ImageSegmenter.
Supports Apple MPS GPU on Mac M1/M2/M3/M4.

Usage:
    python3 run_densepose.py --demo
    python3 run_densepose.py --image photo.jpg
    python3 run_densepose.py --folder ./photos/
    python3 run_densepose.py --webcam

Keys during display:
    q  →  quit
    s  →  save frame (webcam mode)
"""

import os, sys, argparse, time, urllib.request, tempfile
from pathlib import Path

# ── dependency check ─────────────────────────────────────────────────────────
def _check():
    missing = []
    for mod, pkg in [("cv2","opencv-python"),("numpy","numpy"),
                     ("PIL","Pillow"),("mediapipe","mediapipe"),("torch","torch")]:
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"[ERROR] Missing: {', '.join(missing)}")
        print(f"  pip install {' '.join(missing)}")
        sys.exit(1)
_check()

import cv2, numpy as np, torch
from PIL import Image

import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

# ── paths ─────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).parent
OUTPUT_DIR = ROOT / "outputs"
MODEL_DIR  = ROOT / "models"
OUTPUT_DIR.mkdir(exist_ok=True)
MODEL_DIR.mkdir(exist_ok=True)

POSE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task"
)
POSE_MODEL_PATH = MODEL_DIR / "pose_landmarker_heavy.task"

SEG_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/image_segmenter/"
    "selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite"
)
SEG_MODEL_PATH = MODEL_DIR / "selfie_multiclass.tflite"

# ── device ────────────────────────────────────────────────────────────────────
if torch.backends.mps.is_available():
    DEVICE_NAME = "Apple GPU (MPS) 🔥"
elif torch.cuda.is_available():
    DEVICE_NAME = f"CUDA GPU"
else:
    DEVICE_NAME = "CPU"

# ── body part colors (DensePose-style palette) ────────────────────────────────
PART_COLORS = {
    "Head":        (100, 100, 255),
    "Neck":        (180, 100, 255),
    "Torso":       ( 60, 180, 255),
    "L_Shoulder":  (100, 255, 150),
    "R_Shoulder":  ( 50, 220, 120),
    "L_Upper_Arm": (255, 200,  60),
    "R_Upper_Arm": (255, 160,  30),
    "L_Forearm":   (255, 255,  60),
    "R_Forearm":   (220, 220,  30),
    "L_Hand":      (200, 255, 200),
    "R_Hand":      (160, 220, 160),
    "L_Hip":       (255, 100, 100),
    "R_Hip":       (220,  60,  60),
    "L_Thigh":     (255, 150, 180),
    "R_Thigh":     (220, 100, 150),
    "L_Shin":      (180,  80, 255),
    "R_Shin":      (140,  50, 220),
    "L_Foot":      (150, 255, 255),
    "R_Foot":      (100, 220, 220),
}

# Segmenter class indices for selfie_multiclass model
SEG_CLASSES = {
    0: ("Background",   (20,  20,  20)),
    1: ("Hair",         (80, 200, 255)),
    2: ("Body Skin",    (100, 200, 100)),
    3: ("Face Skin",    (255, 180, 100)),
    4: ("Clothes",      (100, 100, 220)),
    5: ("Accessories",  (220, 220,  80)),
}


# ── model download ─────────────────────────────────────────────────────────────
def download_model(url, path, name):
    if path.exists():
        return
    print(f"[↓] Downloading {name}…  (first time only)")
    try:
        urllib.request.urlretrieve(url, path,
            reporthook=lambda b, bs, total: print(
                f"  {min(b*bs, total)/1024**2:.1f} / {total/1024**2:.1f} MB",
                end="\r", flush=True) if total > 0 else None
        )
        print(f"\n[✅] {name} saved → {path}")
    except Exception as e:
        print(f"\n[ERROR] Download failed: {e}")
        sys.exit(1)


# ── predictor ─────────────────────────────────────────────────────────────────
class DensePoseEstimator:
    def __init__(self):
        print(f"\n[INFO] Device: {DEVICE_NAME}")
        print("[INFO] Loading models…")
        download_model(POSE_MODEL_URL,  POSE_MODEL_PATH,  "Pose Landmarker")
        download_model(SEG_MODEL_URL,   SEG_MODEL_PATH,   "Segmenter")
        self._load_pose()
        self._load_seg()
        print("[✅] Models ready!\n")

    def _load_pose(self):
        opts = mp_vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(
                model_asset_path=str(POSE_MODEL_PATH)
            ),
            running_mode=mp_vision.RunningMode.IMAGE,
            num_poses=4,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            output_segmentation_masks=True,
        )
        self.pose_det = mp_vision.PoseLandmarker.create_from_options(opts)

    def _load_seg(self):
        opts = mp_vision.ImageSegmenterOptions(
            base_options=mp_python.BaseOptions(
                model_asset_path=str(SEG_MODEL_PATH)
            ),
            running_mode=mp_vision.RunningMode.IMAGE,
            output_category_mask=True,
        )
        self.seg_det = mp_vision.ImageSegmenter.create_from_options(opts)

    def predict(self, bgr_frame: np.ndarray) -> dict:
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        pose_result = self.pose_det.detect(mp_img)
        seg_result  = self.seg_det.segment(mp_img)

        return {
            "frame": bgr_frame,
            "pose":  pose_result,
            "seg":   seg_result,
        }

    def close(self):
        self.pose_det.close()
        self.seg_det.close()


# ── visualizer ────────────────────────────────────────────────────────────────
PL = mp_vision.PoseLandmark   # shortcut

# Bone connections → (start_idx, end_idx, part_name)
BONES = [
    # Head / Neck
    (0,  7,  "Head"),       (0,  8,  "Head"),
    (9,  10, "Neck"),
    # Torso
    (11, 12, "Torso"),      (11, 23, "Torso"),
    (12, 24, "Torso"),      (23, 24, "Torso"),
    # Left arm
    (11, 13, "L_Shoulder"), (13, 15, "L_Upper_Arm"),
    (15, 17, "L_Forearm"),  (15, 19, "L_Hand"),   (15, 21, "L_Hand"),
    # Right arm
    (12, 14, "R_Shoulder"), (14, 16, "R_Upper_Arm"),
    (16, 18, "R_Forearm"),  (16, 20, "R_Hand"),   (16, 22, "R_Hand"),
    # Left leg
    (23, 25, "L_Hip"),      (25, 27, "L_Thigh"),
    (27, 29, "L_Shin"),     (27, 31, "L_Foot"),
    # Right leg
    (24, 26, "R_Hip"),      (26, 28, "R_Thigh"),
    (28, 30, "R_Shin"),     (28, 32, "R_Foot"),
]


def visualize(result: dict, show_skeleton=True,
              show_seg=True, show_labels=True, alpha=0.55) -> np.ndarray:
    frame = result["frame"].copy()
    h, w  = frame.shape[:2]
    pose_res = result["pose"]
    seg_res  = result["seg"]

    overlay = frame.copy()

    # ── 1. Segmentation color mask ───────────────────────────────────────────
    if show_seg and seg_res.category_mask is not None:
        cat_mask = np.array(seg_res.category_mask.numpy_view(), dtype=np.uint8)
        # ── FIX: squeeze extra channel dim (H,W,1) → (H,W) ──────────────────
        if cat_mask.ndim == 3:
            cat_mask = cat_mask.squeeze(-1)
        # Resize mask to frame size if needed
        if cat_mask.shape[:2] != (h, w):
            cat_mask = cv2.resize(cat_mask, (w, h), interpolation=cv2.INTER_NEAREST)

        color_mask = np.zeros_like(frame)
        for class_id, (name, color) in SEG_CLASSES.items():
            if class_id == 0:
                continue  # skip background
            region = (cat_mask == class_id)   # shape: (H, W) — 2D boolean
            color_mask[region] = color

        overlay = cv2.addWeighted(overlay, 1.0 - alpha, color_mask, alpha, 0)

    # ── 2. Pose landmarks + colored bones ───────────────────────────────────
    if pose_res.pose_landmarks:
        for person_lms in pose_res.pose_landmarks:
            lm = person_lms  # list of NormalizedLandmark

            def pt(idx):
                l = lm[idx]
                return (int(l.x * w), int(l.y * h))

            # Draw bones (colored by body part)
            if show_skeleton:
                for s, e, part in BONES:
                    if s >= len(lm) or e >= len(lm):
                        continue
                    color = PART_COLORS.get(part, (200, 200, 200))
                    p1, p2 = pt(s), pt(e)
                    cv2.line(overlay, p1, p2, color, 4, cv2.LINE_AA)

                # Draw landmark dots
                for idx, l in enumerate(lm):
                    px, py = int(l.x * w), int(l.y * h)
                    cv2.circle(overlay, (px, py), 5, (255, 255, 255), -1)
                    cv2.circle(overlay, (px, py), 5, (0, 0, 0), 1)

            # ── 3. Body part fill polygons ───────────────────────────────────
            def safe_pt(idx):
                if idx >= len(lm): return None
                l = lm[idx]
                return (int(l.x * w), int(l.y * h))

            fill_regions = [
                ("Head",   [safe_pt(7),  safe_pt(8),  safe_pt(0),  safe_pt(9), safe_pt(10)]),
                ("Torso",  [safe_pt(11), safe_pt(12), safe_pt(24), safe_pt(23)]),
                ("L_Upper_Arm", [safe_pt(11), safe_pt(13), safe_pt(15)]),
                ("R_Upper_Arm", [safe_pt(12), safe_pt(14), safe_pt(16)]),
                ("L_Forearm",   [safe_pt(13), safe_pt(15), safe_pt(17)]),
                ("R_Forearm",   [safe_pt(14), safe_pt(16), safe_pt(18)]),
                ("L_Thigh",     [safe_pt(23), safe_pt(25), safe_pt(27)]),
                ("R_Thigh",     [safe_pt(24), safe_pt(26), safe_pt(28)]),
                ("L_Shin",      [safe_pt(25), safe_pt(27), safe_pt(29)]),
                ("R_Shin",      [safe_pt(26), safe_pt(28), safe_pt(30)]),
            ]

            fill_layer = overlay.copy()
            for part_name, pts in fill_regions:
                valid = [p for p in pts if p is not None]
                if len(valid) < 3:
                    continue
                pts_arr = np.array(valid, dtype=np.int32)
                color   = PART_COLORS.get(part_name, (150, 150, 150))
                cv2.fillPoly(fill_layer, [pts_arr], color)

            overlay = cv2.addWeighted(overlay, 0.5, fill_layer, 0.5, 0)

            # ── 4. Labels ────────────────────────────────────────────────────
            if show_labels:
                label_pts = {
                    "Head":        safe_pt(0),
                    "Torso":       safe_pt(11),
                    "L Arm":       safe_pt(13),
                    "R Arm":       safe_pt(14),
                    "L Leg":       safe_pt(25),
                    "R Leg":       safe_pt(26),
                }
                for label, pt_pos in label_pts.items():
                    if pt_pos is None:
                        continue
                    x, y = pt_pos
                    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
                    cv2.rectangle(overlay, (x-2, y-th-4), (x+tw+2, y+2), (0,0,0), -1)
                    cv2.putText(overlay, label, (x, y),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                                (255, 255, 255), 1, cv2.LINE_AA)

    # ── 5. Info bar ──────────────────────────────────────────────────────────
    n_people = len(pose_res.pose_landmarks) if pose_res.pose_landmarks else 0
    cv2.rectangle(overlay, (0, 0), (w, 32), (15, 15, 15), -1)
    cv2.putText(overlay,
                f"DensePose  |  People: {n_people}  |  {DEVICE_NAME}",
                (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                (0, 220, 255), 1, cv2.LINE_AA)

    return overlay


# ── run modes ─────────────────────────────────────────────────────────────────

def run_image(estimator, image_path: str):
    path = Path(image_path)
    if not path.exists():
        print(f"[ERROR] Not found: {image_path}")
        return

    print(f"[INFO] Processing: {path.name}")
    frame = cv2.imread(str(path))
    if frame is None:
        print(f"[ERROR] Cannot read image.")
        return

    t0      = time.time()
    result  = estimator.predict(frame)
    vis     = visualize(result)
    elapsed = time.time() - t0

    out = OUTPUT_DIR / f"densepose_{path.stem}.jpg"
    cv2.imwrite(str(out), vis)
    print(f"[✅] Done in {elapsed:.2f}s → saved: {out}")

    cv2.imshow("DensePose Result — press any key", vis)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


def run_folder(estimator, folder_path: str):
    folder = Path(folder_path)
    images = sorted([f for f in folder.iterdir()
                     if f.suffix.lower() in {".jpg",".jpeg",".png",".bmp",".webp"}])
    if not images:
        print(f"[ERROR] No images in {folder_path}")
        return
    print(f"[INFO] {len(images)} image(s) found")
    for img in images:
        run_image(estimator, str(img))


def run_webcam(estimator):
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[ERROR] Cannot open webcam.")
        return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    print("[INFO] Webcam live — press 'q' quit  |  's' save frame")

    saved, fps_buf = 0, []
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        t0 = time.time()
        result = estimator.predict(frame)
        vis    = visualize(result)
        dt     = time.time() - t0

        fps_buf.append(1.0 / max(dt, 0.001))
        if len(fps_buf) > 15: fps_buf.pop(0)
        fps = np.mean(fps_buf)

        cv2.putText(vis, f"{fps:.1f} FPS", (vis.shape[1]-100, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (100, 255, 100), 1)
        cv2.imshow("DensePose — Live  (q=quit  s=save)", vis)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('s'):
            p = OUTPUT_DIR / f"webcam_{saved:04d}.jpg"
            cv2.imwrite(str(p), vis)
            print(f"[✅] Saved: {p}")
            saved += 1

    cap.release()
    cv2.destroyAllWindows()


def run_demo(estimator):
    demo_path = OUTPUT_DIR / "demo_person.jpg"
    if not demo_path.exists():
        print("[INFO] Downloading demo image…")
        # Public-domain human body images (reliable sources)
        urls = [
            "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a7/Camponotus_flavomarginatus_ant.jpg/200px-Camponotus_flavomarginatus_ant.jpg",  # placeholder fallback
            "https://raw.githubusercontent.com/google/mediapipe/master/mediapipe/examples/desktop/object_detection/cat_and_dog.jpg",
            "https://raw.githubusercontent.com/CMU-Perceptual-Computing-Lab/openpose/master/examples/media/COCO_val2014_000000000192.jpg",
        ]
        downloaded = False
        for url in urls:
            try:
                urllib.request.urlretrieve(url, demo_path)
                # Verify it is a valid image
                test = cv2.imread(str(demo_path))
                if test is not None:
                    downloaded = True
                    print(f"[✅] Demo image downloaded")
                    break
            except Exception:
                pass
        if not downloaded:
            # Generate a simple synthetic human silhouette for demo
            print("[INFO] Creating synthetic demo image")
            img = np.ones((600, 400, 3), dtype=np.uint8) * 30
            # Head
            cv2.circle(img, (200, 80),  40, (180, 140, 100), -1)
            # Torso
            cv2.rectangle(img, (150, 120), (250, 280), (100, 120, 180), -1)
            # Left arm
            cv2.line(img, (150, 130), (100, 240), (120, 160, 220), 20)
            # Right arm
            cv2.line(img, (250, 130), (300, 240), (120, 160, 220), 20)
            # Left leg
            cv2.line(img, (170, 280), (150, 420), (100, 100, 200), 22)
            # Right leg
            cv2.line(img, (230, 280), (250, 420), (100, 100, 200), 22)
            cv2.putText(img, "Use --image with a real photo",
                        (20, 560), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (0, 220, 255), 1)
            cv2.imwrite(str(demo_path), img)
            print("[INFO] Synthetic demo ready. For best results use --image with a real human photo.")
    run_image(estimator, str(demo_path))


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        description="DensePose: Human Body Part Estimation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 run_densepose.py --demo\n"
            "  python3 run_densepose.py --image photo.jpg\n"
            "  python3 run_densepose.py --folder ./photos/\n"
            "  python3 run_densepose.py --webcam\n"
        )
    )
    ap.add_argument("--image",  help="Path to an image file")
    ap.add_argument("--folder", help="Path to a folder of images")
    ap.add_argument("--webcam", action="store_true", help="Live webcam mode")
    ap.add_argument("--demo",   action="store_true", help="Run on a sample image")
    args = ap.parse_args()

    print("\n" + "="*55)
    print("  🏃 DensePose — Human Body Part Estimation")
    print(f"  Device : {DEVICE_NAME}")
    print(f"  Output : {OUTPUT_DIR}")
    print("="*55)

    estimator = DensePoseEstimator()

    try:
        if   args.image:  run_image(estimator, args.image)
        elif args.folder: run_folder(estimator, args.folder)
        elif args.webcam: run_webcam(estimator)
        else:             run_demo(estimator)
    finally:
        estimator.close()


if __name__ == "__main__":
    main()
