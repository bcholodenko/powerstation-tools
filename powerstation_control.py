#!/usr/bin/env python3
"""
Local control client for a WiFi-connected power station, over its TCP
socket at 192.168.4.1:5000.

Message framing: AA55 + length(4 hex) + serial(4 hex) + command(2 hex)
+ data + CRC16-IBM(4 hex) + CC33. All fields uppercase hex.

Connection sequence: device sends an unsolicited '61' identification
frame on connect; client acks it, then sends '24'/'01' to enter control
mode. Once acked, the device pushes status ('93') roughly every 3s for
the life of the connection - see wait_for_status_push().

Master/AC/DC/ambient-light switches use command '12' with a single byte
carrying the full 8-bit switch state (bit7=acHz, bit6=lbs, bit5=four_g,
bit4=ambient_light, bit3=buzzer, bit2=dc, bit1=ac, bit0=master) - only
one bit changes per call, the rest are read from current status first.
AmpUp/silent-input use command '20' the same way, on a separate 2-bit
byte. Buzzer, sleep, AC Hz, charge speed/limit, LED, and standby timers
each have their own single-purpose command word.

Usage examples (run from this directory):
    python3 powerstation_control.py --status
    python3 powerstation_control.py --ac-output on
    python3 powerstation_control.py --dc-output off
    python3 powerstation_control.py --master-switch on
    python3 powerstation_control.py --buzzer off
    python3 powerstation_control.py --sleep-mode enable
    python3 powerstation_control.py --amp-up on
    python3 powerstation_control.py --charge-limit 90
    python3 powerstation_control.py --charge-speed 1200
    python3 powerstation_control.py --led-brightness 60
    python3 powerstation_control.py --led-color 7
    python3 powerstation_control.py --ambient-light on
    python3 powerstation_control.py --wifi-ssid "MyNetwork" --wifi-pass 'secret123'

Note on WiFi passwords containing '!': pass --wifi-pass in single quotes
in an interactive shell, not double quotes (bash history expansion can
mangle '!' inside double quotes). Omitting --wifi-pass prompts securely
instead, avoiding shell quoting entirely.
"""

import socket
import sys
import subprocess
import threading
import time
import getpass
import argparse
from typing import Optional


class PowerstationError(Exception):
    """Base exception for power station communication errors."""
    pass


# CRC16-IBM lookup table.
CRC_TABLE = [
    0,49345,49537,320,49921,960,640,49729,50689,1728,1920,51009,1280,50625,50305,1088,
    52225,3264,3456,52545,3840,53185,52865,3648,2560,51905,52097,2880,51457,2496,2176,
    51265,55297,6336,6528,55617,6912,56257,55937,6720,7680,57025,57217,8000,56577,7616,
    7296,56385,5120,54465,54657,5440,55041,6080,5760,54849,53761,4800,4992,54081,4352,
    53697,53377,4160,61441,12480,12672,61761,13056,62401,62081,12864,13824,63169,63361,
    14144,62721,13760,13440,62529,15360,64705,64897,15680,65281,16320,16000,65089,64001,
    15040,15232,64321,14592,63937,63617,14400,10240,59585,59777,10560,60161,11200,10880,
    59969,60929,11968,12160,61249,11520,60865,60545,11328,58369,9408,9600,58689,9984,
    59329,59009,9792,8704,58049,58241,9024,57601,8640,8320,57409,40961,24768,24960,
    41281,25344,41921,41601,25152,26112,42689,42881,26432,42241,26048,25728,42049,
    27648,44225,44417,27968,44801,28608,28288,44609,43521,27328,27520,43841,26880,
    43457,43137,26688,30720,47297,47489,31040,47873,31680,31360,47681,48641,32448,
    32640,48961,32000,48577,48257,31808,46081,29888,30080,46401,30464,47041,46721,
    30272,29184,45761,45953,29504,45313,29120,28800,45121,20480,37057,37249,20800,
    37633,21440,21120,37441,38401,22208,22400,38721,21760,38337,38017,21568,39937,
    23744,23936,40257,24320,40897,40577,24128,23040,39617,39809,23360,39169,22976,
    22656,38977,34817,18624,18816,35137,19200,35777,35457,19008,19968,36545,36737,
    20288,36097,19904,19584,35905,17408,33985,34177,17728,34561,18368,18048,34369,
    33281,17088,17280,33601,16640,33217,32897,16448
]


def crc16_ibm(hex_str: str) -> str:
    """CRC16-IBM over a hex string (e.g. 'AA550010...'). Returns a
    4-char uppercase hex CRC."""
    if len(hex_str) % 2 != 0:
        raise ValueError("CRC input must be even-length hex string")

    crc = 0
    for i in range(0, len(hex_str), 2):
        b = int(hex_str[i:i + 2], 16)
        crc = (crc >> 8 & 0xFF) ^ CRC_TABLE[(crc ^ b) & 0xFF]

    return format(crc, '04X').upper()


def auto_increment_serial(serial: str) -> str:
    """Auto-increment a 4-hex-char serial field, wrapping 0xFFFF to 0x0001."""
    if len(serial) != 4:
        raise ValueError("Serial must be 4 hex chars")

    def to_int(ch):
        m = {
            'A': 10, 'B': 11, 'C': 12, 'D': 13, 'E': 14, 'F': 15,
            'a': 10, 'b': 11, 'c': 12, 'd': 13, 'e': 14, 'f': 15
        }
        if ch.isdigit():
            return int(ch)
        return m.get(ch.upper(), 0)

    n = (to_int(serial[0]) * 4096 +
         to_int(serial[1]) * 256 +
         to_int(serial[2]) * 16 +
         to_int(serial[3]))

    if n == 0xFFFF:
        return "0000"
    n = (n + 1) & 0xFFFF
    return pad4(format(n, 'X').upper())


def pad4(x: str) -> str:
    """Left-pad a hex string to 4 digits."""
    return x.rjust(4, '0')


def ascii_to_hex(s: str) -> str:
    """Convert an ASCII string to uppercase hex."""
    return ''.join(format(ord(ch), 'X') for ch in s)


def send_data_conversion(
    serial: str,
    command_word: str,
    data: str,
    encoding: str = "base2"
) -> str:
    """
    Build a protocol frame: AA55 + length + serial + command + data +
    CRC16 + CC33.

    Args:
        serial: 4-char hex serial number
        command_word: 2-char hex command code
        data: payload (hex string for base2, ASCII string for ascii)
        encoding: 'base2' or 'ascii'

    Returns:
        Complete message string ready to send over TCP.
    """
    if encoding == "base2":
        data_hex = data
        length_value = 11 + len(data) // 2
    else:
        data_hex = ascii_to_hex(data)
        length_value = 11 + len(data_hex)

    # Length field = total frame byte count, including AA55/CC33 markers.
    length_field = pad4(format(length_value, 'X'))

    msg_without_crc = "AA55" + length_field + serial + command_word + data_hex
    crc = crc16_ibm(msg_without_crc)

    return msg_without_crc + crc + "CC33"


def parse_response_frame(response: str):
    """
    Strip the AA55...CC33 envelope off a raw response.
    Returns (command_word, data_hex) or None if the response doesn't look
    like a valid framed message.
    """
    if not response:
        return None
    response = response.strip()
    if len(response) < 22 or not response.startswith("AA55") or not response.endswith("CC33"):
        return None
    command_word = response[12:14]
    data = response[14:-8]
    return command_word, data


