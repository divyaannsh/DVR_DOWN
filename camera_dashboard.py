#!/usr/bin/env python3
"""
Home Camera Dashboard
======================
Apne ghar ke CCTV cameras ko laptop par dekhein.

Features:
  - WiFi par cameras auto-detect karo
  - RTSP / HTTP streams se connect karo
  - Multiple camera feeds ek saath dekhein (grid view)
  - Optional: DensePose body detection overlay

Usage:
    python3 camera_dashboard.py                    # auto-scan + dashboard
    python3 camera_dashboard.py --scan             # sirf scan, koi UI nahi
    python3 camera_dashboard.py --rtsp rtsp://...  # direct RTSP URL
    python3 camera_dashboard.py --ip 192.168.1.10  # specific camera IP

Keys:
    q  →  quit
    d  →  toggle DensePose overlay
    s  →  screenshot save karo
    1-9→  fullscreen mode uss camera ka
    g  →  back to grid view
"""

import os, sys, time, socket, threading, argparse, subprocess, ipaddress
from pathlib import Path
from datetime import datetime

# ── dependency check ─────────────────────────────────────────────────────────
def _check():
    missing = []
    for mod, pkg in [("cv2","opencv-python"),("numpy","numpy"),("rich","rich")]:
        try: __import__(mod)
        except ImportError: missing.append(pkg)
    if missing:
        print(f"Missing: pip install {' '.join(missing)}")
        sys.exit(1)
_check()

import cv2
import numpy as np
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from rich.prompt import Prompt

console = Console()

# ── paths ─────────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).parent
SCREENSHOTS = ROOT / "screenshots"
SCREENSHOTS.mkdir(exist_ok=True)

# ── common RTSP / HTTP stream URL patterns ────────────────────────────────────
RTSP_PATTERNS = [
    "rtsp://{ip}:554/",
    "rtsp://{ip}:554/stream",
    "rtsp://{ip}:554/live",
    "rtsp://{ip}:554/cam/realmonitor",
    "rtsp://{ip}:8554/",
    "rtsp://admin:@{ip}:554/",
    "rtsp://admin:admin@{ip}:554/",
    "rtsp://admin:12345@{ip}:554/",
]
HTTP_PATTERNS = [
    "http://{ip}/video",
    "http://{ip}:8080/video",
    "http://{ip}/mjpg/video.mjpg",
    "http://{ip}/cgi-bin/mjpg/video.cgi",
    "http://{ip}:80/videostream.cgi",
]

CCTV_PORTS = [554, 8554, 80, 8080, 8000, 9000, 37777, 34567]

# ─────────────────────────────────────────────────────────────────────────────
#  NETWORK SCANNER
# ─────────────────────────────────────────────────────────────────────────────

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]; s.close(); return ip
    except: return "192.168.1.1"

def port_open(ip, port, timeout=0.8):
    try:
        with socket.create_connection((ip, port), timeout=timeout): return True
    except: return False

def ping(ip):
    result = subprocess.run(
        ["ping", "-c", "1", "-W", "1", ip],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    return result.returncode == 0

def scan_network(network_cidr):
    """Ping-scan the /24 subnet and check CCTV ports."""
    console.print(f"\n[cyan]Scanning {network_cidr}…[/cyan]")
    net   = ipaddress.ip_network(network_cidr, strict=False)
    hosts = list(net.hosts())
    alive = []
    lock  = threading.Lock()
    done  = [0]

    def check_host(ip_str):
        if ping(ip_str):
            open_ports = [p for p in CCTV_PORTS if port_open(ip_str, p)]
            if open_ports:
                try: hostname = socket.gethostbyaddr(ip_str)[0]
                except: hostname = "—"
                with lock:
                    alive.append({
                        "ip":       ip_str,
                        "ports":    open_ports,
                        "hostname": hostname,
                    })
        with lock: done[0] += 1

    threads = []
    for host in hosts:
        t = threading.Thread(target=check_host, args=(str(host),), daemon=True)
        threads.append(t); t.start()
        if len([t for t in threads if t.is_alive()]) >= 60:
            time.sleep(0.02)
    for t in threads: t.join()

    alive.sort(key=lambda d: socket.inet_aton(d["ip"]))
    return alive

def probe_stream(ip):
    """Try all RTSP/HTTP patterns and return first that opens."""
    patterns = RTSP_PATTERNS + HTTP_PATTERNS
    for pattern in patterns:
        url = pattern.format(ip=ip)
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 2000)
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 2000)
        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                cap.release()
                return url
            cap.release()
    return None

