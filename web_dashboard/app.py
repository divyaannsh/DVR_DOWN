#!/usr/bin/env python3
"""
NetGuard Pro — Backend Server
Flask + SocketIO powered real-time network dashboard.
"""

import os, sys, time, socket, threading, subprocess, ipaddress
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

try:
    import psutil
    PSUTIL_OK = True
except ImportError:
    PSUTIL_OK = False

try:
    from scapy.all import ARP, Ether, srp, conf as scapy_conf
    SCAPY_OK = True
except ImportError:
    SCAPY_OK = False

# ── App setup ─────────────────────────────────────────────────────────────────
BASE  = Path(__file__).parent
app   = Flask(__name__, template_folder=str(BASE / "templates"),
              static_folder=str(BASE / "static"))
app.config["SECRET_KEY"] = "netguard-secret-2024"
sio   = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ── State ─────────────────────────────────────────────────────────────────────
STATE = {
    "devices":    [],        # [{ip, mac, hostname, vendor, status, last_seen}]
    "alerts":     [],        # [{time, type, message, ip}]
    "bandwidth":  {},        # {iface: {up, down, total_up, total_down}}
    "known_macs": set(),     # set of known MAC addresses
    "cameras":    [],        # [{url, label}]
    "scanning":   False,
}
STATE_LOCK = threading.Lock()

OUI_MAP = {
    "B8:AC:6F": "Hikvision", "C0:56:E3": "Hikvision",
    "8C:E7:48": "Dahua",     "E0:50:8B": "Dahua",
    "3C:EF:8C": "Xiaomi",    "60:55:F9": "TP-Link",
    "EC:17:2F": "TP-Link",   "DC:9F:DB": "Apple",
    "AC:BC:32": "Apple",     "18:65:90": "Amazon",
    "FC:65:DE": "Amazon",    "50:79:5A": "Hikvision",
    "44:19:B6": "Dahua",
}

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]; s.close(); return ip
    except: return "127.0.0.1"

def vendor_from_mac(mac):
    prefix = mac.upper()[:8] if mac and mac != "N/A" else ""
    return OUI_MAP.get(prefix, "Unknown")

def ping(ip, timeout=1):
    r = subprocess.run(["ping","-c","1","-W",str(timeout), ip],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0

def arp_scan(network):
    if not SCAPY_OK or os.geteuid() != 0:
        return []
    scapy_conf.verb = 0
    pkt = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=network)
    answered, _ = srp(pkt, timeout=3, retry=1)
    devices = []
    for _, recv in answered:
        ip, mac = recv.psrc, recv.hwsrc
        try: hostname = socket.gethostbyaddr(ip)[0]
        except: hostname = "—"
        devices.append({"ip": ip, "mac": mac,
                         "hostname": hostname, "vendor": vendor_from_mac(mac)})
    return devices

def ping_scan(network):
    net   = ipaddress.ip_network(network, strict=False)
    found = []
    lock  = threading.Lock()

    def chk(ip_str):
        if ping(ip_str, timeout=1):
            try: hn = socket.gethostbyaddr(ip_str)[0]
            except: hn = "—"
            with lock:
                found.append({"ip": ip_str, "mac": "N/A",
                               "hostname": hn, "vendor": "—"})

    threads = []
    for h in list(net.hosts()):
        t = threading.Thread(target=chk, args=(str(h),), daemon=True)
        threads.append(t); t.start()
        if len([x for x in threads if x.is_alive()]) >= 50:
            time.sleep(0.05)
    for t in threads: t.join()
    return sorted(found, key=lambda d: socket.inet_aton(d["ip"]))

# ── Background workers ────────────────────────────────────────────────────────

def scan_loop():
    local_ip = get_local_ip()
    network  = local_ip.rsplit(".", 1)[0] + ".0/24"
    while True:
        with STATE_LOCK: STATE["scanning"] = True
        sio.emit("scan_start", {"network": network})

        devices = arp_scan(network) or ping_scan(network)
        now     = datetime.now().strftime("%H:%M:%S")

        with STATE_LOCK:
            current_macs = {d["mac"] for d in devices if d["mac"] != "N/A"}
            # New device alert
            new_macs = current_macs - STATE["known_macs"]
            for mac in new_macs:
                dev = next((d for d in devices if d["mac"] == mac), {})
                alert = {
                    "time": now, "type": "new_device",
                    "message": f"New device joined: {dev.get('ip','?')} ({dev.get('vendor','Unknown')})",
                    "ip": dev.get("ip", "?"),
                }
                STATE["alerts"].insert(0, alert)
                STATE["alerts"] = STATE["alerts"][:50]  # keep last 50
                sio.emit("alert", alert)

            # Mark all as online
            for d in devices:
                d["status"]    = "online"
                d["last_seen"] = now

            STATE["devices"]    = devices
            STATE["known_macs"] = STATE["known_macs"] | current_macs
            STATE["scanning"]   = False

        sio.emit("devices_update", {"devices": devices, "ts": now})
        time.sleep(30)   # rescan every 30s


