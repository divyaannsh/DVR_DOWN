# DensePose Demo 🏃

Human body part estimation using **MediaPipe** (with optional Detectron2 upgrade).

Works on **Mac M1/M2/M3/M4** with Apple GPU (MPS) acceleration.

---

## Quick Start

```bash
# Step 1: Install dependencies
python3 setup_check.py

# Step 2: Run demo (downloads a sample image automatically)
python3 run_densepose.py --demo

# Step 3: Try with your own image
python3 run_densepose.py --image your_photo.jpg

# Step 4: Live webcam
python3 run_densepose.py --webcam
```

---

## Modes

| Command | Description |
|---------|-------------|
| `--demo` | Download sample image and run |
| `--image path` | Run on a single image |
| `--folder path` | Run on all images in a folder |
| `--webcam` | Live webcam feed |

## Webcam Controls

| Key | Action |
|-----|--------|
| `q` | Quit |
| `s` | Save current frame |

## Output

All results saved to `outputs/` folder.

---

## Body Parts Detected

- Head / Face
- Torso (Front & Back)
- Upper & Lower Arms (Left/Right)
- Upper & Lower Legs (Left/Right)
- Hands & Feet
