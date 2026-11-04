#!/usr/bin/env python3
"""Servora Hardware Agent
=======================

Connects a restaurant's local hardware (receipt / KOT / label printers, cash
drawers, customer pole displays, weighing scales) to the cloud Servora POS.

The cloud cannot reach devices on the restaurant LAN, so this small program
runs on the counter PC / Raspberry Pi / mini-PC and *pulls* work:

    GET  {server}/api/hardware/agent      (header X-Device-Key: <key>)
         -> {restaurant, devices:[...], jobs:[...]}
    POST {server}/api/hardware/agent
         <- {results:[{id, ok, error}], scale_weight?, online_devices?}

Only the Python standard library is required. Optional extras are imported
lazily, only when a device actually needs them:

    pyusb     USB printers               address "04b8:0202" (vendor:product hex)
    pyserial  serial printers / pole displays / weighing scales
              address "COM3", "/dev/ttyUSB0", optional "@9600" baud suffix
    pywin32   "win:<Printer Name>" -> RAW print via the Windows spooler

Usage:
    python servora_agent.py setup                         # first-time wizard
    python servora_agent.py run                           # start the agent
    python servora_agent.py test --address 192.168.1.50   # test page
    python servora_agent.py discover                      # find printers
"""
from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import logging
import logging.handlers
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

__version__ = "1.0.0"

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.environ.get("SERVORA_AGENT_CONFIG") or os.path.join(HERE, "config.json")
DEFAULT_SERVER = "https://servora.vercel.app"
AGENT_PATH = "/api/hardware/agent"

DEFAULTS = {
    "server_url": DEFAULT_SERVER,
    "device_key": "",
    "poll_interval": 2.0,          # seconds between polls
    "health_interval": 60.0,       # seconds between printer health checks
    "max_backoff": 60.0,           # cap for exponential backoff on outages
    "retries": 3,                  # delivery attempts per job
    "retry_backoff": 1.0,          # first retry delay (doubles each time)
    "socket_timeout": 8.0,         # printer connection timeout
    "http_timeout": 20.0,          # cloud request timeout
    "default_baud": 9600,
    "log_file": os.path.join(HERE, "servora-agent.log"),
    "log_level": "INFO",
}

# Connections the agent is responsible for (browser/cloud/hid are excluded server side).
AGENT_CONNECTIONS = ("network", "usb", "serial", "bluetooth")

log = logging.getLogger("servora")

# ESC/POS snippets used locally (test page, plain-text fallback)
ESC, GS = b"\x1b", b"\x1d"
INIT = ESC + b"@"
CUT = GS + b"V\x41\x03"


class DeliveryError(Exception):
    """A job could not be delivered to a device."""


class MissingExtra(DeliveryError):
    """An optional dependency is needed for this device type."""


# --------------------------------------------------------------------------- #
# Config & logging
# --------------------------------------------------------------------------- #
def load_config(path=DEFAULT_CONFIG_PATH):
    cfg = dict(DEFAULTS)
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    # environment overrides (handy for docker / systemd)
    if os.environ.get("SERVORA_SERVER_URL"):
        cfg["server_url"] = os.environ["SERVORA_SERVER_URL"]
    if os.environ.get("SERVORA_DEVICE_KEY"):
        cfg["device_key"] = os.environ["SERVORA_DEVICE_KEY"]
    return cfg


def save_config(cfg, path=DEFAULT_CONFIG_PATH):
    keep = {k: cfg[k] for k in ("server_url", "device_key", "poll_interval") if k in cfg}
    for k, v in cfg.items():
        if k not in keep and k in DEFAULTS and v != DEFAULTS[k]:
            keep[k] = v
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(keep, fh, indent=2)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)  # the device key is a secret
    except OSError:
        pass