def bandwidth_loop():
    prev = {}
    prev_time = time.time()

    while True:
        time.sleep(2)
        if not PSUTIL_OK:
            continue
        now     = time.time()
        dt      = max(now - prev_time, 0.001)
        cur_io  = psutil.net_io_counters(pernic=True)
        result  = {}

        for iface, stats in cur_io.items():
            if iface == "lo": continue
            if iface in prev:
                ps, pr = prev[iface]
                up   = (stats.bytes_sent - ps) / dt
                down = (stats.bytes_recv - pr) / dt
            else:
                up = down = 0.0
            result[iface] = {
                "up":        round(up   / 1024, 2),   # KB/s
                "down":      round(down / 1024, 2),
                "total_up":  round(stats.bytes_sent   / 1024**2, 2),  # MB
                "total_down": round(stats.bytes_recv  / 1024**2, 2),
            }
            prev[iface] = (stats.bytes_sent, stats.bytes_recv)

        prev_time = now
        with STATE_LOCK: STATE["bandwidth"] = result
        sio.emit("bandwidth_update", {"bandwidth": result,
                                       "ts": datetime.now().strftime("%H:%M:%S")})


def system_stats_loop():
    while True:
        time.sleep(3)
        if not PSUTIL_OK: continue
        stats = {
            "cpu":    psutil.cpu_percent(interval=None),
            "ram":    psutil.virtual_memory().percent,
            "ram_gb": round(psutil.virtual_memory().used / 1024**3, 1),
            "ram_total": round(psutil.virtual_memory().total / 1024**3, 1),
            "ts":     datetime.now().strftime("%H:%M:%S"),
        }
        sio.emit("system_stats", stats)

# ── REST API ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    local_ip = get_local_ip()
    network  = local_ip.rsplit(".", 1)[0] + ".0/24"
    return render_template("index.html", local_ip=local_ip, network=network)

@app.route("/api/devices")
def api_devices():
    with STATE_LOCK: return jsonify(STATE["devices"])

@app.route("/api/alerts")
def api_alerts():
    with STATE_LOCK: return jsonify(STATE["alerts"])

@app.route("/api/bandwidth")
def api_bandwidth():
    with STATE_LOCK: return jsonify(STATE["bandwidth"])

@app.route("/api/cameras", methods=["GET"])
def api_cameras_get():
    with STATE_LOCK: return jsonify(STATE["cameras"])

@app.route("/api/cameras", methods=["POST"])
def api_cameras_post():
    data = request.json
    with STATE_LOCK:
        STATE["cameras"].append({"url": data["url"], "label": data.get("label","Camera")})
    sio.emit("cameras_update", STATE["cameras"])
    return jsonify({"ok": True})

@app.route("/api/cameras/<int:idx>", methods=["DELETE"])
def api_cameras_delete(idx):
    with STATE_LOCK:
        if 0 <= idx < len(STATE["cameras"]):
            STATE["cameras"].pop(idx)
    sio.emit("cameras_update", STATE["cameras"])
    return jsonify({"ok": True})

@app.route("/api/stats")
def api_stats():
    if not PSUTIL_OK: return jsonify({})
    mem = psutil.virtual_memory()
    return jsonify({
        "cpu":       psutil.cpu_percent(),
        "ram":       mem.percent,
        "ram_used":  round(mem.used / 1024**3, 1),
        "ram_total": round(mem.total / 1024**3, 1),
    })

# ── SocketIO events ───────────────────────────────────────────────────────────

@sio.on("connect")
def on_connect():
    with STATE_LOCK:
        emit("devices_update", {"devices": STATE["devices"],
                                 "ts": datetime.now().strftime("%H:%M:%S")})
        emit("bandwidth_update", {"bandwidth": STATE["bandwidth"],
                                   "ts": datetime.now().strftime("%H:%M:%S")})
        emit("alerts_init", STATE["alerts"])
        emit("cameras_update", STATE["cameras"])

@sio.on("request_scan")
def on_request_scan():
    threading.Thread(target=scan_loop_once, daemon=True).start()

def scan_loop_once():
    local_ip = get_local_ip()
    network  = local_ip.rsplit(".", 1)[0] + ".0/24"
    sio.emit("scan_start", {"network": network})
    devices = arp_scan(network) or ping_scan(network)
    now = datetime.now().strftime("%H:%M:%S")
    for d in devices:
        d["status"] = "online"; d["last_seen"] = now
    with STATE_LOCK:
        STATE["devices"] = devices
    sio.emit("devices_update", {"devices": devices, "ts": now})

# ── Start background threads ──────────────────────────────────────────────────

def start_background():
    threading.Thread(target=scan_loop,         daemon=True).start()
    threading.Thread(target=bandwidth_loop,    daemon=True).start()
    threading.Thread(target=system_stats_loop, daemon=True).start()

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*55)
    print("  🛡️  NetGuard Pro — Web Dashboard")
    print(f"  Local IP : {get_local_ip()}")
    print("  URL      : http://localhost:8080")
    print("  Press Ctrl+C to stop")
    print("="*55 + "\n")
    start_background()
    sio.run(app, host="0.0.0.0", port=8080, debug=False, allow_unsafe_werkzeug=True)
