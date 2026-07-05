#!/usr/bin/env python3
"""
Home Network Security Toolkit
==============================
Ethical security testing tool for YOUR OWN home network.
Tools: Network Scanner | Camera Vulnerability Checker | Network Monitor

Requirements:
    pip install scapy python-nmap psutil rich requests

Run as root/sudo for full functionality:
    sudo python3 home_network_security.py
"""

import os
import sys
import time
import socket
import threading
import subprocess
import ipaddress
from datetime import datetime

# ── Rich UI ──────────────────────────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.live import Live
    from rich import box
    from rich.prompt import Prompt
    from rich.columns import Columns
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

try:
    from scapy.all import ARP, Ether, srp, conf
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None

# ── Common CCTV / IoT ports ──────────────────────────────────────────────────
CCTV_PORTS = {
    80:    "HTTP Web Interface",
    443:   "HTTPS Web Interface",
    554:   "RTSP Video Stream",
    8080:  "HTTP Alt / Admin Panel",
    8443:  "HTTPS Alt",
    8554:  "RTSP Alt",
    9000:  "Management Port",
    37777: "Dahua CCTV",
    34567: "HikVision CCTV",
    8000:  "HikVision SDK",
}

# Known weak / default credentials for common CCTV brands
DEFAULT_CREDS = [
    ("admin",  "admin"),
    ("admin",  "12345"),
    ("admin",  "123456"),
    ("admin",  "password"),
    ("admin",  ""),
    ("root",   "root"),
    ("root",   ""),
    ("user",   "user"),
    ("admin",  "1234"),
    ("guest",  "guest"),
]

# MAC OUI prefix → brand mapping (partial list)
OUI_MAP = {
    "00:00:F0": "Samsung",
    "B8:AC:6F": "Hikvision",
    "C0:56:E3": "Hikvision",
    "8C:E7:48": "Dahua",
    "E0:50:8B": "Dahua",
    "3C:EF:8C": "Xiaomi",
    "60:55:F9": "TP-Link",
    "EC:17:2F": "TP-Link",
    "00:1A:79": "Ubiquiti",
    "DC:9F:DB": "Apple",
    "AC:BC:32": "Apple",
    "18:65:90": "Amazon",
    "FC:65:DE": "Amazon",
    "50:79:5A": "Hikvision",
    "44:19:B6": "Dahua",
}

# ─────────────────────────────────────────────────────────────────────────────
#  HELPER UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def get_local_ip():
    """Return machine's local IP on the default interface."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_network_cidr(local_ip):
    """Guess /24 subnet from local IP."""
    parts = local_ip.rsplit(".", 1)
    return f"{parts[0]}.0/24"


def lookup_vendor(mac):
    """Simple OUI lookup from MAC address."""
    prefix = mac.upper()[:8]
    return OUI_MAP.get(prefix, "Unknown")


def port_open(ip, port, timeout=1.0):
    """Check if a TCP port is open on the host."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False