def setup_logging(cfg=None, console=True):
    cfg = cfg or DEFAULTS
    root = logging.getLogger("servora")
    root.setLevel(getattr(logging, str(cfg.get("log_level", "INFO")).upper(), logging.INFO))
    root.handlers[:] = []
    root.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    if console:
        h = logging.StreamHandler()
        h.setFormatter(fmt)
        root.addHandler(h)
    lf = cfg.get("log_file")
    if lf:
        try:
            fh = logging.handlers.RotatingFileHandler(lf, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except OSError as e:  # read-only dir etc. -- console logging still works
            root.warning("Cannot write log file %s: %s", lf, e)


# --------------------------------------------------------------------------- #
# Cloud client
# --------------------------------------------------------------------------- #
class AuthError(Exception):
    pass


class ServoraClient:
    def __init__(self, server_url, device_key, timeout=20.0):
        self.url = server_url.rstrip("/") + AGENT_PATH
        self.key = device_key
        self.timeout = timeout

    def _request(self, method, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url, data=data, method=method)
        req.add_header("X-Device-Key", self.key)
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "ServoraHardwareAgent/" + __version__)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise AuthError("Device key rejected by server (HTTP %s). Re-run setup with the key from "
                                "Settings -> Hardware." % e.code)
            raise
        return json.loads(raw.decode() or "{}")

    def poll(self):
        return self._request("GET")

    def report(self, payload):
        return self._request("POST", payload)


# --------------------------------------------------------------------------- #
# Address parsing
# --------------------------------------------------------------------------- #
def parse_network_address(address, default_port=9100):
    a = address.strip()
    if a.startswith("tcp://"):
        a = a[6:]
    if a.startswith("["):  # [ipv6]:port
        host, _, rest = a[1:].partition("]")
        port = int(rest.lstrip(":")) if rest.lstrip(":") else default_port
        return host, port
    if a.count(":") == 1:
        host, port = a.split(":")
        return host, int(port)
    return a, default_port


def parse_serial_address(address, default_baud=9600):
    """'COM3' / '/dev/ttyUSB0@19200' / 'COM4@9600,8N1' -> (port, baud)"""
    a = address.strip()
    if a.startswith("serial:"):
        a = a[7:]
    port, _, rest = a.partition("@")
    baud = default_baud
    if rest:
        m = re.match(r"\d+", rest)
        if m:
            baud = int(m.group())
    return port.strip(), baud


def parse_usb_address(address):
    """'04b8:0202' or '0x04b8:0x0202' -> (0x04b8, 0x0202)"""
    a = address.strip().lower()
    if a.startswith("usb:"):
        a = a[4:]
    parts = a.split(":")
    if len(parts) < 2:
        raise DeliveryError("USB address must be 'vendor:product' in hex, e.g. 04b8:0202 (got %r)" % address)
    return int(parts[0], 16), int(parts[1], 16)


_MAC_RE = re.compile(r"^([0-9a-f]{2}[:-]){5}[0-9a-f]{2}$", re.I)


def parse_bt_address(address):
    """'00:11:22:33:44:55' or '00:11:22:33:44:55@2' (RFCOMM channel) -> (mac, channel)"""
    a = address.strip()
    mac, _, ch = a.partition("@")
    if not ch and "#" in mac:
        mac, _, ch = mac.partition("#")
    return mac.replace("-", ":").upper(), int(ch or 1)


def looks_like_serial_port(address):
    a = address.strip().split("@")[0]
    return bool(re.match(r"^(COM\d+|/dev/\S+|serial:)", a, re.I))


# --------------------------------------------------------------------------- #
# Drivers: each takes (address, data: bytes, cfg) and raises on failure
# --------------------------------------------------------------------------- #
def _lazy(module, pip_name, purpose):
    try:
        return __import__(module, fromlist=["_"])
    except ImportError:
        raise MissingExtra("%s requires the optional package '%s'. Install it with:  "
                           "python -m pip install %s" % (purpose, pip_name, pip_name))


def send_network(address, data, cfg=DEFAULTS):
    host, port = parse_network_address(address)
    timeout = float(cfg.get("socket_timeout", 8))
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall(data)
            try:
                s.shutdown(socket.SHUT_WR)
            except OSError:
                pass
    except OSError as e:
        raise DeliveryError("network printer %s:%s unreachable: %s" % (host, port, e))


def send_serial(address, data, cfg=DEFAULTS):
    serial = _lazy("serial", "pyserial", "Serial/COM devices")
    port, baud = parse_serial_address(address, int(cfg.get("default_baud", 9600)))
    try:
        with serial.Serial(port, baudrate=baud, timeout=float(cfg.get("socket_timeout", 8)),
                           write_timeout=float(cfg.get("socket_timeout", 8))) as ser:
            ser.write(data)
            ser.flush()
    except Exception as e:  # serial.SerialException and OS errors
        raise DeliveryError("serial port %s: %s" % (port, e))