def parse_ack(data: str) -> str:
    """Decode a short ACK payload returned for a control command."""
    return {"55": "success", "CC": "fail", "33": "error"}.get(data.upper(), "unknown")


def _frame_crc_ok(frame_text: str) -> bool:
    """Validate a frame's CRC before trusting its contents."""
    if len(frame_text) < 22 or not frame_text.startswith("AA55") or not frame_text.endswith("CC33"):
        return False
    body = frame_text[:-8]
    embedded_crc = frame_text[-8:-4]
    try:
        return crc16_ibm(body) == embedded_crc.upper()
    except ValueError:
        return False


def _bits(byte_hex: str) -> str:
    """2 hex chars -> 8-char binary string, MSB first."""
    return format(int(byte_hex, 16), '08b')


def _hex_to_ascii(hex_str: str) -> str:
    if len(hex_str) % 2 != 0:
        hex_str = hex_str[:-1]
    try:
        return bytes.fromhex(hex_str).decode('ascii', errors='ignore').rstrip('\x00').strip()
    except ValueError:
        return ""


def parse_status_93_payload(data: str) -> dict:
    """
    Parse the short status format (command '93', 23 bytes = 46 hex chars).

    Field offsets (2 hex chars = 1 byte):
      hex[ 0: 2] battery %                          - confirmed
      hex[ 2: 6] remaining output time (minutes)
      hex[ 6:10] remaining input/charge time (minutes)
      hex[10:14] AC input watts                     - confirmed
      hex[14:18] DC input watts
      hex[18:22] AC output watts                    - confirmed
      hex[22:34] DC output watts, sum of 5 port readings - confirmed
      hex[34:36] ambient light color index
      hex[36:38] ambient light brightness
      hex[38:40] switch bitmask: bit7=acHz, bit6=lbs, bit5=four_g,
                 bit4=ambient_light, bit3=buzzer, bit2=dc, bit1=ac,
                 bit0=master
      hex[40:42] bit0=ampUp (confirmed), bit1=sleep mode
      hex[42:46] unknown

    0xFFFF in the remaining-time fields means no active value.
    """
    def h(start, end):
        """Extract hex substring and convert to int, returns None if out of range."""
        if end > len(data):
            return None
        return int(data[start:end], 16)

    def bits8(start):
        """Extract a byte as an 8-bit string."""
        if start + 2 > len(data):
            return None
        return format(h(start, start + 2), '08b')

    sw_bits = bits8(38)
    switches = None
    if sw_bits is not None:
        names = ["ac_hz", "lbs", "four_g", "ambient_light", "buzzer", "dc", "ac", "master"]
        switches = {name: bit == "1" for name, bit in zip(names, sw_bits)}

    amp_byte = h(40, 42)
    amp_up = bool(amp_byte & 0x01) if amp_byte is not None else None
    sleep_mode = bool((amp_byte >> 1) & 0x01) if amp_byte is not None else None

    # DC output is a SUM across 5 separate port measurements
    dc_parts = [h(22, 26), h(26, 28), h(28, 30), h(30, 32), h(32, 34)]
    dc_output_watts = sum(p for p in dc_parts if p is not None) if any(p is not None for p in dc_parts) else None

    byte_list = [data[i:i+2] for i in range(0, len(data), 2)]

    def no_sentinel(v):
        """0xFFFF means no active value for the remaining-time fields."""
        return None if v == 0xFFFF else v

    remaining_output = no_sentinel(h(2, 6))
    remaining_input = no_sentinel(h(6, 10))

    result = {
        # CONFIRMED by direct experiment:
        "battery_percent":    h(0, 2),
        "ac_input_watts":     h(10, 14),
        "ac_output_watts":    h(18, 22),
        "dc_output_watts":    dc_output_watts,
        "amp_up":             amp_up,
        # From source, not yet independently confirmed:
        "dc_input_watts":     h(14, 18),
        "ambient_color":      h(34, 36),
        "ambient_lightness":  h(36, 38),
        "sleep_mode":         sleep_mode,
        "switches":           switches,
        "remaining_output_minutes": remaining_output,
        "remaining_input_minutes":  remaining_input,
        # Compatibility aliases for existing dashboard JS field names:
        "electricity_pct":        h(0, 2),
        "dc_output_12v_watts":    dc_output_watts,
        "switch_status":          switches,
        "device_mode": {
            "amp_up": amp_up,
            "sleep_mode": sleep_mode,
        },
        # Raw for debugging:
        "byte_count": len(byte_list),
        "bytes": byte_list,
    }
    return result


def parse_status_payload(data: str) -> dict:
    """Parse the long-form status report payload (368 hex chars)."""
    def h(start, length):
        return data[start:start + length]

    def num(start, length):
        return int(h(start, length), 16)

    result = {}

    result["electricity_pct"] = num(0, 2)
    result["discharge_time"] = num(2, 4)   # unit not confirmed, app shows as remaining time
    result["charge_time"] = num(6, 4)
    result["ac_input_watts"] = num(10, 4)
    result["dc_input_watts"] = num(14, 4)
    result["ac_output_watts"] = num(18, 4)
    result["dc_output_12v_watts"] = num(22, 4)
    result["dc_output_ports_watts"] = [num(26, 2), num(28, 2), num(30, 2), num(32, 2)]

    led_byte1_bits = _bits(h(34, 2))
    result["led"] = {
        "mode_type": int(led_byte1_bits[0:3], 2),
        "color_id": int(led_byte1_bits[3:8], 2),
        "brightness": num(36, 2),
    }

    if len(data) >= 40:
        w = _bits(h(38, 2))
        result["working_status"] = {
            "wifi": bool(int(w[0])),
            "four_g": bool(int(w[1])),
            "input_full": bool(int(w[2])),
            "solar_charging": bool(int(w[3])),
            "dc_input": bool(int(w[4])),
            "ac_input": bool(int(w[5])),
            "input": bool(int(w[6])),
            "output": bool(int(w[7])),
        }

    if len(data) >= 42:
        sw = _bits(h(40, 2))
        result["switch_status"] = {
            "ac_hz_60": bool(int(sw[0])),
            "lbs": bool(int(sw[1])),
            "four_g": bool(int(sw[2])),
            "ambient_light": bool(int(sw[3])),
            "buzzer": bool(int(sw[4])),
            "dc": bool(int(sw[5])),
            "ac": bool(int(sw[6])),
            "master": bool(int(sw[7])),
        }

    if len(data) >= 56:
        ds = _bits(h(54, 2))
        machine_standby_level = int(ds[1:4], 2)
        result["device_setting"] = {
            "lock": bool(int(ds[0])),
            "machine_standby_level": machine_standby_level,
            # "never" is level 6 - this is the setting behind the
            # "keep powered on" control (command '64').
            "machine_never_standby": machine_standby_level == 6,
            "screen_standby_level": int(ds[4:7], 2),
            "open_reset": bool(int(ds[7])),
        }

    if len(data) >= 58:
        battery = _bits(h(56, 2))
        full_level = int(battery[0:4], 2)
        result["battery_setting"] = {
            "full_level": full_level,
            "lower_level": int(battery[4:8], 2),
            "charge_limit_percent": {1: 100, 2: 90, 3: 80, 4: 70}.get(full_level),
        }

    if len(data) >= 60:
        mode = _bits(h(58, 2))
        input_power_level = int(mode[0:3], 2)
        result["device_mode"] = {
            "input_power_level": input_power_level,
            "max_charge_watts": {1: 300, 2: 500, 3: 800, 4: 1200, 5: 1800}.get(input_power_level),
            "pv": bool(int(mode[3])),
            "ac_voltage_high": bool(int(mode[4])),
            "sleep_mode": bool(int(mode[6])),
            "amp_up": bool(int(mode[7])),
        }

    if len(data) >= 112:
        result["power_factor"] = num(110, 2) / 100

    if len(data) >= 116:
        # Cellular signal quality (csq) and network type, only meaningful
        # on units with the LTE/cellular modem option. csq follows the
        # usual AT+CSQ scale (0-31, 99 = unknown).
        result["cellular"] = {
            "signal_quality": num(112, 2),
            "network_format": num(114, 2),
        }

    if len(data) >= 146:
        result.setdefault("device_info", {})["imei"] = _hex_to_ascii(h(116, 30))

    if len(data) >= 170:
        result.setdefault("device_info", {})["msisdn"] = _hex_to_ascii(h(146, 24))

    if len(data) >= 210:
        result.setdefault("device_info", {})["iccid"] = _hex_to_ascii(h(170, 40))

    if len(data) >= 226:
        info = result.setdefault("device_info", {})
        info["device_id"] = num(210, 4)
        info["dc_firmware_version"] = num(214, 4)
        info["ac_firmware_version"] = num(218, 4)
        info["hardware_version"] = num(222, 2)

    if len(data) >= 228:
        # Celsius = (raw - 2731) / 10
        result["temperature_c"] = round((num(224, 4) - 2731) / 10, 1)

    if len(data) >= 230:
        result.setdefault("device_info", {})["wifi_mode"] = num(228, 2)

    if len(data) >= 292:
        result["wifi_name"] = _hex_to_ascii(h(230, 62))

    if len(data) >= 324:
        # Not surfaced in the dashboard since it's a credential, but
        # available here for anyone scripting against this directly.
        result["wifi_password"] = _hex_to_ascii(h(292, 32))

    if len(data) >= 368:
        # Cell-tower-based location info; typically empty on non-cellular
        # units. Rarely populated/useful, but included for completeness.
        lbs = _hex_to_ascii(h(324, 44))
        if lbs:
            result["lbs_location"] = lbs

    result["raw_data"] = data
    return result