# ─────────────────────────────────────────────────────────────────────────────
#  CAMERA STREAM WORKER
# ─────────────────────────────────────────────────────────────────────────────

class CameraStream:
    """Background thread that continuously reads frames from a stream URL."""

    def __init__(self, url: str, label: str = ""):
        self.url    = url
        self.label  = label or url
        self.frame  = None
        self.alive  = False
        self.error  = None
        self._lock  = threading.Lock()
        self._stop  = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)

        if not cap.isOpened():
            self.error = "Cannot open stream"
            return

        self.alive = True
        while not self._stop.is_set():
            ret, frame = cap.read()
            if not ret:
                self.error = "Stream disconnected"
                self.alive = False
                break
            with self._lock:
                self.frame = frame.copy()

        cap.release()
        self.alive = False

    def read(self):
        with self._lock:
            return self.frame.copy() if self.frame is not None else None

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=3)

# ─────────────────────────────────────────────────────────────────────────────
#  OPTIONAL DENSEPOSE OVERLAY
# ─────────────────────────────────────────────────────────────────────────────

class BodyDetector:
    """Lightweight wrapper — loads MediaPipe only if available."""

    def __init__(self):
        self.available = False
        self._load()

    def _load(self):
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision as mp_vision

            pose_model = ROOT / "densepose_demo" / "models" / "pose_landmarker_heavy.task"
            if not pose_model.exists():
                console.print("[yellow]⚠  DensePose model not found. Run setup first.[/yellow]")
                return

            opts = mp_vision.PoseLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(pose_model)),
                running_mode=mp_vision.RunningMode.IMAGE,
                num_poses=4,
                min_pose_detection_confidence=0.4,
                output_segmentation_masks=False,
            )
            self._det  = mp_vision.PoseLandmarker.create_from_options(opts)
            self._mp   = mp
            self._vision = mp_vision
            self.available = True
            console.print("[green]✅ DensePose body detector loaded[/green]")
        except Exception as e:
            console.print(f"[yellow]DensePose not loaded: {e}[/yellow]")

    BONE_PAIRS = [
        (0,1),(1,2),(2,3),(3,7),(0,4),(4,5),(5,6),(6,8),
        (11,12),(11,13),(13,15),(12,14),(14,16),
        (11,23),(12,24),(23,24),
        (23,25),(25,27),(27,29),(27,31),
        (24,26),(26,28),(28,30),(28,32),
    ]
    BONE_COLOR = (0, 230, 120)
    DOT_COLOR  = (255, 255, 255)

    def draw(self, frame: np.ndarray) -> np.ndarray:
        if not self.available:
            return frame
        try:
            h, w = frame.shape[:2]
            rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_img = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
            result = self._det.detect(mp_img)
            out = frame.copy()
            if result.pose_landmarks:
                for person in result.pose_landmarks:
                    pts = [(int(l.x*w), int(l.y*h)) for l in person]
                    for s, e in self.BONE_PAIRS:
                        if s < len(pts) and e < len(pts):
                            cv2.line(out, pts[s], pts[e], self.BONE_COLOR, 2, cv2.LINE_AA)
                    for p in pts:
                        cv2.circle(out, p, 4, self.DOT_COLOR, -1)
                        cv2.circle(out, p, 4, (0,0,0), 1)
            return out
        except:
            return frame