def send_usb(address, data, cfg=DEFAULTS):
    usb_core = _lazy("usb.core", "pyusb", "USB printers")
    usb_util = _lazy("usb.util", "pyusb", "USB printers")
    vid, pid = parse_usb_address(address)
    dev = usb_core.find(idVendor=vid, idProduct=pid)
    if dev is None:
        raise DeliveryError("USB printer %04x:%04x not found (is it plugged in and powered on?)" % (vid, pid))
    try:
        try:
            if dev.is_kernel_driver_active(0):
                dev.detach_kernel_driver(0)  # Linux: release from usblp
        except (NotImplementedError, usb_core.USBError):
            pass
        try:
            dev.set_configuration()
        except usb_core.USBError:
            pass  # already configured
        intf = dev.get_active_configuration()[(0, 0)]
        ep = usb_util.find_descriptor(
            intf, custom_match=lambda e: usb_util.endpoint_direction(e.bEndpointAddress) == usb_util.ENDPOINT_OUT)
        if ep is None:
            raise DeliveryError("USB device %04x:%04x has no OUT endpoint" % (vid, pid))
        tmo = int(float(cfg.get("socket_timeout", 8)) * 1000)
        for i in range(0, len(data), 4096):
            ep.write(data[i:i + 4096], timeout=tmo)
    except usb_core.USBError as e:
        msg = str(e)
        if "Access denied" in msg or "Errno 13" in msg:
            msg += " (run the agent as administrator/root or add a udev rule)"
        raise DeliveryError("USB %04x:%04x: %s" % (vid, pid, msg))
    finally:
        try:
            usb_util.dispose_resources(dev)
        except Exception:
            pass


def send_bluetooth(address, data, cfg=DEFAULTS):
    # Windows (and some Linux setups) expose paired BT printers as a serial COM port.
    if looks_like_serial_port(address):
        return send_serial(address, data, cfg)
    mac, channel = parse_bt_address(address)
    if not _MAC_RE.match(mac):
        raise DeliveryError("Bluetooth address must be a MAC like 00:11:22:33:44:55 or a COM port (got %r)" % address)
    if not hasattr(socket, "AF_BLUETOOTH"):
        raise DeliveryError("Direct Bluetooth sockets are not supported on this OS. Pair the printer and use the "
                            "COM port Windows assigned to it (e.g. COM5) as the address.")
    timeout = float(cfg.get("socket_timeout", 8))
    try:
        s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        try:
            s.settimeout(timeout)
            s.connect((mac, channel))
            s.sendall(data)
            time.sleep(0.2)  # let the BT stack flush before closing
        finally:
            s.close()
    except OSError as e:
        raise DeliveryError("Bluetooth printer %s (channel %s): %s" % (mac, channel, e))


def send_windows(address, data, cfg=DEFAULTS):
    name = address[4:].strip()
    win32print = _lazy("win32print", "pywin32", "Windows-installed printers ('win:' addresses)")
    try:
        h = win32print.OpenPrinter(name)
        try:
            win32print.StartDocPrinter(h, 1, ("Servora", None, "RAW"))
            try:
                win32print.StartPagePrinter(h)
                win32print.WritePrinter(h, data)
                win32print.EndPagePrinter(h)
            finally:
                win32print.EndDocPrinter(h)
        finally:
            win32print.ClosePrinter(h)
    except Exception as e:
        raise DeliveryError("Windows printer %r: %s" % (name, e))


def send_cups(address, data, cfg=DEFAULTS):
    name = address[5:].strip()
    lp = shutil.which("lp")
    if not lp:
        raise DeliveryError("'lp' command not found -- install CUPS to use 'cups:' addresses")
    try:
        p = subprocess.run([lp, "-o", "raw", "-d", name], input=data, capture_output=True,
                           timeout=float(cfg.get("socket_timeout", 8)) * 3)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise DeliveryError("CUPS printer %r: %s" % (name, e))
    if p.returncode != 0:
        raise DeliveryError("CUPS printer %r: %s" % (name, (p.stderr or b"").decode(errors="replace").strip()))


DRIVERS = {
    "network": send_network,
    "usb": send_usb,
    "serial": send_serial,
    "bluetooth": send_bluetooth,
}


