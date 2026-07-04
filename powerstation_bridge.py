#!/usr/bin/env python3
"""
powerstation-tools: Bridge Server
Exposes a small JSON HTTP API for controlling the device from a browser,
and serves the dark-mode dashboard (powerstation_dashboard.html) at '/'.

Run:
    python3 powerstation_bridge.py
Then open:
    http://localhost:8090

Listens on localhost:8090 by default. Keep this on localhost - there is
no authentication, and anyone who can reach this port can control the
device.
"""

import json
import os
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from socketserver import ThreadingMixIn

from powerstation_control import PowerstationClient, PowerstationError

HOST = "0.0.0.0"
PORT = 8090
DASHBOARD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "powerstation_dashboard.html")

# Single shared client + lock, since the device only handles one TCP
# connection's worth of conversation at a time.
_client_lock = threading.Lock()
_client: PowerstationClient = None


def get_client(host: str = None, port: int = None) -> PowerstationClient:
    """Return a connected client, (re)connecting if needed."""
    global _client
    if _client is None or not _client.connected:
        if _client is not None:
            # Close the old socket explicitly rather than just dropping
            # the reference - otherwise its TCP connection can linger
            # from the device's side even though we've stopped using it,
            # which may be part of why a full WiFi reset was needed to
            # recover in practice rather than just a bridge restart.
            try:
                _client.disconnect()
            except Exception:
                pass
        _client = PowerstationClient(host=host, port=port)
        _client.connect(timeout=5.0)
    return _client


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        """
        Skip the traceback for a client that closed the connection
        before we finished responding (e.g. tab reloaded mid-request) -
        that's normal. Anything else still gets a full traceback.
        """
        exc_type = sys.exc_info()[0]
        if exc_type in (BrokenPipeError, ConnectionResetError):
            return
        super().handle_error(request, client_address)


class BridgeHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        # Comment this out (call the real implementation) to see request logs.
        pass

    # ---------- response helpers ----------

    def _send_headers(self, status: int, content_type: str, length: int = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()

    def send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        try:
            self._send_headers(status, "application/json", len(body))
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            # Client gave up waiting and closed the connection before we
            # finished responding - nothing to do, nowhere to send this.
            pass

    def send_html(self, html: str, status: int = 200):
        body = html.encode("utf-8")
        try:
            self._send_headers(status, "text/html; charset=utf-8", len(body))
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    # ---------- command execution wrapper ----------

    def run_command(self, fn):
        """Run a client command, ensuring a connection, and reply with
        a uniform JSON result/error shape."""
        try:
            client = get_client()
        except PowerstationError as e:
            self.send_json({"ok": False, "error": f"Connection failed: {e}"}, status=502)
            return

        try:
            result = fn(client)
            self.send_json({"ok": True, "result": result})
        except PowerstationError as e:
            self.send_json({"ok": False, "error": str(e)}, status=500)
        except (ValueError, KeyError) as e:
            self.send_json({"ok": False, "error": str(e)}, status=400)
        except Exception as e:
            self.send_json({"ok": False, "error": f"Unexpected error: {e}"}, status=500)

    # ---------- routing ----------

    def do_OPTIONS(self):
        self._send_headers(204, "text/plain", 0)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)

        if path == "/":
            self.serve_dashboard()
            return

        if path == "/health":
            self.send_json({"status": "ok"})
            return

        if path == "/api/status":
            with _client_lock:
                # Device pushes '93' status on its own roughly every 3s
                # once connected - wait_for_status_push runs the
                # handshake first if needed, then waits for the next
                # push.
                self.run_command(lambda c: c.wait_for_status_push(timeout=8.0))
            return

        if path == "/api/scan":
            subnet = params.get("subnet", ["192.168.4"])[0].strip()
            try:
                ips = PowerstationClient.scan_subnet_for_device(subnet_prefix=subnet)
                self.send_json({"ok": True, "result": {"ips": ips}})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, status=500)
            return

        self.send_json({"ok": False, "error": "Not found"}, status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        body = self.read_json_body()

        if path == "/api/wifi/provision":
            self.handle_wifi_provision(body)
            return

        routes = {
            "/api/master": lambda c: c.set_master_switch(bool(body.get("on"))),
            "/api/ac": lambda c: c.set_ac_output(bool(body.get("on"))),
            "/api/dc": lambda c: c.set_dc_output(bool(body.get("on"))),
            "/api/beep": lambda c: c.set_buzzer(bool(body.get("on"))),
            "/api/ambient-light": lambda c: c.set_ambient_light(bool(body.get("on"))),
            "/api/sleep-mode": lambda c: c.set_sleep_mode(bool(body.get("on"))),
            "/api/amp-up": lambda c: c.set_amp_up_mode(bool(body.get("on"))),
            "/api/four-g": lambda c: c.set_four_g_switch(bool(body.get("on"))),
            "/api/ac-hz": lambda c: c.set_ac_frequency(int(body.get("hz", 60))),
            "/api/led/brightness": lambda c: c.set_led_brightness(int(body.get("value", 50))),
            "/api/led/color": lambda c: c.set_led_color(int(body.get("id", 1))),
            "/api/led/color-and-brightness": lambda c: c.set_led_color_and_brightness(
                int(body.get("id", 1)), int(body.get("brightness", 50))),
            "/api/charge-limit": lambda c: c.set_charge_limit(int(body.get("percent", 100))),
            "/api/charge-speed": lambda c: c.set_max_charge_watts(int(body.get("watts", 1800))),
            # Machine and screen standby share one byte on this device
            # and can't be read back (see set_standby_levels docstring),
            # so both are required on every call - no silent default for
            # the value the caller isn't trying to change.
            "/api/standby-levels": lambda c: c.set_standby_levels(
                int(body["machine"]), int(body["screen"])),
        }

        fn = routes.get(path)
        if fn is None:
            self.send_json({"ok": False, "error": "Not found"}, status=404)
            return

        with _client_lock:
            self.run_command(fn)

    # ---------- Wi-Fi provisioning ----------

    def handle_wifi_provision(self, body):
        """
        Run the Wi-Fi provisioning handshake on its own connection
        (only works on the device's own hotspot, 192.168.4.1 - a
        different context than normal control). Drops the shared
        connection first: the device's TCP listener can't service two
        connections at once, and running this alongside status polling
        gets both stuck with no response.
        """
        ssid = (body.get("ssid") or "").strip()
        password = body.get("password") or ""
        if not ssid:
            self.send_json({"ok": False, "error": "ssid is required"}, status=400)
            return

        global _client
        with _client_lock:
            if _client is not None and _client.connected:
                _client.disconnect()
                # Give the device's TCP stack a moment to tear down the
                # old session before opening a new one - we've seen the
                # provisioning connection get zero response when it
                # follows a disconnect with no gap.
                time.sleep(1.0)

            client = PowerstationClient(host="192.168.4.1", port=5000)
            try:
                client.connect(timeout=5.0)
                result = client.provision_wifi(ssid, password, timeout=30.0)
                self.send_json({"ok": True, "result": result})
            except PowerstationError as e:
                self.send_json({"ok": False, "error": str(e)}, status=500)
            except Exception as e:
                self.send_json({"ok": False, "error": f"Unexpected error: {e}"}, status=500)
            finally:
                client.disconnect()

    # ---------- dashboard ----------

    def serve_dashboard(self):
        try:
            with open(DASHBOARD_FILE, "r", encoding="utf-8") as f:
                html = f.read()
            self.send_html(html)
        except FileNotFoundError:
            self.send_html(
                "<h1>powerstation_dashboard.html not found</h1>"
                "<p>Put powerstation_dashboard.html in the same folder as "
                "powerstation_bridge.py, next to this script.</p>",
                status=500,
            )


def main():
    server = ThreadingHTTPServer((HOST, PORT), BridgeHandler)
    print(f"Powerstation bridge running at http://localhost:{PORT}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if _client is not None:
            _client.disconnect()
        server.server_close()


if __name__ == "__main__":
    main()