def banner_grab(ip, port, timeout=2.0):
    """Grab a short banner from an open port."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((ip, port))
        s.sendall(b"HEAD / HTTP/1.0\r\n\r\n")
        data = s.recv(512).decode(errors="ignore")
        s.close()
        return data[:200].strip()
    except Exception:
        return ""


def ping(ip):
    """Quick ICMP ping check."""
    flag = "-n" if sys.platform == "win32" else "-c"
    result = subprocess.run(
        ["ping", flag, "1", "-W", "1", ip],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def print_banner():
    if RICH_AVAILABLE:
        banner = Panel.fit(
            "[bold cyan]🏠 Home Network Security Toolkit[/bold cyan]\n"
            "[dim]Ethical testing — for YOUR OWN network only[/dim]\n"
            "[yellow]Tools: Scanner | CCTV Checker | Monitor[/yellow]",
            border_style="cyan",
            padding=(1, 4),
        )
        console.print(banner)
    else:
        print("=" * 60)
        print("  Home Network Security Toolkit")
        print("  Ethical testing — for YOUR OWN network only")
        print("=" * 60)


# ─────────────────────────────────────────────────────────────────────────────
#  TOOL 1 — NETWORK SCANNER
# ─────────────────────────────────────────────────────────────────────────────

def arp_scan(network):
    """ARP scan using Scapy (requires root)."""
    devices = []
    if not SCAPY_AVAILABLE:
        return devices
    conf.verb = 0
    arp_req = ARP(pdst=network)
    ether = Ether(dst="ff:ff:ff:ff:ff:ff")
    packet = ether / arp_req
    answered, _ = srp(packet, timeout=3, retry=1)
    for sent, received in answered:
        ip = received.psrc
        mac = received.hwsrc
        try:
            hostname = socket.gethostbyaddr(ip)[0]
        except Exception:
            hostname = "—"
        devices.append({
            "ip":       ip,
            "mac":      mac,
            "vendor":   lookup_vendor(mac),
            "hostname": hostname,
        })
    devices.sort(key=lambda d: socket.inet_aton(d["ip"]))
    return devices


def ping_scan(network):
    """Fallback ping scan (no root needed). Slower."""
    devices = []
    lock = threading.Lock()
    net = ipaddress.ip_network(network, strict=False)
    hosts = list(net.hosts())

    def check(ip):
        ip_str = str(ip)
        if ping(ip_str):
            try:
                hostname = socket.gethostbyaddr(ip_str)[0]
            except Exception:
                hostname = "—"
            with lock:
                devices.append({
                    "ip":       ip_str,
                    "mac":      "N/A (no root)",
                    "vendor":   "—",
                    "hostname": hostname,
                })

    threads = []
    for host in hosts:
        t = threading.Thread(target=check, args=(host,), daemon=True)
        threads.append(t)
        t.start()
        if len([t for t in threads if t.is_alive()]) >= 50:
            time.sleep(0.05)

    for t in threads:
        t.join()

    devices.sort(key=lambda d: socket.inet_aton(d["ip"]))
    return devices


def run_network_scanner():
    local_ip = get_local_ip()
    network = get_network_cidr(local_ip)

    if RICH_AVAILABLE:
        console.print(f"\n[bold green]📡 Network Scanner[/bold green]")
        console.print(f"[dim]Your IP : {local_ip}[/dim]")
        console.print(f"[dim]Scanning: {network}[/dim]\n")
    else:
        print(f"\n[Network Scanner]  Your IP: {local_ip}  Scanning: {network}\n")

    devices = []
    is_root = (os.geteuid() == 0) if hasattr(os, 'geteuid') else False

    if SCAPY_AVAILABLE and is_root:
        if RICH_AVAILABLE:
            with console.status("[cyan]Running ARP scan…[/cyan]"):
                devices = arp_scan(network)
        else:
            print("Running ARP scan…")
            devices = arp_scan(network)
    else:
        if RICH_AVAILABLE:
            console.print("[yellow]⚠  No root — using ping scan (slower, less info)[/yellow]")
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as prog:
                prog.add_task("Pinging hosts…", total=None)
                devices = ping_scan(network)
        else:
            print("No root — using ping scan…")
            devices = ping_scan(network)

    if not devices:
        if RICH_AVAILABLE:
            console.print("[red]No devices found. Try running with sudo.[/red]")
        else:
            print("No devices found. Try running with sudo.")
        return []

    if RICH_AVAILABLE:
        table = Table(
            title=f"Devices on {network}", box=box.ROUNDED, border_style="cyan"
        )
        table.add_column("#",        style="dim",       width=4)
        table.add_column("IP",       style="bold white")
        table.add_column("MAC",      style="yellow")
        table.add_column("Vendor",   style="magenta")
        table.add_column("Hostname", style="green")
        for i, d in enumerate(devices, 1):
            table.add_row(str(i), d["ip"], d["mac"], d["vendor"], d["hostname"])
        console.print(table)
        console.print(f"\n[green]✅ {len(devices)} device(s) found.[/green]")
    else:
        print(f"\n{'#':>3}  {'IP':>15}  {'MAC':>17}  {'Vendor':>12}  Hostname")
        print("-" * 70)
        for i, d in enumerate(devices, 1):
            print(f"{i:>3}  {d['ip']:>15}  {d['mac']:>17}  {d['vendor']:>12}  {d['hostname']}")
        print(f"\n{len(devices)} device(s) found.")

    return devices


# ─────────────────────────────────────────────────────────────────────────────
#  TOOL 2 — CCTV VULNERABILITY CHECKER
# ─────────────────────────────────────────────────────────────────────────────

def check_cctv_ports(ip):
    """Check which CCTV-related ports are open."""
    open_ports = {}
    threads = []
    lock = threading.Lock()

    def probe(port, desc):
        if port_open(ip, port):
            banner = banner_grab(ip, port)
            with lock:
                open_ports[port] = {"desc": desc, "banner": banner}

    for port, desc in CCTV_PORTS.items():
        t = threading.Thread(target=probe, args=(port, desc), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()
    return open_ports


def check_default_credentials(ip, port):
    """Try default credentials on HTTP interface (non-destructive read-only check)."""
    if not REQUESTS_AVAILABLE:
        return []
    found = []
    for user, passwd in DEFAULT_CREDS:
        try:
            resp = requests.get(
                f"http://{ip}:{port}/",
                auth=(user, passwd),
                timeout=3,
                allow_redirects=True,
            )
            if resp.status_code in (200, 301, 302) and resp.status_code != 401:
                found.append((user, passwd, resp.status_code))
                break
        except Exception:
            pass
    return found


def run_cctv_checker(devices=None):
    if RICH_AVAILABLE:
        console.print(f"\n[bold green]🔒 CCTV Vulnerability Checker[/bold green]\n")
    else:
        print("\n[CCTV Vulnerability Checker]\n")

    if devices is None:
        devices = run_network_scanner()

    if not devices:
        return

    if RICH_AVAILABLE:
        target = Prompt.ask(
            "[cyan]Enter IP to check (or 'all' to scan every device)[/cyan]",
            default="all"
        )
    else:
        target = input("Enter IP to check (or 'all'): ").strip() or "all"

    targets = devices if target.lower() == "all" else [
        d for d in devices if d["ip"] == target
    ]
    if not targets:
        targets = [{"ip": target, "mac": "—", "vendor": "—", "hostname": "—"}]

    results = []

    for device in targets:
        ip = device["ip"]
        if RICH_AVAILABLE:
            console.rule(f"[cyan]{ip}[/cyan]  [{device.get('vendor','—')}]")
        else:
            print(f"\n--- {ip}  [{device.get('vendor','—')}] ---")

        open_ports = check_cctv_ports(ip)

        if not open_ports:
            if RICH_AVAILABLE:
                console.print("  [dim]No CCTV-related ports open → probably not a camera.[/dim]")
            else:
                print("  No CCTV-related ports open.")
            results.append({"ip": ip, "ports": {}, "creds": [], "risk": "LOW"})
            continue

        risk = "LOW"
        weak_creds = []

        if RICH_AVAILABLE:
            port_table = Table(box=box.SIMPLE, show_header=True, header_style="bold magenta")
            port_table.add_column("Port", width=7)
            port_table.add_column("Service")
            port_table.add_column("Banner (first 80 chars)", style="dim")
            for port, info in open_ports.items():
                port_table.add_row(str(port), info["desc"], info["banner"][:80])
            console.print(port_table)
        else:
            for port, info in open_ports.items():
                print(f"  PORT {port}: {info['desc']}")

        for port in (80, 8080, 8000, 443):
            if port in open_ports:
                if RICH_AVAILABLE:
                    with console.status(f"[yellow]Testing default credentials on port {port}…[/yellow]"):
                        weak_creds = check_default_credentials(ip, port)
                else:
                    print(f"  Testing default creds on port {port}…")
                    weak_creds = check_default_credentials(ip, port)
                if weak_creds:
                    break

        if open_ports:
            risk = "MEDIUM"
        if weak_creds:
            risk = "HIGH"

        risk_color = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red"}[risk]

        if RICH_AVAILABLE:
            if weak_creds:
                for u, p, code in weak_creds:
                    console.print(
                        f"  [red]⚠  Weak credential → user=[b]{u}[/b]  pass=[b]{p or '(empty)'}[/b]  HTTP {code}[/red]"
                    )
            else:
                console.print("  [green]✓  No default credentials matched.[/green]")
            console.print(f"  Risk level: [{risk_color}]{risk}[/{risk_color}]\n")
        else:
            if weak_creds:
                for u, p, code in weak_creds:
                    print(f"  ⚠  Weak cred: {u}/{p or '(empty)'}  HTTP {code}")
            print(f"  Risk: {risk}\n")

        results.append({"ip": ip, "ports": open_ports, "creds": weak_creds, "risk": risk})

    high = sum(1 for r in results if r["risk"] == "HIGH")
    med  = sum(1 for r in results if r["risk"] == "MEDIUM")

    if RICH_AVAILABLE:
        console.print(Panel(
            f"[red]HIGH risk  : {high}[/red]\n"
            f"[yellow]MEDIUM risk: {med}[/yellow]\n"
            f"[green]LOW risk   : {len(results)-high-med}[/green]\n\n"
            "[dim]Recommendation: Change default passwords & disable unused ports.[/dim]",
            title="🔍 Vulnerability Summary",
            border_style="magenta",
        ))
    else:
        print(f"\nSummary → HIGH: {high}  MEDIUM: {med}  LOW: {len(results)-high-med}")
        print("Recommendation: Change default passwords & disable unused ports.")

    return results


# ─────────────────────────────────────────────────────────────────────────────
#  TOOL 3 — NETWORK MONITOR
# ─────────────────────────────────────────────────────────────────────────────

class NetworkMonitor:
    """Real-time bandwidth & connection monitor using psutil."""

    def __init__(self, interval=2.0):
        self.interval = interval
        self._prev_io = {}
        self._prev_time = time.time()

    def _get_net_io(self):
        if not PSUTIL_AVAILABLE:
            return {}
        stats = psutil.net_io_counters(pernic=True)
        return {iface: (s.bytes_sent, s.bytes_recv) for iface, s in stats.items()}

    def _human(self, bps):
        for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
            if bps < 1024:
                return f"{bps:6.1f} {unit}"
            bps /= 1024
        return f"{bps:.1f} GB/s"

    def _active_connections(self):
        if not PSUTIL_AVAILABLE:
            return []
        conns = []
        try:
            for c in psutil.net_connections(kind="inet"):
                if c.status == "ESTABLISHED" and c.raddr:
                    try:
                        proc = psutil.Process(c.pid).name() if c.pid else "—"
                    except Exception:
                        proc = "—"
                    conns.append({
                        "local":  f"{c.laddr.ip}:{c.laddr.port}",
                        "remote": f"{c.raddr.ip}:{c.raddr.port}",
                        "proc":   proc,
                    })
        except Exception:
            pass
        return conns[:15]

    def _build_bw_table(self):
        now = time.time()
        dt = now - self._prev_time
        cur_io = self._get_net_io()

        table = Table(
            title=f"📡 Interface Bandwidth  [{datetime.now().strftime('%H:%M:%S')}]",
            box=box.ROUNDED, border_style="cyan", expand=True
        )
        table.add_column("Interface",   style="bold white")
        table.add_column("↑ Upload",    style="yellow")
        table.add_column("↓ Download",  style="green")
        table.add_column("Total Sent",  style="dim")
        table.add_column("Total Recv",  style="dim")

        for iface, (sent, recv) in cur_io.items():
            if iface in self._prev_io:
                ps, pr = self._prev_io[iface]
                up_bps   = (sent - ps) / max(dt, 0.001)
                down_bps = (recv - pr) / max(dt, 0.001)
            else:
                up_bps = down_bps = 0.0
            table.add_row(
                iface,
                self._human(up_bps),
                self._human(down_bps),
                self._human(sent),
                self._human(recv),
            )

        self._prev_io   = cur_io
        self._prev_time = now
        return table

    def _build_conn_table(self):
        conns = self._active_connections()
        table = Table(
            title="🔗 Active Connections (top 15)",
            box=box.SIMPLE, border_style="magenta", expand=True
        )
        table.add_column("Local",   style="white")
        table.add_column("Remote",  style="cyan")
        table.add_column("Process", style="yellow")
        for c in conns:
            table.add_row(c["local"], c["remote"], c["proc"])
        return table

    def run(self):
        if not PSUTIL_AVAILABLE:
            print("psutil not installed. Run:  pip install psutil")
            return

        if not RICH_AVAILABLE:
            print("Network Monitor (press Ctrl+C to stop)\n")
            self._prev_io = self._get_net_io()
            while True:
                time.sleep(self.interval)
                cur = self._get_net_io()
                dt  = self.interval
                for iface, (s, r) in cur.items():
                    if iface in self._prev_io:
                        ps, pr = self._prev_io[iface]
                        print(f"{iface:12}  ↑ {self._human((s-ps)/dt)}  ↓ {self._human((r-pr)/dt)}")
                self._prev_io = cur
                print()
            return

        console.print(Panel("[dim]Press [bold]Ctrl+C[/bold] to stop monitoring.[/dim]", border_style="dim"))
        self._prev_io   = self._get_net_io()
        self._prev_time = time.time()

        with Live(refresh_per_second=1) as live:
            while True:
                bw_table   = self._build_bw_table()
                conn_table = self._build_conn_table()
                live.update(Columns([bw_table, conn_table]))
                time.sleep(self.interval)


def run_network_monitor():
    if RICH_AVAILABLE:
        console.print(f"\n[bold green]📊 Network Monitor[/bold green]\n")
    else:
        print("\n[Network Monitor]\n")
    monitor = NetworkMonitor(interval=2.0)
    try:
        monitor.run()
    except KeyboardInterrupt:
        if RICH_AVAILABLE:
            console.print("\n[yellow]Monitor stopped.[/yellow]")
        else:
            print("\nMonitor stopped.")


# ─────────────────────────────────────────────────────────────────────────────
#  DEPENDENCY CHECK
# ─────────────────────────────────────────────────────────────────────────────

def check_dependencies():
    missing = []
    if not SCAPY_AVAILABLE:    missing.append("scapy")
    if not PSUTIL_AVAILABLE:   missing.append("psutil")
    if not RICH_AVAILABLE:     missing.append("rich")
    if not REQUESTS_AVAILABLE: missing.append("requests")
    if missing:
        msg = f"Missing packages → pip install {' '.join(missing)}"
        if RICH_AVAILABLE:
            console.print(Panel(
                f"[yellow]Some packages missing. Install with:[/yellow]\n\n"
                f"[bold cyan]pip install {' '.join(missing)}[/bold cyan]",
                title="⚠  Dependencies",
                border_style="yellow",
            ))
        else:
            print(msg)


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN MENU
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print_banner()
    check_dependencies()

    while True:
        if RICH_AVAILABLE:
            console.print("\n[bold]Choose a tool:[/bold]")
            console.print("  [cyan]1[/cyan]  📡 Network Scanner")
            console.print("  [cyan]2[/cyan]  🔒 CCTV Vulnerability Checker")
            console.print("  [cyan]3[/cyan]  📊 Network Monitor")
            console.print("  [cyan]4[/cyan]  🚀 Run All Three")
            console.print("  [cyan]0[/cyan]  ❌ Exit")
            choice = Prompt.ask("\n[bold cyan]Your choice[/bold cyan]", default="1")
        else:
            print("\nChoose a tool:")
            print("  1  Network Scanner")
            print("  2  CCTV Vulnerability Checker")
            print("  3  Network Monitor")
            print("  4  Run All Three")
            print("  0  Exit")
            choice = input("Your choice [1]: ").strip() or "1"

        if choice == "0":
            if RICH_AVAILABLE:
                console.print("[dim]Goodbye![/dim]")
            else:
                print("Goodbye!")
            break
        elif choice == "1":
            run_network_scanner()
        elif choice == "2":
            run_cctv_checker()
        elif choice == "3":
            run_network_monitor()
        elif choice == "4":
            devices = run_network_scanner()
            run_cctv_checker(devices)
            run_network_monitor()
        else:
            if RICH_AVAILABLE:
                console.print("[red]Invalid choice. Enter 0-4.[/red]")
            else:
                print("Invalid choice.")


if __name__ == "__main__":
    main()