def pick_driver(connection, address):
    a = (address or "").strip()
    low = a.lower()
    if low.startswith("win:"):
        return send_windows
    if low.startswith("cups:"):
        return send_cups
    if low.startswith("usb:"):
        return send_usb
    if low.startswith("tcp://"):
        return send_network
    if connection in DRIVERS:
        return DRIVERS[connection]
    raise DeliveryError("connection type %r is not handled by the agent" % connection)


def deliver(connection, address, data, cfg=DEFAULTS):
    if not address:
        raise DeliveryError("device has no address configured (Settings -> Hardware)")
    pick_driver(connection, address)(address, data, cfg)


# --------------------------------------------------------------------------- #
# Payload helpers
# --------------------------------------------------------------------------- #
def format_display(text, cols=20, rows=2):
    """Render text for a 2x20 VFD / LCD pole display (clear + home, fixed width lines)."""
    lines = [ln for ln in (text or "").replace("\r", "").split("\n")]
    lines = (lines + [""] * rows)[:rows]
    body = "".join(ln[:cols].ljust(cols) for ln in lines)
    # 0x0C = clear display (ESC/POS customer display & most VFDs), 0x0B = cursor home
    return b"\x0c\x0b" + body.replace("₹", "Rs").encode("ascii", "replace")


def text_to_escpos(text):
    body = (text or "").replace("₹", "Rs.").encode("cp437", "replace")
    return INIT + body + b"\n\n\n\n" + CUT


def job_payload(job, device):
    """Return the raw bytes to send to the device for this job."""
    kind = (device or {}).get("kind")
    if job.get("kind") == "display" or kind == "customer_display":
        cfg = (device or {}).get("config") or {}
        return format_display(job.get("text", ""), int(cfg.get("cols", 20)), int(cfg.get("rows", 2)))
    b64 = job.get("escpos_b64") or ""
    if b64:
        try:
            return base64.b64decode(b64)
        except (ValueError, TypeError) as e:
            raise DeliveryError("invalid escpos_b64 payload: %s" % e)
    if job.get("text"):
        return text_to_escpos(job["text"])
    raise DeliveryError("job has no printable content")


def test_page(address="", width_mm=80):
    w = 32 if int(width_mm) <= 58 else 48
    lines = [
        ESC + b"a\x01" + ESC + b"E\x01" + GS + b"!\x11" + b"SERVORA\n" + GS + b"!\x00" + ESC + b"E\x00",
        b"Hardware Agent test page\n",
        ("-" * w + "\n").encode(),
        ESC + b"a\x00",
        ("Agent   : v%s\n" % __version__).encode(),
        ("Host    : %s\n" % socket.gethostname())[: w + 1].encode("ascii", "replace"),
        ("Address : %s\n" % address)[: w + 1].encode("ascii", "replace"),
        ("Time    : %s\n" % time.strftime("%Y-%m-%d %H:%M:%S")).encode(),
        ("-" * w + "\n").encode(),
        ESC + b"a\x01" + b"If you can read this,\nyour printer is connected!\n",
    ]
    return INIT + b"".join(lines) + b"\n\n\n\n" + CUT


# --------------------------------------------------------------------------- #
# Weighing scale
# --------------------------------------------------------------------------- #
_WEIGHT_RE = re.compile(r"([-+])?\s*(\d+(?:[.,]\d+)?)\s*(kg|g|lb|oz)?", re.I)


def parse_weight(line):
    """Parse a scale output line into a kg string with 3 decimals, or None.

    Handles common formats:
      'ST,GS,+  1.250kg'  'ST,NT,+0001.250 kg'  '  1.250'  'W: 1250 g'  '+001.250'
    Lines flagged unstable ('US,...') are ignored.
    """
    if line is None:
        return None
    if isinstance(line, bytes):
        line = line.decode("ascii", "ignore")
    s = line.strip().strip("\x02\x03")
    if not s or s.upper().startswith("US"):
        return None
    best = None
    for m in _WEIGHT_RE.finditer(s):
        sign, num, unit = m.group(1), m.group(2), (m.group(3) or "").lower()
        best = (sign, num, unit)
        if unit:  # a number with an explicit unit wins
            break
    if not best:
        return None
    sign, num, unit = best
    try:
        val = float(num.replace(",", "."))
    except ValueError:
        return None
    if unit == "g":
        val /= 1000.0
    elif unit == "lb":
        val *= 0.45359237
    elif unit == "oz":
        val *= 0.028349523125
    if sign == "-":
        val = -val
    return "%.3f" % val


