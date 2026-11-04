"""Stdlib-only tests for the Servora Hardware Agent.

Run from the repo root:   python -m unittest discover -s hardware-agent/tests
"""
import base64
import json
import os
import socket
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import servora_agent as sa  # noqa: E402


class FakePrinter:
    """A raw TCP 'port 9100' printer that records every byte it receives."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.received = bytearray()
        self.jobs = 0
        self.got_job = threading.Event()
        self._stop = False
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                conn.settimeout(5)
                chunk_total = b""
                while True:
                    try:
                        chunk = conn.recv(4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    chunk_total += chunk
                if chunk_total:  # health checks connect without sending
                    self.received += chunk_total
                    self.jobs += 1
                    self.got_job.set()

    def close(self):
        self._stop = True
        self.sock.close()


class FakeServora:
    """http.server stand-in for GET/POST /api/hardware/agent."""

    KEY = "dev_testkey"

    def __init__(self, devices, jobs):
        self.devices = devices
        self.jobs = jobs
        self.posts = []
        self.gets = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, body):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _authed(self):
                if self.path.rstrip("/") != sa.AGENT_PATH:
                    self._json(404, {"detail": "not found"})
                    return False
                if self.headers.get("X-Device-Key") != outer.KEY:
                    self._json(401, {"detail": "Invalid device key"})
                    return False
                return True

            def do_GET(self):
                if not self._authed():
                    return
                outer.gets += 1
                jobs, outer.jobs = outer.jobs, []  # marked 'sent' on read
                self._json(200, {"restaurant": "Test Cafe", "devices": outer.devices, "jobs": jobs})

            def do_POST(self):
                if not self._authed():
                    return
                n = int(self.headers.get("Content-Length") or 0)
                outer.posts.append(json.loads(self.rfile.read(n) or b"{}"))
                self._json(200, {"ok": True})

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def make_cfg(url, key=FakeServora.KEY):
    return dict(sa.DEFAULTS, server_url=url, device_key=key, retry_backoff=0.01, socket_timeout=2,
                http_timeout=5, log_file=None)


class PollCycleTest(unittest.TestCase):
    def setUp(self):
        sa.setup_logging(dict(sa.DEFAULTS, log_file=None), console=False)
        self.printer = FakePrinter()
        self.escpos = b"\x1b@HELLO SERVORA\n\x1dVA\x03\x1bp\x00\x19\xfa"
        self.dead_port = free_port()
        devices = [
            {"id": 1, "name": "Counter", "kind": "receipt_printer", "connection": "network",
             "address": "127.0.0.1:%d" % self.printer.port, "paper_width": 80, "config": {}},
            {"id": 2, "name": "Kitchen", "kind": "kot_printer", "connection": "network",
             "address": "127.0.0.1:%d" % self.dead_port, "paper_width": 80, "config": {}},
        ]
        jobs = [
            {"id": 101, "device": 1, "kind": "bill", "escpos_b64": base64.b64encode(self.escpos).decode(),
             "text": "HELLO SERVORA"},
            {"id": 102, "device": 2, "kind": "kot", "escpos_b64": base64.b64encode(b"KOT").decode(), "text": "KOT"},
            {"id": 103, "device": 99, "kind": "bill", "escpos_b64": "", "text": "orphan"},
        ]
        self.server = FakeServora(devices, jobs)

    def tearDown(self):
        self.server.close()
        self.printer.close()

    def test_one_poll_cycle_delivers_and_reports(self):
        agent = sa.Agent(make_cfg(self.server.url))
        results = agent.poll_once()

        # bytes arrived at the fake printer, unchanged
        self.assertTrue(self.printer.got_job.wait(5), "printer received nothing")
        self.assertEqual(bytes(self.printer.received), self.escpos)
        self.assertEqual(self.printer.jobs, 1)

        # result was reported back to the server
        self.assertEqual(self.server.gets, 1)
        self.assertEqual(len(self.server.posts), 1)
        post = self.server.posts[0]
        by_id = {r["id"]: r for r in post["results"]}
        self.assertTrue(by_id[101]["ok"])
        self.assertEqual(by_id[101]["error"], "")
        self.assertFalse(by_id[102]["ok"])          # dead printer -> failed after retries
        self.assertIn("unreachable", by_id[102]["error"])
        self.assertFalse(by_id[103]["ok"])          # unknown device
        self.assertEqual(post["online_devices"], [1])  # health check: only printer 1 is up
        self.assertEqual(len(results), 3)
        self.assertEqual(agent.restaurant, "Test Cafe")

        # second cycle: no jobs, health not due -> nothing to POST
        agent.poll_once()
        self.assertEqual(self.server.gets, 2)
        self.assertEqual(len(self.server.posts), 1)

    def test_bad_key_raises_auth_error(self):
        agent = sa.Agent(make_cfg(self.server.url, key="dev_wrong"))
        with self.assertRaises(sa.AuthError):
            agent.poll_once()

    def test_outage_does_not_crash_run_loop(self):
        cfg = make_cfg("http://127.0.0.1:%d" % free_port())  # nothing listening
        cfg.update(poll_interval=0.01, max_backoff=0.05)
        agent = sa.Agent(cfg)
        t = threading.Thread(target=agent.run, daemon=True)
        t.start()
        t.join(0.5)
        self.assertTrue(t.is_alive(), "agent loop died during an outage")
        agent.stop_event.set()
        t.join(2)
        self.assertFalse(t.is_alive())


class HelperTest(unittest.TestCase):
    def test_parse_weight(self):
        cases = {
            "ST,GS,+  1.250kg": "1.250",
            "ST,NT,+0001.250 kg\r\n": "1.250",
            "  0.785": "0.785",
            "W: 1250 g": "1.250",
            "ST,GS,-  0.020kg": "-0.020",
            b"\x02+002.500kg\x03": "2.500",
            "US,GS,+  1.300kg": None,   # unstable reading ignored
            "": None,
            "ERR": None,
        }
        for line, want in cases.items():
            self.assertEqual(sa.parse_weight(line), want, line)

    def test_scale_reader_reports_changes_only(self):
        seen = []
        r = sa.ScaleReader({"id": 5, "name": "Scale", "address": "COM9"}, seen.append)
        for ln in ["ST,GS,+  1.250kg", "ST,GS,+  1.250kg", "US,GS,+  1.900kg", "ST,GS,+  2.000kg"]:
            r.handle_line(ln)
        self.assertEqual(seen, ["1.250", "2.000"])

    def test_addresses(self):
        self.assertEqual(sa.parse_network_address("192.168.1.50"), ("192.168.1.50", 9100))
        self.assertEqual(sa.parse_network_address("192.168.1.50:9101"), ("192.168.1.50", 9101))
        self.assertEqual(sa.parse_serial_address("COM3"), ("COM3", 9600))
        self.assertEqual(sa.parse_serial_address("/dev/ttyUSB0@19200"), ("/dev/ttyUSB0", 19200))
        self.assertEqual(sa.parse_usb_address("04b8:0202"), (0x04B8, 0x0202))
        self.assertEqual(sa.parse_bt_address("00:11:22:aa:bb:cc@2"), ("00:11:22:AA:BB:CC", 2))
        self.assertIs(sa.pick_driver("network", "win:EPSON TM-T82"), sa.send_windows)
        self.assertIs(sa.pick_driver("usb", "cups:receipt"), sa.send_cups)
        self.assertIs(sa.pick_driver("bluetooth", "COM5"), sa.send_bluetooth)
        self.assertTrue(sa.looks_like_serial_port("COM5@9600"))
        with self.assertRaises(sa.DeliveryError):
            sa.pick_driver("browser", "x")

    def test_display_payload(self):
        data = sa.job_payload({"kind": "display", "text": "Total\nRs 250.00"}, {"kind": "customer_display"})
        self.assertEqual(data, b"\x0c\x0b" + b"Total".ljust(20) + b"Rs 250.00".ljust(20))

    def test_text_fallback(self):
        data = sa.job_payload({"kind": "bill", "escpos_b64": "", "text": "hi"}, {"kind": "receipt_printer"})
        self.assertTrue(data.startswith(sa.INIT) and data.endswith(sa.CUT) and b"hi" in data)

    def test_cli_test_command_sends_test_page(self):
        printer = FakePrinter()
        try:
            rc = sa.main(["--config", os.devnull + ".missing", "test", "--address", "127.0.0.1:%d" % printer.port])
            self.assertEqual(rc, 0)
            self.assertTrue(printer.got_job.wait(5))
            self.assertIn(b"Hardware Agent test page", bytes(printer.received))
        finally:
            printer.close()


if __name__ == "__main__":
    unittest.main()