class PowerstationClient:
    """Client for a power station's local TCP control socket, default
    192.168.4.1:5000."""

    HOST = "192.168.4.1"
    PORT = 5000

    def __init__(self, host: str = None, port: int = None, verbose: bool = True):
        self.host = host or self.HOST
        self.port = port or self.PORT
        self.sock: Optional[socket.socket] = None
        self.connected = False
        self.serial = "0001"
        self.verbose = verbose
        # True once quick_connect() has completed on this connection -
        # after that the device pushes '93' status every ~3s on its own.
        self.handshake_done = False
        # imei/iccid/device_id from the handshake, merged into every
        # wait_for_status_push() result.
        self._cached_device_info = None
        # Buffer for partial/unsolicited frames (e.g. an unprompted '61'
        # announcement) so nothing is lost between reads.
        self._recv_buffer = b""

    def _log(self, msg: str):
        if self.verbose:
            print(f"  [powerstation] {msg}", flush=True)

    def connect(self, timeout: float = 5.0):
        """Establish TCP connection to the device."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(timeout)
            self.sock.connect((self.host, self.port))
            self.connected = True
            self._recv_buffer = b""
            self._log(f"connected to {self.host}:{self.port}")
        except Exception as e:
            self.connected = False
            raise PowerstationError(f"Failed to connect: {e}")

    def disconnect(self):
        """Close the TCP connection."""
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.connected = False
        self.handshake_done = False
        self._cached_device_info = None
        self._recv_buffer = b""
        self._log("disconnected")

    def _send_frame(self, command_word: str, data: str, encoding: str = "base2"):
        """Build, log, and send a single frame. Low-level - does not wait
        for or expect a response (see send_command / _read_frame for that)."""
        msg = send_data_conversion(self.serial, command_word, data, encoding)
        self._log(f"-> sent  '{command_word}' data={data!r} ({encoding}) serial={self.serial}")
        self.sock.sendall(msg.encode('utf-8'))
        self.serial = auto_increment_serial(self.serial)

    def _read_frame(self, expected_cmds, timeout: float = 3.0) -> Optional[str]:
        """
        Read frames off the socket until one with a command word in
        expected_cmds turns up, discarding corrupt/unmatched ones.
        Leftover bytes stay buffered for the next call.

        Auto-acks the device's unsolicited '61' identification frame,
        syncing our serial to the device's own sequence. Does NOT
        auto-send '24'/'02' (the WiFi-provisioning trigger) - that's
        only sent explicitly via provision_wifi().

        Returns the matching frame's full text, or None on timeout.
        """
        deadline = time.time() + timeout
        skipped = []

        while True:
            # Resync to the next frame start if there's junk ahead of it.
            start = self._recv_buffer.find(b"AA55")
            if start == -1:
                self._recv_buffer = b""
            elif start > 0:
                self._recv_buffer = self._recv_buffer[start:]

            end = self._recv_buffer.find(b"CC33")
            if end != -1:
                frame_end = end + 4
                raw_frame = self._recv_buffer[:frame_end]
                self._recv_buffer = self._recv_buffer[frame_end:]
                text = raw_frame.decode("utf-8", errors="ignore")

                if not _frame_crc_ok(text):
                    self._log(f"<- received frame with bad CRC, discarding: {text!r}")
                    continue  # corrupt frame, drop and keep looking

                parsed = parse_response_frame(text)
                if not parsed:
                    self._log(f"<- received unparseable frame, discarding: {text!r}")
                    continue
                cmd, data = parsed

                # Resync outgoing serial to follow the device's sequence.
                received_serial = text[8:12]
                self.serial = auto_increment_serial(received_serial)

                if expected_cmds is None or cmd in expected_cmds:
                    self._log(f"<- recv '{cmd}' data_len={len(data)} - matches what we're waiting for")
                    return text

                self._log(f"<- recv unsolicited '{cmd}' (data={data!r}) while waiting for {expected_cmds}")
                if cmd == "61":
                    self._log("   '61' is the device's self-announcement handshake - acking it "
                               "('61'/'55') with a serial synced to its own sequence")
                    try:
                        self._send_frame("61", "55")
                    except Exception as e:
                        self._log(f"   failed to ack '61': {e}")
                elif cmd == "83":
                    self._log("   '83' means the device wants WiFi credentials - "
                               "use provision_wifi() for that.")
                skipped.append(cmd)
                continue  # unsolicited frame - discard, keep waiting

            remaining = deadline - time.time()
            if remaining <= 0:
                if skipped:
                    self._log(f"timed out waiting for {expected_cmds}; ignored along the way: {skipped}")
                else:
                    self._log(f"timed out waiting for {expected_cmds}; nothing else arrived")
                return None
            try:
                self.sock.settimeout(min(remaining, 2.0))
                chunk = self.sock.recv(2048)
            except socket.timeout:
                continue
            if not chunk:
                raise PowerstationError("Connection closed by device")
            self._recv_buffer += chunk

    def send_command(
        self,
        command_word: str,
        data: str,
        encoding: str = "base2",
        timeout: float = 3.0,
        expected_cmds=None,
    ) -> Optional[str]:
        """
        Send a command and wait for the matching response, ignoring
        unsolicited frames in the meantime. Defaults to expecting the
        same command_word echoed back; pass expected_cmds otherwise.

        Runs the '24'/'01' handshake first if it hasn't happened yet
        on this connection - required before the device will respond
        to most commands.
        """
        if not self.connected or not self.sock:
            raise PowerstationError("Not connected")

        if not self.handshake_done and command_word not in ("61", "24"):
            self.quick_connect(timeout=15.0)

        if expected_cmds is None:
            expected_cmds = {command_word}

        try:
            self._send_frame(command_word, data, encoding)

            if timeout <= 0:
                return None

            return self._read_frame(expected_cmds, timeout=timeout)

        except PowerstationError:
            raise
        except Exception as e:
            self.connected = False
            raise PowerstationError(f"Command failed: {e}")

    # ---------- Status ----------

    def request_status(self) -> Optional[str]:
        """Request device status (command '34', data '01'). Response
        comes back as '93' - see wait_for_status_push() for the
        preferred way to get status, since '34' itself triggers
        nothing; status is pushed by the device on its own schedule."""
        return self.send_command("34", "01", timeout=5.0, expected_cmds={"34", "79", "75", "93"})

    def listen_passively(self, duration: float = 90.0) -> None:
        """Connect and listen without sending anything, including no
        status request. Auto-acks any '61' the device sends. Relies on
        verbose logging to surface whatever arrives."""
        self._read_frame(expected_cmds=set(), timeout=duration)

    def monitor_after_handshake(self, listen_duration: float = 60.0) -> dict:
        """
        Run the handshake, then listen passively for listen_duration,
        timestamping every frame received (confirms the device pushes
        '93' status on its own roughly every 3s once connected).

        Returns {'handshake': quick_connect's result dict,
                 'frames': [(elapsed_seconds, command_word, data), ...]}
        """
        handshake_result = self.quick_connect(timeout=15.0)
        frames = []
        if not handshake_result.get("success"):
            return {"handshake": handshake_result, "frames": frames}

        start = time.time()
        deadline = start + listen_duration
        self._log(f"monitoring: handshake done, now listening passively for {listen_duration:.0f}s, "
                  f"timestamping everything that arrives...")

        while time.time() < deadline:
            start_idx = self._recv_buffer.find(b"AA55")
            if start_idx == -1:
                self._recv_buffer = b""
            elif start_idx > 0:
                self._recv_buffer = self._recv_buffer[start_idx:]

            end = self._recv_buffer.find(b"CC33")
            if end != -1:
                frame_end = end + 4
                raw_frame = self._recv_buffer[:frame_end]
                self._recv_buffer = self._recv_buffer[frame_end:]
                text = raw_frame.decode("utf-8", errors="ignore")

                if not _frame_crc_ok(text):
                    continue
                frame = parse_response_frame(text)
                if not frame:
                    continue
                cmd, data = frame
                elapsed = time.time() - start
                self.serial = auto_increment_serial(text[8:12])

                if cmd == "61":
                    self._send_frame("61", "55")

                frames.append((elapsed, cmd, data))
                self._log(f"<- [{elapsed:6.1f}s] recv '{cmd}' data_len={len(data)}")
                continue

            try:
                self.sock.settimeout(2.0)
                chunk = self.sock.recv(2048)
            except socket.timeout:
                continue
            except Exception as e:
                self._log(f"monitoring: connection error, stopping early: {e}")
                break
            if not chunk:
                self._log("monitoring: connection closed by device, stopping early")
                break
            self._recv_buffer += chunk

        if len(frames) >= 2:
            gaps = [frames[i + 1][0] - frames[i][0] for i in range(len(frames) - 1)]
            self._log(f"monitoring: {len(frames)} frames received, gaps between them: "
                      f"{[f'{g:.1f}s' for g in gaps]}")
        else:
            self._log(f"monitoring: only {len(frames)} frame(s) received in {listen_duration:.0f}s")

        return {"handshake": handshake_result, "frames": frames}

    def get_status(self) -> dict:
        """Request status and parse it into a dict. Raises PowerstationError
        if no response is received."""
        raw = self.request_status()
        if not raw:
            raise PowerstationError("No response from device")
        frame = parse_response_frame(raw)
        if not frame:
            return {"raw": raw, "note": "unrecognized response format"}
        command_word, data = frame
        if command_word == "93":
            parsed = parse_status_93_payload(data)
            parsed["command_word"] = command_word
            parsed["raw"] = raw
            parsed["data_hex"] = data
            return parsed
        if len(data) >= 90:
            parsed = parse_status_payload(data)
            parsed["command_word"] = command_word
            return parsed
        return {"command_word": command_word, "ack": parse_ack(data), "raw": raw}

    def wait_for_status_push(self, timeout: float = 5.0) -> dict:
        """
        Wait for the device's next unsolicited '93' status push (sent
        roughly every 3s once connected - '34' itself triggers nothing).
        Runs the handshake first if needed, and merges in cached
        device_info (imei/iccid/device_id) from it.
        """
        if not self.handshake_done:
            result = self.quick_connect(timeout=15.0)
            if not result.get("success"):
                raise PowerstationError("quick_connect handshake failed - can't get status without it")
            self._cached_device_info = {
                k: v for k, v in result.items()
                if k in ("device_id", "imei", "msisdn", "iccid") and v
            }

        raw = self._read_frame(expected_cmds={"93"}, timeout=timeout)
        if not raw:
            raise PowerstationError(f"No status push arrived within {timeout:.0f}s")
        frame = parse_response_frame(raw)
        if not frame:
            return {"raw": raw, "note": "unrecognized response format"}
        _, data = frame
        parsed = parse_status_93_payload(data)
        parsed["command_word"] = "93"
        parsed["raw"] = raw
        parsed["data_hex"] = data
        if getattr(self, "_cached_device_info", None):
            parsed["device_info"] = dict(self._cached_device_info)
        return parsed

    # ---------- Switch controls ----------
    # master/AC/DC/ambient-light use the bitmask command '12', not the
    # documented single-purpose commands ('48'/'50'/'52'/'56'), which
    # are gated behind a firmware flag this device doesn't set.

    def _set_switch(self, command_word: str, on: bool):
        """Single-purpose on/off command, used by switches without a
        confirmed bitmask path (sleep, AC Hz, 4G)."""
        self.send_command(command_word, "00" if on else "01", timeout=2.0)

    def set_master_switch(self, on: bool):
        """Master power switch on/off, via the '12' bitmask."""
        return self.toggle_switch_via_legacy_bitmask("master", on)

    def set_ac_output(self, on: bool):
        """AC output on/off, via the '12' bitmask."""
        return self.toggle_switch_via_legacy_bitmask("ac", on)

    def set_dc_output(self, on: bool):
        """DC outputs on/off, via the '12' bitmask."""
        return self.toggle_switch_via_legacy_bitmask("dc", on)

    def set_ambient_light(self, on: bool):
        """Ambient light strip on/off, via the '12' bitmask."""
        return self.toggle_switch_via_legacy_bitmask("ambient_light", on)

    def set_buzzer(self, on: bool):
        """Buzzer on/off (command '54'). Note: '01'=on, '00'=off - the
        reverse of the convention used by other switches."""
        self.send_command("54", "01" if on else "00", timeout=2.0)

    def set_ac_frequency(self, hz: int):
        """AC output frequency, 50 or 60 Hz (command '62')."""
        if hz not in (50, 60):
            raise ValueError("hz must be 50 or 60")
        self.send_command("62", "00" if hz == 60 else "01", timeout=2.0)

    def set_four_g_switch(self, on: bool):
        """4G/LTE radio on/off (command '58'); not independently confirmed."""
        self._set_switch("58", on)

    def set_amp_up_mode(self, on: bool):
        """AmpUp mode on/off (command '20'). Sends the full AmpUp/
        sleep-mode byte from current status with only bit0 changed."""
        status = self.wait_for_status_push(timeout=8.0)
        data_hex = status.get("data_hex", "")
        current_amp_byte = int(data_hex[40:42], 16) if len(data_hex) >= 42 else 0
        new_byte = (current_amp_byte | 0x01) if on else (current_amp_byte & 0xFE)
        self.send_command("20", format(int(format(new_byte, '08b'), 2), '02X'), timeout=2.0)

    def set_sleep_mode(self, on: bool):
        """Sleep mode on/off (command '20'). Internally this is the
        same field referred to as silentInput in the param bean, but
        the UI view ID (switch_silent_mode, icon ic_sleep/ic_sleep_no)
        confirms it as sleep mode. Same byte as AmpUp, bit1 instead of
        bit0."""
        status = self.wait_for_status_push(timeout=8.0)
        data_hex = status.get("data_hex", "")
        current_amp_byte = int(data_hex[40:42], 16) if len(data_hex) >= 42 else 0
        new_byte = (current_amp_byte | 0x02) if on else (current_amp_byte & 0xFD)
        self.send_command("20", format(int(format(new_byte, '08b'), 2), '02X'), timeout=2.0)

    # ---------- Multi-level settings ----------

    def set_machine_standby_minutes(self, level: int):
        """Auto power-off-when-idle timeout (command '64').
        6=never, 5=12h, 4=6h, 3=2h, 2=1h, 1=shortest."""
        if not 1 <= level <= 6:
            raise ValueError("Standby level must be 1-6 (6 = never)")
        self.send_command("64", format(level, '02X'), timeout=2.0)

    def set_keep_powered_on(self, enabled: bool, off_level: int = 1):
        """Convenience wrapper: True sets standby to "never" (level 6),
        False restores a timeout (default: shortest)."""
        self.set_machine_standby_minutes(6 if enabled else off_level)

    def set_screen_standby_minutes(self, level: int):
        """Screen/display backlight standby timeout (command '66'),
        separate from the whole-unit timeout above. Not independently
        confirmed against hardware."""
        if not 1 <= level <= 6:
            raise ValueError("Standby level must be 1-6 (assumed range, unconfirmed)")
        self.send_command("66", format(level, '02X'), timeout=2.0)

    # Bit order for the legacy 8-bit switch bitmask, MSB to LSB.
    LEGACY_BITMASK_POSITIONS = ["ac_hz", "lbs", "four_g", "ambient_light",
                                 "buzzer", "dc", "ac", "master"]

    def toggle_switch_via_legacy_bitmask(self, switch_name: str, turn_on: bool) -> dict:
        """
        Toggle one switch via command '12', which carries the full
        8-bit switch state in a single byte. Reads fresh status first
        and changes only the targeted bit, leaving the other 7 as
        reported.
        """
        if switch_name not in self.LEGACY_BITMASK_POSITIONS:
            raise ValueError(f"switch_name must be one of {self.LEGACY_BITMASK_POSITIONS}")

        status = self.wait_for_status_push(timeout=8.0)
        switches = status.get("switches")
        if not switches:
            raise PowerstationError("Could not read current switch state before toggling.")

        bits = []
        for name in self.LEGACY_BITMASK_POSITIONS:
            if name == switch_name:
                bits.append("1" if turn_on else "0")
            else:
                bits.append("1" if switches.get(name) else "0")
        bitstring = "".join(bits)
        hex_value = format(int(bitstring, 2), '02X')

        self._log(f"bitmask toggle: {switch_name}={'on' if turn_on else 'off'}, "
                  f"preserving the rest. "
                  f"Full bitstring: {bitstring} (command '12', data '{hex_value}')")

        resp = self.send_command("12", hex_value, timeout=3.0, expected_cmds={"12"})
        return {"sent_bitstring": bitstring, "sent_hex": hex_value, "response": resp,
                "status_before": status}

    def set_max_charge_watts(self, watts: int):
        """Maximum AC charge speed in watts, via command '72'.
        One of: 300, 500, 800, 1200, 1800."""
        level_map = {300: 1, 500: 2, 800: 3, 1200: 4, 1800: 5}
        if watts not in level_map:
            raise ValueError("Max charge watts must be one of 300, 500, 800, 1200, 1800")
        self.send_command("72", format(level_map[watts], '02X'), timeout=2.0)

    def set_charge_limit(self, percent: int):
        """
        Battery charge limit percentage (command '18'): 100, 90, 80, or
        70. Encoding: percentage as binary, left-padded to 4 bits, with
        literal suffix '0001' appended, converted to hex (e.g. 100% =
        '0641').
        """
        if percent not in (100, 90, 80, 70):
            raise ValueError("Charge limit must be one of 100, 90, 80, 70")
        binary_str = format(percent, 'b')
        if len(binary_str) < 4:
            binary_str = "0" + binary_str
        combined = binary_str + "0001"
        int_value = int(combined, 2)
        hex_str = format(int_value, 'X')
        if len(hex_str) % 2 == 1:
            hex_str = "0" + hex_str
        self.send_command("18", hex_str, timeout=2.0)

    # ---------- LED controls ----------

    def set_led_brightness(self, brightness: int):
        """Set LED brightness (0-100%)."""
        if not 0 <= brightness <= 100:
            raise ValueError("Brightness must be between 0 and 100")
        self.send_command("74", format(brightness, '02X'), timeout=2.0)

    def set_led_color(self, color_id: int):
        """Set LED color using predefined IDs (1-10):
        1 white, 2 pink, 3 purple, 4 blue, 5 light blue, 6 cyan,
        7 brand/orange, 8 yellow-green, 9 orange, 10 red."""
        if not 1 <= color_id <= 10:
            raise ValueError("Color ID must be between 1 and 10")
        self.send_command("76", format(color_id, '02X'), timeout=2.0)

    def set_led_color_and_brightness(self, color_id: int, brightness: int):
        """
        Set LED color and brightness together in one command ('22'),
        as an alternative to set_led_color()/set_led_brightness() via
        '76'/'74'. 16-bit value = '001' prefix + 5-bit color_id +
        8-bit brightness, packed and sent as 4 hex chars.
        """
        if not 1 <= color_id <= 10:
            raise ValueError("Color ID must be between 1 and 10")
        if not 0 <= brightness <= 100:
            raise ValueError("Brightness must be between 0 and 100")
        color_bin = format(color_id, '05b')
        brightness_bin = format(brightness, '08b')
        full_bin = "001" + color_bin + brightness_bin
        int_value = int(full_bin, 2)
        hex_str = format(int_value, 'X')
        if len(hex_str) % 2 == 1:
            hex_str = "0" + hex_str
        self.send_command("22", hex_str, timeout=2.0)

    # ---------- Undocumented commands, found by probing ----------

    def trigger_amp_up_on(self):
        """Turn AmpUp mode on via command '20' (alternative to
        set_amp_up_mode, with no off-direction equivalent here)."""
        self.send_command("20", "01", timeout=2.0)

    def trigger_power_off(self):
        """Power off the unit (command '12', data '00'). Requires the
        physical power button to turn back on."""
        self.send_command("12", "00", timeout=2.0)

    # ---------- WiFi provisioning ----------
    # Run this while connected to the device's own hotspot (192.168.4.1),
    # not your home network.
    #
    # Handshake:
    #   device -> '61' (announces itself: deviceId/imei/msisdn/iccid)
    #   us     -> '61' ACK ('55'), then '24' / '02' (start provisioning)
    #   device -> '24' ACK (no action, just wait)
    #   device -> '83' data='00'  (asking for SSID)
    #   us     -> '83' ACK ('55'), then '30' / <ssid>  (ascii)
    #   device -> '30' ACK (no action, just wait)
    #   device -> '83' data!='00' (asking for password)
    #   us     -> '83' ACK ('55'), then '32' / <password>  (ascii)
    #   device -> '32' ACK -> us -> '26' / '03' (close provisioning mode)
    #   device -> '26' ACK -> done

    def provision_wifi(self, ssid: str, password: str, timeout: float = 30.0,
                        on_progress=None) -> dict:
        """
        Join the device to a home Wi-Fi network. Must be called after
        connect() while on the device's own hotspot.

        on_progress, if given, is called as on_progress(percent, message)
        as the handshake advances (matches the app's own progress bar:
        20/40/60/80/100).

        Returns a dict with any device info announced during the
        handshake (device_id/imei/msisdn/iccid) plus success=True.
        Raises PowerstationError on timeout, malformed data, or if the
        connection drops mid-handshake.
        """
        if not self.connected or not self.sock:
            raise PowerstationError(
                "Not connected. Connect while on the device's own Wi-Fi "
                "hotspot (192.168.4.1) before provisioning."
            )

        def report(pct, msg):
            if on_progress:
                on_progress(pct, msg)

        device_info = {}
        buf = b""
        deadline = time.time() + timeout
        self.sock.settimeout(2.0)

        self._log(f"provisioning: waiting up to {timeout:.0f}s for the device to announce itself...")
        report(0, "Waiting for device to announce itself...")
        last_heartbeat = time.time()

        while time.time() < deadline:
            try:
                chunk = self.sock.recv(2048)
            except socket.timeout:
                if time.time() - last_heartbeat >= 5.0:
                    remaining = deadline - time.time()
                    self._log(f"provisioning: still nothing after waiting, {remaining:.0f}s left before giving up")
                    last_heartbeat = time.time()
                continue
            except Exception as e:
                raise PowerstationError(f"Connection lost during provisioning: {e}")

            if not chunk:
                raise PowerstationError("Connection closed by device during provisioning")
            buf += chunk

            while b"CC33" in buf:
                end = buf.index(b"CC33") + 4
                raw_frame = buf[:end]
                buf = buf[end:]
                text = raw_frame.decode("utf-8", errors="ignore")

                if not _frame_crc_ok(text):
                    self._log(f"<- received frame with bad CRC during provisioning, discarding: {text!r}")
                    continue

                frame = parse_response_frame(text)
                if not frame:
                    self._log(f"<- received unparseable frame during provisioning, discarding: {text!r}")
                    continue
                cmd, data = frame

                # Resync outgoing serial to follow the device's sequence.
                self.serial = auto_increment_serial(text[8:12])
                self._log(f"<- recv '{cmd}' data={data!r} (serial resynced to {self.serial})")

                if cmd == "61":
                    try:
                        device_info["device_id"] = int(data[-8:], 16)
                        device_info["imei"] = _hex_to_ascii(data[0:32])
                        device_info["msisdn"] = _hex_to_ascii(data[32:58])
                        device_info["iccid"] = _hex_to_ascii(data[58:98])
                    except (ValueError, IndexError):
                        pass
                    report(20, "Device found, starting provisioning...")
                    self._send_frame("61", "55")
                    self._send_frame("24", "02")

                elif cmd == "24":
                    report(40, "Provisioning mode started...")

                elif cmd == "83":
                    self._send_frame("83", "55")
                    if data == "00":
                        report(50, f"Sending network name ({ssid})...")
                        self._send_frame("30", ssid, encoding="ascii")
                    else:
                        report(70, "Sending password...")
                        self._send_frame("32", password, encoding="ascii")

                elif cmd == "30":
                    report(60, "Network name acknowledged...")

                elif cmd == "32":
                    report(80, "Password acknowledged, closing provisioning mode...")
                    self._send_frame("26", "03")

                elif cmd == "26":
                    report(100, "Done.")
                    device_info["success"] = True
                    return device_info

        self._log(f"provisioning: gave up after the full {timeout:.0f}s with no response at all from the device")
        raise PowerstationError("Wi-Fi provisioning timed out waiting for the device")

    def quick_connect(self, timeout: float = 15.0) -> dict:
        """
        Simpler control-mode handshake: '61' ack, then '24'/'01' (vs.
        the full '24'/'02' + SSID/password flow used for first-time
        WiFi setup). Once the device acks '24', it's ready for control
        and begins pushing status pushes.

        Returns a dict with device info from '61', plus 'success': True
        if the device acked '24'.
        """
        device_info = {}
        deadline = time.time() + timeout

        self._log(f"quick-connect: waiting up to {timeout:.0f}s for the device to announce itself...")

        while time.time() < deadline:
            # Resync to the next frame start if there's junk ahead of it.
            start = self._recv_buffer.find(b"AA55")
            if start == -1:
                self._recv_buffer = b""
            elif start > 0:
                self._recv_buffer = self._recv_buffer[start:]

            end = self._recv_buffer.find(b"CC33")
            if end != -1:
                frame_end = end + 4
                raw_frame = self._recv_buffer[:frame_end]
                self._recv_buffer = self._recv_buffer[frame_end:]
                text = raw_frame.decode("utf-8", errors="ignore")

                if not _frame_crc_ok(text):
                    self._log(f"<- received frame with bad CRC during quick-connect, discarding: {text!r}")
                    continue

                frame = parse_response_frame(text)
                if not frame:
                    self._log(f"<- received unparseable frame during quick-connect, discarding: {text!r}")
                    continue
                cmd, data = frame

                self.serial = auto_increment_serial(text[8:12])
                self._log(f"<- recv '{cmd}' data={data!r} (serial resynced to {self.serial})")

                if cmd == "61":
                    try:
                        device_info["device_id"] = int(data[-8:], 16)
                        device_info["imei"] = _hex_to_ascii(data[0:32])
                        device_info["msisdn"] = _hex_to_ascii(data[32:58])
                        device_info["iccid"] = _hex_to_ascii(data[58:98])
                    except (ValueError, IndexError):
                        pass
                    self._send_frame("61", "55")
                    self._send_frame("24", "01")

                elif cmd == "24":
                    self._log("quick-connect: device acked '24' - this is what the app itself "
                              "treats as 'ready for control', with no SSID/password ever sent")
                    device_info["success"] = True
                    self.handshake_done = True
                    return device_info

                elif cmd == "93":
                    self._log("   '93' is an unsolicited status push arriving mid-handshake - "
                              "noted but not acted on here, left for a later request_status() "
                              "call to pick up properly")

                continue  # keep draining any further complete frames already buffered

            try:
                self.sock.settimeout(2.0)
                chunk = self.sock.recv(2048)
            except socket.timeout:
                continue
            except Exception as e:
                raise PowerstationError(f"Connection lost during quick-connect: {e}")
            if not chunk:
                raise PowerstationError("Connection closed by device during quick-connect")
            self._recv_buffer += chunk

        self._log(f"quick-connect: gave up after the full {timeout:.0f}s with no '24' ack from the device")
        device_info["success"] = False
        return device_info

    # ---------- IP scanning helpers (after joining Wi-Fi) ----------

    @staticmethod
    def ping_host(ip: str, timeout: float = 1.0) -> bool:
        """Ping a host using the system ping command."""
        try:
            if sys.platform.startswith('win'):
                cmd = ['ping', '-n', '1', '-w', str(int(timeout * 1000)), ip]
            else:
                cmd = ['ping', '-c', '1', '-W', str(max(1, int(round(timeout)))), ip]
            result = subprocess.run(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=timeout + 1
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def scan_subnet_for_device(subnet_prefix: str = "192.168.4", max_hosts: int = 254,
                                timeout_per_host: float = 0.3):
        """Scan a subnet for reachable hosts using parallel pings."""
        found_ips = []
        lock = threading.Lock()

        def worker(ip_last):
            ip = f"{subnet_prefix}.{ip_last}"
            if PowerstationClient.ping_host(ip, timeout=timeout_per_host):
                with lock:
                    found_ips.append(ip)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(1, max_hosts + 1)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=max(timeout_per_host * 5, 3.0))

        return sorted(found_ips)


def main():
    parser = argparse.ArgumentParser(description="Powerstation control interface.")

    parser.add_argument("--host", default="192.168.4.1", help="Device IP (default: 192.168.4.1)")
    parser.add_argument("--port", type=int, default=5000, help="Device port (default: 5000)")

    parser.add_argument("--status", action="store_true", help="Request device status")
    parser.add_argument("--quick-connect-test", action="store_true",
                         help="Run the simpler '24'/'01' handshake, then request status to "
                              "confirm the connection is in control mode.")
    parser.add_argument("--led-brightness", type=int, metavar="VALUE", help="Set LED brightness 0-100")
    parser.add_argument("--led-color", type=int, metavar="ID", help="Set LED color ID (1-10)")
    parser.add_argument("--led-color-and-brightness", nargs=2, type=int, metavar=("COLOR_ID", "BRIGHTNESS"),
                         help="Set color and brightness in one combined command ('22')")
    parser.add_argument("--charge-limit", type=int, choices=[70, 80, 90, 100], metavar="PCT",
                         help="Set charge limit percentage")
    parser.add_argument("--master-switch", choices=["on", "off"], help="Master switch on/off")
    parser.add_argument("--ac-output", choices=["on", "off"], help="AC output on/off")
    parser.add_argument("--legacy-toggle", nargs=2, metavar=("SWITCH", "STATE"),
                         help="Toggle a switch via the bitmask command ('12'). SWITCH is one of "
                              "ac_hz,lbs,four_g,ambient_light,buzzer,dc,ac,master. STATE is on/off. "
                              "Example: --legacy-toggle ac on")
    parser.add_argument("--dc-output", choices=["on", "off"], help="DC outputs on/off")
    parser.add_argument("--buzzer", choices=["on", "off"], help="Buzzer on/off")
    parser.add_argument("--ambient-light", choices=["on", "off"], help="Ambient light strip on/off")
    parser.add_argument("--sleep-mode", choices=["enable", "disable"], help="Enable/disable sleep mode")
    parser.add_argument("--amp-up", choices=["on", "off"], help="AmpUp mode on/off")
    parser.add_argument("--ac-hz", type=int, choices=[50, 60], help="Set AC output frequency")
    parser.add_argument("--local-amp-up-on", action="store_true",
                         help="Turn AmpUp mode on via command '20'")
    parser.add_argument("--local-power-off", action="store_true",
                         help="Power off the unit via command '12'. Requires the physical "
                              "power button to turn back on.")
    parser.add_argument("--screen-standby", type=int, metavar="LEVEL",
                         help="Screen backlight standby level (command '66'), 1-6.")
    parser.add_argument("--listen", type=float, metavar="SECONDS",
                         help="Connect and listen for SECONDS without sending anything, "
                              "including no status request.")
    parser.add_argument("--monitor-after-handshake", type=float, metavar="SECONDS",
                         help="Run the handshake, then listen passively for SECONDS, "
                              "timestamping every frame that arrives.")
    parser.add_argument("--charge-speed", type=int, choices=[300, 500, 800, 1200, 1800], metavar="WATTS",
                         help="Set max AC charge speed in watts")
    parser.add_argument("--wifi-ssid", type=str, help="Wi-Fi SSID to join (run while on the device's own hotspot)")
    parser.add_argument("--wifi-pass", type=str,
                         help="Wi-Fi password for --wifi-ssid. If omitted, you'll be prompted "
                              "securely instead - recommended if your password contains '!' "
                              "(use single quotes if you do pass it directly: --wifi-pass 'p!w')")
    parser.add_argument("--scan-subnet", type=str, help="Scan subnet for device IP (e.g., 192.168.4)")

    args = parser.parse_args()

    if args.scan_subnet:
        print(f"\nScanning subnet {args.scan_subnet}.x for reachable devices...")
        ips = PowerstationClient.scan_subnet_for_device(subnet_prefix=args.scan_subnet)
        print("Found IPs:", ", ".join(ips) if ips else "(none found)")
        return

    client = PowerstationClient(host=args.host, port=args.port)

    try:
        client.connect()

        if args.quick_connect_test:
            print("\nRunning the '24'/'01' handshake...")
            result = client.quick_connect(timeout=15.0)
            print(f"quick_connect result: {result}")
            if result.get("success"):
                print("\nDevice acked '24' - requesting status...")
                status_resp = client.request_status()
                if status_resp:
                    print(f"\nStatus response: {status_resp}")
                    frame = parse_response_frame(status_resp)
                    if frame:
                        cmd, data = frame
                        print(f"command word: '{cmd}'")
                        if cmd == "93":
                            parsed_93 = parse_status_93_payload(data)
                            print(f"\nConfirmed fields:")
                            print(f"  battery: {parsed_93['battery_percent']}%")
                            print(f"  AC output: {parsed_93['ac_output_watts']}W")
                            print(f"  DC output: {parsed_93['dc_output_watts']}W")
                            print(f"  AmpUp: {'on' if parsed_93['amp_up'] else 'off'}")
                            print(f"\nCode-derived fields:")
                            print(f"  AC input: {parsed_93['ac_input_watts']}W")
                            print(f"  DC input: {parsed_93['dc_input_watts']}W")
                            print(f"  ambient light: brightness={parsed_93['ambient_lightness']} "
                                  f"color={parsed_93['ambient_color']}")
                            if parsed_93['switches']:
                                print(f"  switches: {parsed_93['switches']}")
                            print(f"\nFull byte breakdown ({parsed_93['byte_count']} bytes):")
                            for i, b in enumerate(parsed_93["bytes"]):
                                tag = ""
                                if i == 0:
                                    tag = "  <- battery %"
                                elif i in (9, 10):
                                    tag = "  <- AC output watts (2-byte)"
                                elif i == 20:
                                    tag = "  <- AmpUp switch"
                                elif i in (5, 6):
                                    tag = "  <- AC input watts (2-byte)"
                                elif i in (7, 8):
                                    tag = "  <- DC input watts (2-byte)"
                                elif i in (11, 12):
                                    tag = "  <- DC output watts (2-byte)"
                                elif i == 13:
                                    tag = "  <- ambient brightness"
                                elif i == 14:
                                    tag = "  <- ambient color"
                                elif i == 17:
                                    tag = "  <- switch bitmask"
                                print(f"  byte[{i:2}] = 0x{b} = {int(b, 16):3} decimal{tag}")
                else:
                    print("\nStill no status response - the '24'/'01' handshake alone wasn't enough on its own.")
            else:
                print("\nDevice never acked '24' within the timeout.")

        if args.status:
            print("\nRequesting device status...")
            status = client.get_status()
            import json
            print(json.dumps(status, indent=2))

        if args.led_brightness is not None:
            print(f"\nSetting LED brightness to {args.led_brightness}%...")
            client.set_led_brightness(args.led_brightness)

        if args.led_color is not None:
            print(f"\nSetting LED color ID to {args.led_color}...")
            client.set_led_color(args.led_color)

        if args.led_color_and_brightness is not None:
            color_id, brightness = args.led_color_and_brightness
            print(f"\nSetting LED color {color_id} + brightness {brightness} (combined '22' command)...")
            client.set_led_color_and_brightness(color_id, brightness)

        if args.charge_limit is not None:
            print(f"\nSetting charge limit to {args.charge_limit}%...")
            client.set_charge_limit(args.charge_limit)

        if args.master_switch in ("on", "off"):
            print(f"\nSetting master switch {args.master_switch.upper()}...")
            client.set_master_switch(args.master_switch == "on")

        if args.ac_output in ("on", "off"):
            print(f"\nSetting AC output {args.ac_output.upper()}...")
            client.set_ac_output(args.ac_output == "on")

        if args.legacy_toggle is not None:
            switch_name, state = args.legacy_toggle
            state = state.lower()
            if state not in ("on", "off"):
                print(f"\nState must be 'on' or 'off', got {state!r}")
            else:
                print(f"\nToggling '{switch_name}' to {state} via the bitmask command ('12')...")
                try:
                    result = client.toggle_switch_via_legacy_bitmask(switch_name, state == "on")
                    print(f"Sent bitstring {result['sent_bitstring']} (hex {result['sent_hex']}) "
                          f"via command '12'.")
                    print(f"Response: {result['response']}")
                except PowerstationError as e:
                    print(f"Error: {e}")

        if args.dc_output in ("on", "off"):
            print(f"\nSetting DC outputs {args.dc_output.upper()}...")
            client.set_dc_output(args.dc_output == "on")

        if args.buzzer in ("on", "off"):
            print(f"\nSetting buzzer {args.buzzer.upper()}...")
            client.set_buzzer(args.buzzer == "on")

        if args.ambient_light in ("on", "off"):
            print(f"\nSetting ambient light {args.ambient_light.upper()}...")
            client.set_ambient_light(args.ambient_light == "on")

        if args.sleep_mode in ("enable", "disable"):
            enabled = args.sleep_mode == "enable"
            print(f"\nSetting sleep mode to {'ENABLED' if enabled else 'DISABLED'}...")
            client.set_sleep_mode(enabled)

        if args.amp_up in ("on", "off"):
            print(f"\nSetting AmpUp mode {args.amp_up.upper()}...")
            client.set_amp_up_mode(args.amp_up == "on")

        if args.ac_hz is not None:
            print(f"\nSetting AC frequency to {args.ac_hz}Hz...")
            client.set_ac_frequency(args.ac_hz)

        if args.local_amp_up_on:
            print("\nTurning AmpUp mode on via command '20'...")
            client.trigger_amp_up_on()

        if args.local_power_off:
            confirm = input("\nThis will power off the unit (command '12'). Only the "
                             "physical button is confirmed to bring it back on. "
                             "Type 'yes' to proceed: ").strip().lower()
            if confirm == "yes":
                print("Powering off...")
                client.trigger_power_off()
            else:
                print("Cancelled.")

        if args.screen_standby is not None:
            print(f"\nSetting screen standby level to {args.screen_standby} (command '66')...")
            client.set_screen_standby_minutes(args.screen_standby)

        if args.listen is not None:
            print(f"\nListening passively for {args.listen:.0f}s, sending nothing...")
            client.listen_passively(duration=args.listen)
            print("Done listening - anything that arrived was logged above.")

        if args.monitor_after_handshake is not None:
            print(f"\nDoing the '24'/'01' handshake, then listening passively for "
                  f"{args.monitor_after_handshake:.0f}s, timestamping everything that arrives...")
            result = client.monitor_after_handshake(listen_duration=args.monitor_after_handshake)
            if not result["handshake"].get("success"):
                print("\nHandshake itself failed - nothing to monitor.")
            else:
                frames = result["frames"]
                print(f"\n{len(frames)} frame(s) received during the monitoring window:")
                for elapsed, cmd, data in frames:
                    print(f"  [{elapsed:6.1f}s] '{cmd}' (data_len={len(data)})")
                if len(frames) >= 2:
                    gaps = [frames[i + 1][0] - frames[i][0] for i in range(len(frames) - 1)]
                    print(f"\nGaps between consecutive frames: {[f'{g:.1f}s' for g in gaps]}")
                    print("If these gaps are roughly consistent, that's a real periodic push, not luck.")

        if args.charge_speed is not None:
            print(f"\nSetting max AC charge speed to {args.charge_speed}W...")
            client.set_max_charge_watts(args.charge_speed)

        if args.wifi_ssid:
            wifi_pass = args.wifi_pass
            if wifi_pass is None:
                wifi_pass = getpass.getpass(f"Wi-Fi password for \"{args.wifi_ssid}\": ")

            print(f"\nProvisioning Wi-Fi for SSID: {args.wifi_ssid}...")
            print("(Make sure you're connected to the device's own hotspot, not your home network.)")

            def _print_progress(pct, msg):
                print(f"  [{pct:3d}%] {msg}")

            info = client.provision_wifi(args.wifi_ssid, wifi_pass, on_progress=_print_progress)
            print("Provisioning complete:", info)

    except PowerstationError as e:
        print(f"Error: {e}")
    finally:
        if client.connected:
            client.disconnect()


if __name__ == "__main__":
    main()