class ScaleReader(threading.Thread):
    """Continuously reads a serial weighing scale and reports weight changes."""

    def __init__(self, device, on_weight, cfg=DEFAULTS):
        super().__init__(name="scale-%s" % device.get("id"), daemon=True)
        self.device = device
        self.on_weight = on_weight
        self.cfg = cfg
        self.stop_event = threading.Event()
        self.last = None

    def stop(self):
        self.stop_event.set()

    def handle_line(self, line):
        w = parse_weight(line)
        if w is not None and w != self.last:
            self.last = w
            try:
                self.on_weight(w)
            except Exception as e:  # never kill the reader on a reporting failure
                log.warning("Could not report scale weight: %s", e)
                self.last = None  # retry on next reading
        return w

    def run(self):
        try:
            serial = _lazy("serial", "pyserial", "Weighing scales")
        except MissingExtra as e:
            log.error("%s", e)
            return
        port, baud = parse_serial_address(self.device.get("address", ""), int(self.cfg.get("default_baud", 9600)))
        dev_cfg = self.device.get("config") or {}
        poll_cmd = dev_cfg.get("poll_command")  # some scales only answer when asked, e.g. "W\r\n"
        delay = 2.0
        while not self.stop_event.is_set():
            try:
                with serial.Serial(port, baudrate=baud, timeout=1) as ser:
                    log.info("Scale '%s' connected on %s @%s", self.device.get("name"), port, baud)
                    delay = 2.0
                    while not self.stop_event.is_set():
                        if poll_cmd:
                            ser.write(poll_cmd.encode().decode("unicode_escape").encode("latin-1"))
                        raw = ser.readline()
                        if raw:
                            self.handle_line(raw)
                        elif poll_cmd:
                            self.stop_event.wait(0.3)
            except Exception as e:
                log.warning("Scale on %s: %s (retrying in %.0fs)", port, e, delay)
                self.stop_event.wait(delay)
                delay = min(delay * 2, 60)