# ─────────────────────────────────────────────────────────────────────────────
#  GRID DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

PLACEHOLDER_COLOR = (20, 20, 35)
FONT = cv2.FONT_HERSHEY_SIMPLEX

def make_placeholder(w, h, text, color=(60,60,80)):
    img = np.full((h, w, 3), PLACEHOLDER_COLOR, dtype=np.uint8)
    cv2.rectangle(img, (2, 2), (w-2, h-2), color, 1)
    tw, th = cv2.getTextSize(text, FONT, 0.5, 1)[0]
    cv2.putText(img, text, ((w-tw)//2, (h+th)//2),
                FONT, 0.5, (120, 120, 180), 1, cv2.LINE_AA)
    return img

def tile_frames(frames, grid_w, grid_h, cell_w, cell_h):
    """Arrange frames into a grid image."""
    canvas = np.full((grid_h * cell_h, grid_w * cell_w, 3),
                     PLACEHOLDER_COLOR, dtype=np.uint8)
    for idx, frame in enumerate(frames):
        if idx >= grid_w * grid_h:
            break
        row, col = divmod(idx, grid_w)
        y1, y2 = row * cell_h, (row+1) * cell_h
        x1, x2 = col * cell_w, (col+1) * cell_w
        if frame is not None:
            cell = cv2.resize(frame, (cell_w, cell_h))
        else:
            cell = make_placeholder(cell_w, cell_h, "No signal")
        canvas[y1:y2, x1:x2] = cell
    return canvas

def draw_cell_label(canvas, idx, label, status, grid_w, cell_w, cell_h):
    row, col = divmod(idx, grid_w)
    x = col * cell_w + 6
    y = row * cell_h + 18
    color = (0, 220, 100) if status == "live" else (80, 80, 200)
    bg_w  = min(cell_w - 10, 8 + len(label) * 8)
    cv2.rectangle(canvas, (x-2, y-14), (x + bg_w, y+4), (0,0,0), -1)
    cv2.putText(canvas, f"● {label}", (x, y), FONT, 0.45, color, 1, cv2.LINE_AA)

class Dashboard:
    WIN = "Home Camera Dashboard — q:quit  d:DensePose  s:screenshot  1-9:fullscreen  g:grid"

    def __init__(self, streams: list[CameraStream], enable_densepose=False):
        self.streams = streams
        self.dp      = BodyDetector() if enable_densepose else None
        self.dp_on   = enable_densepose and (self.dp is not None and self.dp.available)
        self.fullscreen_idx = None   # None = grid, int = single cam
        self.saved   = 0

        n = len(streams)
        self.grid_w = min(n, 3)
        self.grid_h = (n + self.grid_w - 1) // self.grid_w
        # Target dashboard size
        total_w = min(1200, max(640,  self.grid_w * 320))
        total_h = min(800,  max(480,  self.grid_h * 240))
        self.cell_w = total_w // self.grid_w
        self.cell_h = total_h // self.grid_h

    def _overlay_info(self, frame, label, fps_str=""):
        h, w = frame.shape[:2]
        bar  = 28
        cv2.rectangle(frame, (0, 0), (w, bar), (10, 10, 10), -1)
        cv2.putText(frame, f"● {label}  {fps_str}", (8, 19),
                    FONT, 0.52, (0, 220, 255), 1, cv2.LINE_AA)
        ts = datetime.now().strftime("%H:%M:%S")
        tw = cv2.getTextSize(ts, FONT, 0.45, 1)[0][0]
        cv2.putText(frame, ts, (w - tw - 8, 19),
                    FONT, 0.45, (180, 180, 180), 1, cv2.LINE_AA)
        return frame

    def run(self):
        cv2.namedWindow(self.WIN, cv2.WINDOW_NORMAL)
        fps_tracker = {i: [] for i in range(len(self.streams))}

        while True:
            t0 = time.time()

            if self.fullscreen_idx is not None:
                # ── Single camera fullscreen ──────────────────────────────────
                idx = self.fullscreen_idx
                s   = self.streams[idx]
                raw = s.read()
                if raw is not None:
                    if self.dp_on and self.dp:
                        raw = self.dp.draw(raw)
                    self._overlay_info(raw, s.label,
                                       f"{np.mean(fps_tracker[idx]):.1f} FPS"
                                       if fps_tracker[idx] else "")
                    canvas = raw
                else:
                    canvas = make_placeholder(
                        self.cell_w * self.grid_w,
                        self.cell_h * self.grid_h,
                        f"{s.label} — No signal", (80, 40, 40)
                    )
            else:
                # ── Grid view ─────────────────────────────────────────────────
                frames = []
                for idx, s in enumerate(self.streams):
                    raw = s.read()
                    if raw is not None:
                        if self.dp_on and self.dp:
                            raw = self.dp.draw(raw)
                        raw = self._overlay_info(raw, s.label)
                    frames.append(raw)

                canvas = tile_frames(frames,
                                     self.grid_w, self.grid_h,
                                     self.cell_w, self.cell_h)

            # FPS counter
            dt = max(time.time() - t0, 0.001)
            if self.fullscreen_idx is not None:
                fps_tracker[self.fullscreen_idx].append(1.0 / dt)
                if len(fps_tracker[self.fullscreen_idx]) > 15:
                    fps_tracker[self.fullscreen_idx].pop(0)

            # DensePose badge
            if self.dp_on:
                h = canvas.shape[0]
                cv2.putText(canvas, "DensePose ON", (8, h - 10),
                            FONT, 0.5, (0, 230, 120), 1, cv2.LINE_AA)

            cv2.imshow(self.WIN, canvas)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('d'):
                if self.dp and self.dp.available:
                    self.dp_on = not self.dp_on
                    status = "ON" if self.dp_on else "OFF"
                    console.print(f"[cyan]DensePose: {status}[/cyan]")
                else:
                    console.print("[yellow]DensePose model not loaded.[/yellow]")
            elif key == ord('s'):
                p = SCREENSHOTS / f"cam_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                cv2.imwrite(str(p), canvas)
                self.saved += 1
                console.print(f"[green]Screenshot saved: {p}[/green]")
            elif key == ord('g'):
                self.fullscreen_idx = None
            elif ord('1') <= key <= ord('9'):
                idx = key - ord('1')
                if idx < len(self.streams):
                    self.fullscreen_idx = idx

        cv2.destroyAllWindows()
        for s in self.streams:
            s.stop()
        console.print(f"[dim]Dashboard closed. Screenshots saved: {self.saved}[/dim]")


# ─────────────────────────────────────────────────────────────────────────────
#  SCAN + CONNECT FLOW
# ─────────────────────────────────────────────────────────────────────────────

def scan_and_connect(densepose=False):
    local_ip = get_local_ip()
    network  = local_ip.rsplit(".", 1)[0] + ".0/24"

    console.print(Panel.fit(
        f"[bold cyan]🏠 Home Camera Dashboard[/bold cyan]\n"
        f"[dim]Your IP : {local_ip}[/dim]\n"
        f"[dim]Network : {network}[/dim]",
        border_style="cyan"
    ))

    # Step 1: Scan network
    devices = scan_network(network)

    if not devices:
        console.print("[red]No devices with open camera ports found.[/red]")
        console.print("[dim]Tip: Make sure you are on the same WiFi as the cameras.[/dim]")
        return

    # Step 2: Show found devices
    table = Table(title="📡 Devices Found", box=box.ROUNDED, border_style="cyan")
    table.add_column("#")
    table.add_column("IP",       style="bold white")
    table.add_column("Ports",    style="yellow")
    table.add_column("Hostname", style="green")
    for i, d in enumerate(devices, 1):
        table.add_row(str(i), d["ip"],
                      ", ".join(map(str, d["ports"])),
                      d["hostname"])
    console.print(table)

    # Step 3: Ask which to connect
    console.print("\n[bold]Kaunsa camera connect karein?[/bold]")
    console.print("  [cyan]all[/cyan]  — saare cameras")
    console.print("  [cyan]1,2[/cyan]  — specific numbers (comma se alag)")
    choice = Prompt.ask("[bold cyan]Choice[/bold cyan]", default="all")

    if choice.strip().lower() == "all":
        selected = devices
    else:
        indices = [int(x.strip())-1 for x in choice.split(",") if x.strip().isdigit()]
        selected = [devices[i] for i in indices if 0 <= i < len(devices)]

    if not selected:
        console.print("[red]Koi camera select nahi kiya.[/red]")
        return

    # Step 4: Probe streams
    streams = []
    for d in selected:
        ip = d["ip"]
        with console.status(f"[cyan]Connecting to {ip}…[/cyan]"):
            url = probe_stream(ip)

        if url:
            console.print(f"  [green]✅ {ip} → {url}[/green]")
            streams.append(CameraStream(url, label=ip))
        else:
            console.print(f"  [yellow]⚠  {ip} — stream open nahi hua (auth required?)[/yellow]")
            console.print(f"     [dim]Apna RTSP URL manually enter karo:[/dim]")
            manual = Prompt.ask(f"     [cyan]RTSP URL for {ip} (skip ke liye Enter)[/cyan]",
                                default="skip")
            if manual.lower() != "skip" and manual.startswith("rtsp"):
                streams.append(CameraStream(manual, label=ip))

    if not streams:
        console.print("[red]Koi stream connect nahi hua.[/red]")
        return

    console.print(f"\n[green]{len(streams)} camera(s) connected! Dashboard khul raha hai…[/green]")
    console.print("[dim]Keys: q=quit  d=DensePose  s=screenshot  1-9=fullscreen  g=grid[/dim]\n")
    time.sleep(1)

    dash = Dashboard(streams, enable_densepose=densepose)
    dash.run()


# ─────────────────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Home Camera Dashboard")
    ap.add_argument("--scan",    action="store_true", help="Sirf network scan karo")
    ap.add_argument("--rtsp",    nargs="+",           help="Direct RTSP URL(s)")
    ap.add_argument("--ip",      nargs="+",           help="Specific camera IP(s) to probe")
    ap.add_argument("--densepose", action="store_true", help="DensePose body detection ON")
    args = ap.parse_args()

    if args.scan:
        local_ip = get_local_ip()
        network  = local_ip.rsplit(".", 1)[0] + ".0/24"
        devices  = scan_network(network)
        if devices:
            table = Table(title="Camera Devices", box=box.ROUNDED)
            table.add_column("IP"); table.add_column("Ports"); table.add_column("Hostname")
            for d in devices:
                table.add_row(d["ip"], str(d["ports"]), d["hostname"])
            console.print(table)
        else:
            console.print("[red]No camera devices found.[/red]")

    elif args.rtsp:
        # Direct RTSP URLs provided
        streams = [CameraStream(url, label=f"Cam {i+1}")
                   for i, url in enumerate(args.rtsp)]
        console.print(f"[green]{len(streams)} stream(s) connected.[/green]")
        dash = Dashboard(streams, enable_densepose=args.densepose)
        dash.run()

    elif args.ip:
        # Probe specific IPs
        streams = []
        for ip in args.ip:
            with console.status(f"Probing {ip}…"):
                url = probe_stream(ip)
            if url:
                console.print(f"[green]✅ {ip} → {url}[/green]")
                streams.append(CameraStream(url, label=ip))
            else:
                console.print(f"[red]❌ {ip} — no stream found[/red]")
        if streams:
            dash = Dashboard(streams, enable_densepose=args.densepose)
            dash.run()

    else:
        # Default: auto scan + interactive connect
        scan_and_connect(densepose=args.densepose)


if __name__ == "__main__":
    main()