# --------------------------------------------------------------------------- #
# Agent
# --------------------------------------------------------------------------- #
class Agent:
    def __init__(self, cfg, client=None):
        self.cfg = cfg
        self.client = client or ServoraClient(cfg["server_url"], cfg["device_key"], float(cfg.get("http_timeout", 20)))
        self.devices = {}          # id -> device dict
        self.scales = {}           # id -> ScaleReader
        self.restaurant = None
        self.last_health = 0.0
        self.online = []
        self.pending_results = []  # results not yet acknowledged by the server
        self.stop_event = threading.Event()
        self._lock = threading.Lock()

    # ---- devices -------------------------------------------------------- #
    def update_devices(self, devices):
        new = {}
        for d in devices or []:
            if d.get("connection") in AGENT_CONNECTIONS or str(d.get("address", "")).lower().startswith(("win:", "cups:")):
                new[d["id"]] = d
        added = set(new) - set(self.devices)
        if added or set(self.devices) - set(new):
            log.info("Managing %d device(s): %s", len(new),
                     ", ".join("%s [%s/%s %s]" % (d.get("name"), d.get("kind"), d.get("connection"), d.get("address"))
                               for d in new.values()) or "none")
        self.devices = new
        self._sync_scales()

    def _sync_scales(self):
        wanted = {i: d for i, d in self.devices.items()
                  if d.get("kind") == "weighing_scale" and d.get("connection") in ("serial", "usb", "bluetooth")
                  and d.get("address")}
        for i in list(self.scales):
            r = self.scales[i]
            if i not in wanted or wanted[i].get("address") != r.device.get("address") or not r.is_alive():
                r.stop()
                del self.scales[i]
        for i, d in wanted.items():
            if i not in self.scales:
                if d.get("connection") == "usb" and not looks_like_serial_port(d["address"]):
                    log.warning("Scale '%s': USB scales appear as a serial port (USB-serial); set its address to "
                                "the COM port / /dev/ttyUSBx", d.get("name"))
                    continue
                r = ScaleReader(d, self.report_weight, self.cfg)
                self.scales[i] = r
                r.start()

    def report_weight(self, weight):
        log.info("Scale weight %s kg", weight)
        with self._lock:
            self.client.report({"scale_weight": weight})

    # ---- health --------------------------------------------------------- #
    def check_health(self):
        online = []
        timeout = min(3.0, float(self.cfg.get("socket_timeout", 8)))
        for d in list(self.devices.values()):
            addr = (d.get("address") or "").strip()
            if not addr:
                continue
            try:
                drv = pick_driver(d.get("connection"), addr)
            except DeliveryError:
                continue
            if drv is send_network:
                host, port = parse_network_address(addr)
                try:
                    with socket.create_connection((host, port), timeout=timeout):
                        online.append(d["id"])
                except OSError:
                    log.warning("Printer '%s' (%s) is not reachable", d.get("name"), addr)
            elif drv is send_serial or (drv is send_bluetooth and looks_like_serial_port(addr)):
                port = parse_serial_address(addr)[0]
                if port.upper().startswith("COM") or os.path.exists(port):
                    online.append(d["id"])
            elif d.get("kind") == "weighing_scale" and d["id"] in self.scales and self.scales[d["id"]].is_alive():
                online.append(d["id"])
        self.online = online
        self.last_health = time.time()
        return online

    # ---- jobs ----------------------------------------------------------- #
    def process_job(self, job):
        device = self.devices.get(job.get("device"))
        if device is None:
            return {"id": job.get("id"), "ok": False, "error": "device %s not managed by this agent" % job.get("device")}
        try:
            data = job_payload(job, device)
        except DeliveryError as e:
            return {"id": job.get("id"), "ok": False, "error": str(e)[:200]}
        attempts = max(1, int(self.cfg.get("retries", 3)))
        delay = float(self.cfg.get("retry_backoff", 1.0))
        err = None
        for n in range(1, attempts + 1):
            try:
                deliver(device.get("connection"), device.get("address"), data, self.cfg)
                log.info("Job %s (%s) -> '%s' OK (%d bytes)", job.get("id"), job.get("kind"), device.get("name"), len(data))
                return {"id": job.get("id"), "ok": True, "error": ""}
            except MissingExtra as e:  # retrying will not help
                err = str(e)
                break
            except Exception as e:
                err = str(e) or e.__class__.__name__
                log.warning("Job %s attempt %d/%d failed: %s", job.get("id"), n, attempts, err)
                if n < attempts:
                    self.stop_event.wait(delay)
                    delay *= 2
        log.error("Job %s (%s) -> '%s' FAILED: %s", job.get("id"), job.get("kind"), device.get("name"), err)
        return {"id": job.get("id"), "ok": False, "error": (err or "unknown error")[:200]}

    def poll_once(self):
        """One cycle: fetch devices & jobs, deliver, report. Raises on network errors."""
        # Flush results from a previous cycle whose report failed (jobs are already 'sent').
        if self.pending_results:
            with self._lock:
                self.client.report({"results": self.pending_results})
            self.pending_results = []

        data = self.client.poll()
        if data.get("restaurant") and data["restaurant"] != self.restaurant:
            self.restaurant = data["restaurant"]
            log.info("Connected to Servora as '%s'", self.restaurant)
        self.update_devices(data.get("devices", []))

        results = [self.process_job(j) for j in data.get("jobs", [])]
        payload = {}
        if results:
            payload["results"] = results
        if time.time() - self.last_health >= float(self.cfg.get("health_interval", 60)):
            online = self.check_health()
            if online:
                payload["online_devices"] = online
        if payload:
            try:
                with self._lock:
                    self.client.report(payload)
            except Exception:
                self.pending_results.extend(results)
                raise
        return results

    def run(self):
        log.info("Servora Hardware Agent v%s starting (server %s)", __version__, self.cfg["server_url"])
        if not self.cfg.get("device_key"):
            log.error("No device key configured. Run:  python servora_agent.py setup")
            return 2
        interval = float(self.cfg.get("poll_interval", 2))
        backoff = interval
        failures = 0
        while not self.stop_event.is_set():
            try:
                self.poll_once()
                if failures:
                    log.info("Connection to Servora restored")
                failures, backoff = 0, interval
                self.stop_event.wait(interval)
            except AuthError as e:
                log.error("%s", e)
                self.stop_event.wait(60)
            except KeyboardInterrupt:
                break
            except Exception as e:  # network outage, server 5xx, bad JSON ... never crash
                failures += 1
                backoff = min(max(backoff * 2, interval), float(self.cfg.get("max_backoff", 60)))
                lvl = logging.WARNING if failures < 5 else logging.ERROR
                log.log(lvl, "Poll failed (%s: %s); retrying in %.0fs", e.__class__.__name__, e, backoff)
                self.stop_event.wait(backoff)
        self.shutdown()
        return 0

    def shutdown(self):
        self.stop_event.set()
        for r in self.scales.values():
            r.stop()


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packets are sent
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def scan_subnet(base_ip=None, port=9100, timeout=0.4, workers=128):
    ip = base_ip or local_ip()
    net = ipaddress.ip_network(ip + "/24", strict=False)

    def probe(host):
        try:
            with socket.create_connection((str(host), port), timeout=timeout):
                return str(host)
        except OSError:
            return None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        found = [h for h in ex.map(probe, net.hosts()) if h]
    return sorted(found, key=lambda h: tuple(int(x) for x in h.split(".")))


def list_usb_printers():
    try:
        import usb.core  # noqa
    except ImportError:
        return None
    out = []
    try:
        for dev in usb.core.find(find_all=True):
            is_printer = dev.bDeviceClass == 7
            if not is_printer:
                try:
                    for cfg in dev:
                        for intf in cfg:
                            if intf.bInterfaceClass == 7:
                                is_printer = True
                except Exception:
                    pass
            if is_printer:
                name = ""
                try:
                    name = "%s %s" % (dev.manufacturer or "", dev.product or "")
                except Exception:
                    pass
                out.append(("%04x:%04x" % (dev.idVendor, dev.idProduct), name.strip()))
    except Exception as e:  # no backend (libusb missing)
        out.append(("error", str(e)))
    return out


def list_serial_ports():
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    return [(p.device, p.description or "") for p in list_ports.comports()]


def list_os_printers():
    out = []
    try:
        import win32print  # noqa
        for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS):
            out.append("win:" + p[2])
    except Exception:
        pass
    if shutil.which("lpstat"):
        try:
            p = subprocess.run(["lpstat", "-a"], capture_output=True, text=True, timeout=5)
            out += ["cups:" + ln.split()[0] for ln in p.stdout.splitlines() if ln.strip()]
        except Exception:
            pass
    return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def cmd_setup(args):
    cfg = load_config(args.config)
    print("\n=== Servora Hardware Agent setup ===\n")
    print("1. Open the Servora dashboard -> Settings -> Hardware.")
    print("2. Add (or open) the device of type 'POS terminal / hub' and copy its Device Key.\n")
    url = input("Servora address [%s]: " % cfg["server_url"]).strip() or cfg["server_url"]
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    key = ""
    while not key:
        key = input("Device key%s: " % (" [keep current]" if cfg.get("device_key") else "")).strip() or cfg.get("device_key", "")
        if not key:
            print("  The device key is required (it starts with 'dev_').")
    iv = input("Check for new print jobs every N seconds [%s]: " % cfg["poll_interval"]).strip()
    cfg.update(server_url=url.rstrip("/"), device_key=key, poll_interval=float(iv) if iv else float(cfg["poll_interval"]))
    print("\nTesting connection ...")
    try:
        # An empty POST validates the key without taking (and marking 'sent') any queued jobs.
        ServoraClient(cfg["server_url"], key, 15).report({"results": []})
        print("  OK - the server accepted this device key.")
    except AuthError as e:
        print("  ! %s" % e)
    except Exception as e:
        print("  ! Could not reach the server: %s (settings saved anyway)" % e)
    save_config(cfg, args.config)
    print("\nSaved to %s" % args.config)
    print("Start the agent with:  python %s run\n" % os.path.basename(__file__))
    return 0


def cmd_test(args):
    cfg = load_config(args.config)
    setup_logging(dict(cfg, log_file=None))
    addr = args.address
    conn = args.connection
    if not conn:
        low = addr.lower()
        if low.startswith(("win:", "cups:", "usb:", "tcp://")):
            conn = "network"  # prefix decides the driver
        elif looks_like_serial_port(addr):
            conn = "serial"
        elif _MAC_RE.match(addr.split("@")[0]):
            conn = "bluetooth"
        elif re.match(r"^[0-9a-f]{4}:[0-9a-f]{4}$", low):
            conn = "usb"
        else:
            conn = "network"
    data = format_display(args.text or "SERVORA\nDisplay test OK") if args.display else test_page(addr, args.width)
    if args.drawer:
        data = data + b"\x1bp\x00\x19\xfa"
    print("Sending %d bytes to %s (%s) ..." % (len(data), addr, conn))
    try:
        deliver(conn, addr, data, cfg)
    except DeliveryError as e:
        print("FAILED: %s" % e)
        return 1
    print("OK - check the printer.")
    return 0


def cmd_discover(args):
    ip = local_ip()
    print("This computer: %s" % ip)
    print("Scanning %s/24 for network printers on port %d ..." % (ip.rsplit(".", 1)[0] + ".0", args.port))
    t = time.time()
    found = scan_subnet(ip, args.port, timeout=args.timeout)
    print("  done in %.1fs" % (time.time() - t))
    for h in found:
        print("  [network] %s:%d" % (h, args.port))
    if not found:
        print("  (none found - is the printer on the same Wi-Fi/LAN and switched on?)")

    usb = list_usb_printers()
    if usb is None:
        print("\nUSB printers: install 'pyusb' to list them  (python -m pip install pyusb)")
    else:
        print("\nUSB printers:")
        for addr, name in usb:
            print("  [usb] %s  %s" % (addr, name))
        if not usb:
            print("  (none found)")

    ports = list_serial_ports()
    if ports is None:
        print("\nSerial / COM ports: install 'pyserial' to list them  (python -m pip install pyserial)")
    else:
        print("\nSerial / COM ports (serial printers, Bluetooth COM, pole displays, weighing scales):")
        for dev, desc in ports:
            print("  [serial] %s  %s" % (dev, desc))
        if not ports:
            print("  (none found)")

    osp = list_os_printers()
    if osp:
        print("\nPrinters installed in the operating system (use as address for RAW printing):")
        for p in osp:
            print("  %s" % p)
    print("\nCopy the address into Servora -> Settings -> Hardware -> device -> Address.")
    return 0


def cmd_run(args):
    cfg = load_config(args.config)
    if args.interval:
        cfg["poll_interval"] = args.interval
    setup_logging(cfg)
    agent = Agent(cfg)
    try:
        return agent.run()
    except KeyboardInterrupt:
        agent.shutdown()
        log.info("Stopped")
        return 0


def build_parser():
    p = argparse.ArgumentParser(prog="servora_agent", description="Servora Hardware Agent v" + __version__)
    p.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="path to config.json")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("setup", help="interactive first-time setup")
    r = sub.add_parser("run", help="run the agent (default)")
    r.add_argument("--interval", type=float, help="poll interval in seconds")
    t = sub.add_parser("test", help="send a test page to a printer")
    t.add_argument("--address", required=True,
                   help="192.168.1.50[:9100] | 04b8:0202 | COM3[@9600] | /dev/ttyUSB0 | AA:BB:..:FF | win:Name | cups:Name")
    t.add_argument("--connection", choices=["network", "usb", "serial", "bluetooth"], help="force connection type")
    t.add_argument("--width", type=int, default=80, help="paper width in mm (58 or 80)")
    t.add_argument("--drawer", action="store_true", help="also kick the cash drawer")
    t.add_argument("--display", action="store_true", help="treat as a 2x20 customer pole display")
    t.add_argument("--text", help="text for --display")
    d = sub.add_parser("discover", help="find printers on the LAN, USB and serial ports")
    d.add_argument("--port", type=int, default=9100)
    d.add_argument("--timeout", type=float, default=0.4)
    sub.add_parser("version", help="print version")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    cmd = args.cmd or "run"
    if cmd == "version":
        print(__version__)
        return 0
    if cmd == "run" and not hasattr(args, "interval"):
        args.interval = None
    return {"setup": cmd_setup, "run": cmd_run, "test": cmd_test, "discover": cmd_discover}[cmd](args)


if __name__ == "__main__":
    sys.exit(main() or 0)
