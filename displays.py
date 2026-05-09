"""
AV Display Emulator
Supports: Christie Secure Series II (K:ALL ASCII protocol)
          Philips SICP (binary Serial/IP Control Protocol)
          LG Commercial (ASCII RS232/IP protocol, port 9761)
          Samsung MDC (binary Multiple Display Control, port 1515)
          NEC MultiSync (SOH/STX/ETX ASCII-encoded HEX, port 7142)
Multi-instance, multiple protocols, full input switching.
"""

import asyncio
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from datetime import datetime

# ─────────────────────────────────────────────────────────────
# COLOUR PALETTE
# ─────────────────────────────────────────────────────────────
DARK   = "#141414"
PANEL  = "#1c1c1c"
BORDER = "#2a2a2a"
ACCENT = "#049fd9"
GREEN  = "#27ae60"
RED    = "#c0392b"
AMBER  = "#f0a500"
TEXT   = "#e8e8e8"
DIM    = "#888888"
BTN    = "#252525"
BTN_HV = "#333333"


# ─────────────────────────────────────────────────────────────
# 1. PROTOCOL HANDLERS
# ─────────────────────────────────────────────────────────────

class ChristieProtocol:
    """
    Christie Secure Series II — K:ALL ASCII protocol.
    Reference: 020-001915-01 Rev.1 (03-2021)

    Command formats:
      Direct:     K:ALL<CMD>.          e.g. K:ALLPON.
      Value-set:  K:ALL<CMD><NNN>.     e.g. K:ALLVOL050.
      Query:      K:ALL<CMD>?          e.g. K:ALLPWR?

    Response formats:
      Query/value: ALL:<CMD>=<NNN>\\r
      ACK:         ALL:<CMD>=A\\r
      Error:       ALL:<CMD>=N\\r
    """
    NAME         = "Christie Secure II"
    DEFAULT_PORT = 5000
    BINARY       = False

    POWER_ON   = "000"   # 000 = On
    POWER_OFF  = "001"   # 001 = Off (power save)
    POWER_OFF2 = "002"   # 002 = Off (RS232 / remote control) — default standby on real hardware

    # Full source map per manual p.9 / p.17 — SH cmd -> SRC? reply code
    # Note: there is no SH6 in the specification
    SOURCE_MAP = {
        "SH0": "000",   # DP 1
        "SH1": "001",   # DP 2
        "SH2": "002",   # HDMI 1
        "SH3": "003",   # HDMI 2
        "SH4": "004",   # HDMI 3
        "SH5": "005",   # HDMI 4
        "SH7": "007",   # OPS / HDMI
        "SH8": "008",   # OPS / DP
    }

    SOURCE_LABELS = {
        "000": "DP 1",
        "001": "DP 2",
        "002": "HDMI 1",
        "003": "HDMI 2",
        "004": "HDMI 3",
        "005": "HDMI 4",
        "007": "OPS/HDMI",
        "008": "OPS/DP",
    }

    @staticmethod
    def format_status(cmd, value):
        return f"ALL:{cmd}={value}\r"

    @staticmethod
    def format_ack(cmd):
        return f"ALL:{cmd}=A\r"

    @staticmethod
    def format_error(cmd):
        return f"ALL:{cmd}=N\r"

    @classmethod
    def parse(cls, raw, device):
        results = []
        raw = raw.strip()
        if not raw.startswith("K:ALL"):
            return results
        cmd = raw[5:]

        # ── PWR? — always responds (even when off), others silent when off ──
        # Captured from real hardware:
        #   PWR? when off  → ALL:PWR=002\r
        #   PWR? when on   → ALL:PWR=0\r   (single digit, not zero-padded)
        #   SRC? when off  → no response (silence)
        #   SRC? when on   → ALL:SRC=002\r
        #   VOL? when off  → no response (silence) — assumed, matches SRC behaviour
        if cmd == "PWR?":
            # Captured from real hardware:
            #   PWR? when on  → ALL:PWR=000\r  (zero-padded 3 digits)
            #   PWR? when off → ALL:PWR=002\r
            results.append((cls.format_status("PWR", device.power), None))
            return results

        # All remaining queries — silent when display is off (matches real hardware)
        if cmd == "SRC?":
            if device.power != cls.POWER_ON:
                return results   # silence — no response
            results.append((cls.format_status("SRC", device.source), None))
            return results
        if cmd == "VOL?":
            if device.power != cls.POWER_ON:
                return results   # silence — no response
            results.append((cls.format_status("VOL", str(device.volume).zfill(3)), None))
            return results

        # Power commands — always execute
        if cmd == "PON.":
            # Real hardware sends three responses after PON (captured from live display):
            #   ALL:PWR=0\r   — current power state (single digit, not zero-padded)
            #   ALL:FWV=A\r   — firmware version ACK (unsolicited)
            #   ALL:MAC=A\r   — MAC address ACK (unsolicited)
            results.append(("ALL:PWR=000\r", {"power": cls.POWER_ON}))
            results.append(("ALL:FWV=A\r", None))
            results.append(("ALL:MAC=A\r", None))
            return results
        if cmd == "POF.":
            # Real hardware behaviour (captured from live display):
            #   POF when on  → ALL:POF=A\r  and transitions to 002
            #   POF when off → ALL:POF=N\r  (nack — already off)
            if device.power != cls.POWER_ON:
                results.append((cls.format_error("POF"), None))
                return results
            results.append((cls.format_ack("POF"), {"power": cls.POWER_OFF2}))
            return results

        # Volume set: K:ALLVOL050.
        if cmd.startswith("VOL") and cmd.endswith("."):
            if device.power != cls.POWER_ON:
                return results   # silence when off — matches real hardware
            try:
                val = max(0, min(100, int(cmd[3:-1])))
                # Real hardware returns ALL:VOL=A\r (ACK), not a value echo
                results.append((cls.format_ack("VOL"), {"volume": val}))
            except ValueError:
                results.append((cls.format_error("VOL"), None))
            return results

        # Source switching: K:ALLSH2.
        if cmd.startswith("SH") and cmd.endswith("."):
            if device.power != cls.POWER_ON:
                return results   # silence when off — matches real hardware
            src_key = cmd[:-1]
            if src_key in cls.SOURCE_MAP:
                results.append((cls.format_ack(src_key),
                                {"source": cls.SOURCE_MAP[src_key]}))
            else:
                results.append((cls.format_error(src_key), None))
            return results

        # Unrecognised
        token = cmd[:3] if len(cmd) >= 3 else cmd
        results.append((cls.format_error(token), None))
        return results

    @classmethod
    def ui_buttons(cls):
        """All input source buttons per the manual — 8 inputs, no SH6."""
        return [
            ("DP 1",     "SH0"),
            ("DP 2",     "SH1"),
            ("HDMI 1",   "SH2"),
            ("HDMI 2",   "SH3"),
            ("HDMI 3",   "SH4"),
            ("HDMI 4",   "SH5"),
            ("OPS/HDMI", "SH7"),
            ("OPS/DP",   "SH8"),
        ]


class PhilipsSICPProtocol:
    """
    Philips SICP (Serial/IP Control Protocol) — binary frame protocol.

    Frame structure (verified against real hardware):
        [LEN] [MON_ID] [TYPE] [CMD] [PARAMS...] [CHECKSUM]

        LEN      = total byte count including LEN and CHECKSUM
        MON_ID   = monitor ID (must match OSD: Menu → Configuration 1 → Monitor ID)
        TYPE     = 0x00 send/read, 0x01 response from display, 0x02 write
        CMD      = command byte
        PARAMS   = command parameters
        CHECKSUM = XOR of all preceding bytes

    ACK response (e.g. after PON/POF):
        CMD=0x00, PARAM=original frame LEN, TYPE=0x01
        e.g. 06 01 01 00 06 00

    Query response (e.g. power status):
        CMD=original CMD, PARAM=value, TYPE=0x01
        e.g. 06 01 01 19 02 1D  (power query, on)
    """
    NAME         = "Philips (SICP)"
    DEFAULT_PORT = 5000
    BINARY       = True

    MONITOR_ID = 0x01   # OSD: Menu → Configuration 1 → Monitor ID

    # TYPE byte values
    TYPE_CMD      = 0x00   # read / action (sent to display)
    TYPE_RESPONSE = 0x01   # response from display
    TYPE_WRITE    = 0x02   # write (sent to display)

    POWER_ON  = 0x02
    POWER_OFF = 0x01

    SOURCE_MAP = {
        "HDMI 1": 0x05,
        "HDMI 2": 0x06,
        "DP":     0x0F,
        "VGA":    0x01,
        "DVI":    0x03,
    }
    SOURCE_LABELS = {v: k for k, v in SOURCE_MAP.items()}

    # ── Frame helpers ─────────────────────────────────────────

    @staticmethod
    def _checksum(payload: bytes) -> int:
        r = 0
        for b in payload: r ^= b
        return r

    @classmethod
    def _build_cmd(cls, cmd: int, *params: int) -> bytes:
        """Build a command frame to SEND to the display. TYPE=0x00."""
        payload = bytes([cls.MONITOR_ID, cls.TYPE_CMD, cmd] + list(params))
        length  = len(payload) + 2
        body    = bytes([length]) + payload
        return body + bytes([cls._checksum(body)])

    @classmethod
    def _build_response(cls, cmd: int, *params: int) -> bytes:
        """Build a response frame as the DISPLAY would send. TYPE=0x01."""
        payload = bytes([cls.MONITOR_ID, cls.TYPE_RESPONSE, cmd] + list(params))
        length  = len(payload) + 2
        body    = bytes([length]) + payload
        return body + bytes([cls._checksum(body)])

    @classmethod
    def _ack(cls, original_len: int) -> bytes:
        """Generic ACK — CMD=0x00, PARAM=original frame length. Verified from real hardware."""
        return cls._build_response(0x00, original_len)

    @classmethod
    def _nack(cls) -> bytes:
        """NACK — same structure as ACK but param=0x00."""
        return cls._build_response(0x00, 0x00)

    # ── Validation ────────────────────────────────────────────

    @classmethod
    def validate(cls, data: bytes):
        if len(data) < 5:
            return False, "Frame too short"
        dl = data[0]
        if len(data) < dl:
            return False, f"Incomplete: got {len(data)}, need {dl}"
        frame  = data[:dl]
        mon_id = frame[1]
        if mon_id not in (cls.MONITOR_ID, 0x00):
            return False, f"Wrong Monitor ID: got 0x{mon_id:02X}, expected 0x{cls.MONITOR_ID:02X} or 0x00"
        exp = cls._checksum(frame[:-1])
        got = frame[-1]
        if exp != got:
            return False, f"Bad checksum: expected 0x{exp:02X} got 0x{got:02X}"
        return True, "OK"

    # ── Parser ────────────────────────────────────────────────

    @classmethod
    def parse(cls, data: bytes, device) -> list:
        results = []
        ok, reason = cls.validate(data)
        if not ok:
            device.log(f"SYS: SICP frame invalid — {reason}")
            return results

        dl     = data[0]
        frame  = data[:dl]
        cmd    = frame[3]
        params = frame[4:-1]
        orig_len = dl   # used in ACK response

        # ── 0x18  Power Control ───────────────────────────────
        if cmd == 0x18:
            if not params:
                results.append((cls._nack(), None))
            elif params[0] == 0x02:   # Power ON
                results.append((cls._ack(orig_len), {"power": cls.POWER_ON}))
            elif params[0] == 0x01:   # Standby
                results.append((cls._ack(orig_len), {"power": cls.POWER_OFF}))
            else:
                results.append((cls._nack(), None))

        # ── 0x19  Power Status Query ──────────────────────────
        elif cmd == 0x19:
            results.append((cls._build_response(0x19, device.power), None))

        # ── 0xAC  Input Source ────────────────────────────────
        elif cmd == 0xAC:
            if not params:
                results.append((cls._build_response(0xAC, device.source), None))
            elif device.power == cls.POWER_ON:
                src = params[0]
                if src in cls.SOURCE_LABELS:
                    results.append((cls._ack(orig_len), {"source": src}))
                else:
                    results.append((cls._nack(), None))
            else:
                results.append((cls._nack(), None))

        # ── 0x44  Volume Query ────────────────────────────────
        elif cmd == 0x44:
            results.append((cls._build_response(0x44, device.volume), None))

        # ── 0x45  Volume Set ──────────────────────────────────
        elif cmd == 0x45:
            if not params:
                results.append((cls._nack(), None))
            elif device.power == cls.POWER_ON:
                vol = max(0, min(100, params[0]))
                results.append((cls._ack(orig_len), {"volume": vol}))
            else:
                results.append((cls._nack(), None))

        else:
            results.append((cls._nack(), None))

        return results

    # ── UI helpers ────────────────────────────────────────────

    @classmethod
    def ui_buttons(cls):
        return [
            ("HDMI 1", "HDMI 1"),
            ("HDMI 2", "HDMI 2"),
            ("DP",     "DP"),
            ("VGA",    "VGA"),
            ("DVI",    "DVI"),
        ]



class LGProtocol:
    """
    LG Commercial Display — ASCII RS232/IP protocol.
    Reference: LG RS232 Protocol (commercial displays)

    Command format sent TO display:
        <cmd1><cmd2> <set_id> <data>\r
        cmd1  = command category letter (e.g. 'k', 'm')
        cmd2  = command letter        (e.g. 'a', 'c')
        set_id= display ID, '01' for first display
        data  = value as 2-digit hex, or 'ff' to query

    Response format FROM display:
        <cmd2> <set_id> OK<data>x\r   — success
        <cmd2> <set_id> NG<data>x\r   — error/not available

    TCP port: 9761 (LG commercial displays use 9761, not 5000)

    Key commands (verified against LG commercial display spec):
        ka = Power             00=off, 01=on
        kb = Screen Mute       00=screen+audio off, 01=screen off only
        kc = Aspect Ratio      01=4:3, 02=16:9, 04=zoom, 06=set by pgm, 09=just scan
        kd = Screen Mute       00=off, 01=on
        ke = Volume Mute       00=mute, 01=unmute
        kf = Volume            00-64 hex (0-100 dec)
        kg = Contrast          00-64 hex
        kh = Brightness        00-64 hex
        kl = Balance           00-64 hex
        km = Colour            00-64 hex
        mc = IR key emulation  various key codes
        xb = Input select      00=DTV, 20=AV, 40=COMPONENT, 60=RGB, 90=HDMI1,
                               91=HDMI2, 92=HDMI3, C0=DP
    """
    NAME         = "LG Commercial"
    DEFAULT_PORT = 9761
    BINARY       = False

    POWER_ON  = "01"
    POWER_OFF = "00"

    # Input source map: UI button key -> hex data byte sent in xb command
    SOURCE_MAP = {
        "HDMI 1":     "90",
        "HDMI 2":     "91",
        "HDMI 3":     "92",
        "DisplayPort":"c0",
        "RGB/VGA":    "60",
        "Component":  "40",
        "AV":         "20",
    }

    SOURCE_LABELS = {v: k for k, v in SOURCE_MAP.items()}

    SET_ID = "01"   # matches display ID setting, 01 = first display

    # ── Formatters ────────────────────────────────────────────

    @classmethod
    def ok(cls, cmd2: str, data: str) -> str:
        """Success response: e.g. 'a 01 OK01x\r'"""
        return f"{cmd2} {cls.SET_ID} OK{data}x\r"

    @classmethod
    def ng(cls, cmd2: str, data: str = "00") -> str:
        """Error response: e.g. 'a 01 NG00x\r'"""
        return f"{cmd2} {cls.SET_ID} NG{data}x\r"

    # ── Parser ────────────────────────────────────────────────

    @classmethod
    def parse(cls, raw: str, device) -> list:
        """
        Parse an LG ASCII command.
        Returns list of (response_str | None, ui_update_dict | None).
        """
        results = []
        raw = raw.strip()

        # Expect format: "ka 01 01" or "ka 01 ff" (query)
        parts = raw.split()
        if len(parts) < 3:
            return results

        cmd   = parts[0].lower()   # e.g. "ka", "kf", "xb"
        sid   = parts[1]           # set id e.g. "01"
        data  = parts[2].lower()   # value or "ff" for query

        # Only respond to our set ID or broadcast FF
        if sid not in (cls.SET_ID, "ff"):
            return results

        cmd1 = cmd[0] if len(cmd) > 0 else ""
        cmd2 = cmd[1] if len(cmd) > 1 else ""

        is_query = (data == "ff")

        # ── ka  Power ─────────────────────────────────────────
        if cmd == "ka":
            if is_query:
                results.append((cls.ok("a", device.power), None))
            elif data == "01":
                results.append((cls.ok("a", "01"), {"power": cls.POWER_ON}))
            elif data == "00":
                results.append((cls.ok("a", "00"), {"power": cls.POWER_OFF}))
            else:
                results.append((cls.ng("a"), None))

        # ── kf  Volume ────────────────────────────────────────
        elif cmd == "kf":
            if is_query:
                val = f"{device.volume:02x}"
                results.append((cls.ok("f", val), None))
            elif device.power == cls.POWER_ON:
                try:
                    vol = max(0, min(100, int(data, 16)))
                    results.append((cls.ok("f", f"{vol:02x}"), {"volume": vol}))
                except ValueError:
                    results.append((cls.ng("f"), None))
            else:
                results.append((cls.ng("f"), None))

        # ── ke  Volume Mute ───────────────────────────────────
        elif cmd == "ke":
            if is_query:
                results.append((cls.ok("e", "00"), None))
            elif device.power == cls.POWER_ON:
                results.append((cls.ok("e", data), None))
            else:
                results.append((cls.ng("e"), None))

        # ── xb  Input source ──────────────────────────────────
        elif cmd == "xb":
            if is_query:
                results.append((cls.ok("b", device.source), None))
            elif device.power == cls.POWER_ON:
                if data in cls.SOURCE_LABELS:
                    results.append((cls.ok("b", data), {"source": data}))
                else:
                    results.append((cls.ng("b"), None))
            else:
                results.append((cls.ng("b"), None))

        # ── kc  Aspect Ratio ──────────────────────────────────
        elif cmd == "kc":
            if is_query:
                results.append((cls.ok("c", "02"), None))   # default 16:9
            elif device.power == cls.POWER_ON:
                results.append((cls.ok("c", data), None))
            else:
                results.append((cls.ng("c"), None))

        # ── kg  Contrast ──────────────────────────────────────
        elif cmd == "kg":
            if is_query:
                results.append((cls.ok("g", "64"), None))
            elif device.power == cls.POWER_ON:
                results.append((cls.ok("g", data), None))
            else:
                results.append((cls.ng("g"), None))

        # ── kh  Brightness ────────────────────────────────────
        elif cmd == "kh":
            if is_query:
                results.append((cls.ok("h", "64"), None))
            elif device.power == cls.POWER_ON:
                results.append((cls.ok("h", data), None))
            else:
                results.append((cls.ng("h"), None))

        # ── mc  IR key emulation ──────────────────────────────
        elif cmd == "mc":
            if device.power == cls.POWER_ON:
                results.append((cls.ok("c", data), None))
            else:
                results.append((cls.ng("c"), None))

        # ── Unrecognised ──────────────────────────────────────
        else:
            results.append((cls.ng(cmd2 if cmd2 else "z"), None))

        return results

    @classmethod
    def ui_buttons(cls):
        return [
            ("HDMI 1",      "HDMI 1"),
            ("HDMI 2",      "HDMI 2"),
            ("HDMI 3",      "HDMI 3"),
            ("DisplayPort", "DisplayPort"),
            ("RGB/VGA",     "RGB/VGA"),
            ("Component",   "Component"),
            ("AV",          "AV"),
        ]


class SamsungMDCProtocol:
    """
    Samsung MDC (Multiple Display Control) — binary protocol.
    Used by Samsung commercial displays (video wall, QM, QE series etc.)
    TCP port: 1515

    Command frame sent TO display:
        [0xAA] [CMD] [ID] [LEN] [DATA...] [CHECKSUM]
        0xAA   = header (always, not included in checksum)
        CMD    = command byte
        ID     = display ID (0xFE = broadcast all)
        LEN    = number of data bytes
        DATA   = command data
        CHECKSUM = sum of CMD+ID+LEN+DATA bytes, keep lower byte only

    Response frame FROM display:
        [0xAA] [0xFF] [ID] [LEN] [ACK/NAK] [CMD] [DATA...] [CHECKSUM]
        0xAA   = header
        0xFF   = response marker
        ID     = display ID
        LEN    = number of remaining bytes (ACK/NAK + CMD + DATA)
        ACK    = 0x41 ('A') = success, 0x4E ('N') = error
        CMD    = echoed command byte
        DATA   = response data
        CHECKSUM = sum of 0xFF+ID+LEN+ACK+CMD+DATA, keep lower byte only

    Key commands:
        0x11 = Power           01=on, 00=off
        0x12 = Volume          00-64 (0-100 decimal)
        0x13 = Mute            01=on, 00=off
        0x14 = Input Source    21=HDMI1, 23=HDMI2, 31=HDMI3, 33=HDMI4,
                               14=DisplayPort, 18=DVI, 0C=RGB/VGA
        0x62 = Volume Step     00=up, 01=down
        0xC1 = IR Key code     various
    """
    NAME         = "Samsung MDC"
    DEFAULT_PORT = 1515
    BINARY       = True

    DISPLAY_ID = 0xFE   # broadcast — responds to 0xFE or 0x01

    POWER_ON  = 0x01
    POWER_OFF = 0x00

    # Source map: UI label -> input byte
    SOURCE_MAP = {
        "HDMI 1":      0x21,
        "HDMI 2":      0x23,
        "HDMI 3":      0x31,
        "HDMI 4":      0x33,
        "DisplayPort": 0x14,
        "DVI":         0x18,
        "RGB/VGA":     0x0C,
    }
    SOURCE_LABELS = {v: k for k, v in SOURCE_MAP.items()}

    # Command bytes
    CMD_POWER   = 0x11
    CMD_VOLUME  = 0x12
    CMD_MUTE    = 0x13
    CMD_INPUT   = 0x14
    CMD_VOL_STEP= 0x62
    CMD_IR      = 0xC1

    # ── Checksum ──────────────────────────────────────────────

    @staticmethod
    def _checksum(data: bytes) -> int:
        """Sum of all bytes, keep lower byte. Header 0xAA excluded."""
        return sum(data) & 0xFF

    # ── Frame builders ────────────────────────────────────────

    @classmethod
    def _build_cmd(cls, cmd: int, *data: int) -> bytes:
        """Build a command frame to send TO the display."""
        body = bytes([cmd, cls.DISPLAY_ID, len(data)] + list(data))
        cs   = cls._checksum(body)
        return bytes([0xAA]) + body + bytes([cs])

    @classmethod
    def _build_ack(cls, cmd: int, *data: int) -> bytes:
        """Build an ACK response as the display would send it."""
        # [0xAA][0xFF][ID][LEN][0x41=ACK][CMD][DATA...][CS]
        inner = bytes([0x41, cmd] + list(data))
        body  = bytes([0xFF, cls.DISPLAY_ID, len(inner)]) + inner
        cs    = cls._checksum(body)
        return bytes([0xAA]) + body + bytes([cs])

    @classmethod
    def _build_nak(cls, cmd: int) -> bytes:
        """Build a NAK response."""
        inner = bytes([0x4E, cmd, 0x03])  # 0x03 = not available
        body  = bytes([0xFF, cls.DISPLAY_ID, len(inner)]) + inner
        cs    = cls._checksum(body)
        return bytes([0xAA]) + body + bytes([cs])

    # ── Validation ────────────────────────────────────────────

    @classmethod
    def validate(cls, data: bytes):
        if len(data) < 4:
            return False, "Frame too short"
        if data[0] != 0xAA:
            return False, f"Bad header: 0x{data[0]:02X}"
        cmd    = data[1]
        dev_id = data[2]
        length = data[3]
        if len(data) < 4 + length + 1:
            return False, f"Incomplete: got {len(data)}, need {4 + length + 1}"
        # Verify checksum — sum of CMD+ID+LEN+DATA
        body = data[1:4 + length]
        exp  = cls._checksum(body)
        got  = data[4 + length]
        if exp != got:
            return False, f"Bad checksum: expected 0x{exp:02X} got 0x{got:02X}"
        # Accept broadcast ID (0xFE) or specific ID (0x01)
        if dev_id not in (cls.DISPLAY_ID, 0x01, 0xFF):
            return False, f"Wrong ID: 0x{dev_id:02X}"
        return True, "OK"

    # ── Parser ────────────────────────────────────────────────

    @classmethod
    def parse(cls, data: bytes, device) -> list:
        results = []
        ok, reason = cls.validate(data)
        if not ok:
            device.log(f"SYS: Samsung MDC frame invalid — {reason}")
            return results

        cmd    = data[1]
        length = data[3]
        params = list(data[4:4 + length])
        val    = params[0] if params else None

        # ── 0x11  Power ───────────────────────────────────────
        if cmd == cls.CMD_POWER:
            if val is None:
                # Query
                results.append((cls._build_ack(cmd, device.power), None))
            elif val == cls.POWER_ON:
                results.append((cls._build_ack(cmd, cls.POWER_ON),
                                {"power": cls.POWER_ON}))
            elif val == cls.POWER_OFF:
                results.append((cls._build_ack(cmd, cls.POWER_OFF),
                                {"power": cls.POWER_OFF}))
            else:
                results.append((cls._build_nak(cmd), None))

        # ── 0x12  Volume set ──────────────────────────────────
        elif cmd == cls.CMD_VOLUME:
            if val is None:
                results.append((cls._build_ack(cmd, device.volume), None))
            elif device.power == cls.POWER_ON:
                vol = max(0, min(100, val))
                results.append((cls._build_ack(cmd, vol), {"volume": vol}))
            else:
                results.append((cls._build_nak(cmd), None))

        # ── 0x13  Mute ────────────────────────────────────────
        elif cmd == cls.CMD_MUTE:
            if val is None:
                results.append((cls._build_ack(cmd, 0x00), None))
            elif device.power == cls.POWER_ON:
                results.append((cls._build_ack(cmd, val), None))
            else:
                results.append((cls._build_nak(cmd), None))

        # ── 0x14  Input source ────────────────────────────────
        elif cmd == cls.CMD_INPUT:
            if val is None:
                results.append((cls._build_ack(cmd, device.source), None))
            elif device.power == cls.POWER_ON:
                if val in cls.SOURCE_LABELS:
                    results.append((cls._build_ack(cmd, val),
                                    {"source": val}))
                else:
                    results.append((cls._build_nak(cmd), None))
            else:
                results.append((cls._build_nak(cmd), None))

        # ── 0x62  Volume step up/down ─────────────────────────
        elif cmd == cls.CMD_VOL_STEP:
            if device.power == cls.POWER_ON:
                if val == 0x00:   # up
                    vol = min(100, device.volume + 1)
                    results.append((cls._build_ack(cmd, val),
                                    {"volume": vol}))
                elif val == 0x01:  # down
                    vol = max(0, device.volume - 1)
                    results.append((cls._build_ack(cmd, val),
                                    {"volume": vol}))
                else:
                    results.append((cls._build_nak(cmd), None))
            else:
                results.append((cls._build_nak(cmd), None))

        # ── 0xC1  IR key ──────────────────────────────────────
        elif cmd == cls.CMD_IR:
            if device.power == cls.POWER_ON:
                results.append((cls._build_ack(cmd, val if val else 0), None))
            else:
                results.append((cls._build_nak(cmd), None))

        else:
            results.append((cls._build_nak(cmd), None))

        return results

    @classmethod
    def ui_buttons(cls):
        return [
            ("HDMI 1",      "HDMI 1"),
            ("HDMI 2",      "HDMI 2"),
            ("HDMI 3",      "HDMI 3"),
            ("HDMI 4",      "HDMI 4"),
            ("DisplayPort", "DisplayPort"),
            ("DVI",         "DVI"),
            ("RGB/VGA",     "RGB/VGA"),
        ]


class NECProtocol:
    """
    NEC MultiSync Professional Display — External Control Protocol.
    Reference: NEC LCD Monitor External Control Rev.1.1 (G2E)

    TCP port: 7142 (fixed per spec)

    Frame structure:
        [SOH][0x30][DEST][SRC][TYPE][LEN_HI][LEN_LO][STX][MSG...][ETX][BCC][CR]

        SOH  = 0x01
        0x30 = reserved, always 0x30
        DEST = monitor ID encoded: ID 1 = 0x41 ('A'), ALL = 0x2A ('*')
        SRC  = always 0x30 ('0') from controller
        TYPE = message type:
               0x41 ('A') = Command
               0x42 ('B') = Command reply
               0x43 ('C') = Get parameter
               0x44 ('D') = Get parameter reply
               0x45 ('E') = Set parameter
               0x46 ('F') = Set parameter reply
        LEN  = length of [STX..ETX] encoded as 2 ASCII hex chars
        STX  = 0x02
        MSG  = message payload (ASCII-encoded hex values)
        ETX  = 0x03
        BCC  = XOR of all bytes from Reserved(0x30) to ETX inclusive
        CR   = 0x0D

    All multi-byte values in the message are ASCII-encoded hex:
        e.g. byte 0x1A is encoded as ASCII '1','A' (0x31, 0x41)

    Key OP codes (page 00, values ASCII-encoded):
        0x00D6 = Power (page 02, op D6)  — 0001=on, 0004=off
        0x0060 = Input select (page 00, op 60)
        0x0062 = Volume       (page 00, op 62)
        0x008D = Mute         (page 00, op 8D)

    Input codes for op 0x0060:
        0x0001 = VGA/RGB
        0x0003 = DVI
        0x0004 = HDMI 1
        0x0100 = DP
        0x0011 = HDMI 2 (some models)
        0x0009 = Option/OPS

    Special commands (TYPE = 'A'):
        Power ON:  message = C 2 0 3 D 6 0 0 0 1  (op-code C203D6, value 0001)
        Power OFF: message = C 2 0 3 D 6 0 0 0 4  (op-code C203D6, value 0004)
    """
    NAME         = "NEC MultiSync"
    DEFAULT_PORT = 7142
    BINARY       = False   # uses ASCII encoding over TCP

    MONITOR_ID = 1         # display ID — dest address = ID + 0x40

    POWER_ON  = "on"
    POWER_OFF = "off"

    # Input source map: UI label -> OP value (16-bit int)
    SOURCE_MAP = {
        "HDMI 1":      0x0004,
        "HDMI 2":      0x0011,
        "DisplayPort": 0x0100,
        "DVI":         0x0003,
        "VGA/RGB":     0x0001,
        "OPS/Option":  0x0009,
    }
    SOURCE_LABELS = {v: k for k, v in SOURCE_MAP.items()}

    # ── Encoding helpers ──────────────────────────────────────

    @classmethod
    def _dest(cls) -> int:
        """Monitor ID 1 = 0x41, ID 2 = 0x42, ALL = 0x2A."""
        if cls.MONITOR_ID == 0:
            return 0x2A   # broadcast '*'
        return 0x40 + cls.MONITOR_ID  # ID 1 = 0x41 'A'

    @staticmethod
    def _enc(val: int, nibbles: int = 2) -> bytes:
        """Encode integer as ASCII hex nibbles. e.g. 0x1A, 2 -> b'1A'"""
        fmt = f"{{:0{nibbles}X}}"
        return fmt.format(val).encode('ascii')

    @staticmethod
    def _bcc(data: bytes) -> int:
        """XOR of all bytes (Reserved through ETX)."""
        result = 0
        for b in data:
            result ^= b
        return result

    @classmethod
    def _build(cls, msg_type: int, message: bytes) -> bytes:
        """
        Build a complete NEC external control frame.
        msg_type: e.g. 0x41 (Command), 0x43 (Get), 0x45 (Set)
        message:  raw bytes for the message payload (without STX/ETX)
        """
        stx     = bytes([0x02])
        etx     = bytes([0x03])
        msg     = stx + message + etx
        msg_len = cls._enc(len(msg), 2)  # length as 2 ASCII hex chars

        dest    = cls._dest()
        src     = 0x30   # controller always '0'

        # Header body (for BCC): reserved + dest + src + type + len
        hdr_body = bytes([0x30, dest, src, msg_type]) + msg_len
        full_msg = hdr_body + msg
        bcc      = cls._bcc(full_msg)

        return bytes([0x01]) + full_msg + bytes([bcc, 0x0D])

    @classmethod
    def _set_param(cls, op_page: int, op_code: int, value: int) -> bytes:
        """Build a Set Parameter frame (TYPE=E)."""
        msg = (cls._enc(op_page, 2) + cls._enc(op_code, 2) +
               cls._enc(value >> 8, 2) + cls._enc(value & 0xFF, 2))
        return cls._build(0x45, msg)

    @classmethod
    def _get_param(cls, op_page: int, op_code: int) -> bytes:
        """Build a Get Parameter frame (TYPE=C)."""
        msg = cls._enc(op_page, 2) + cls._enc(op_code, 2)
        return cls._build(0x43, msg)

    @classmethod
    def _command(cls, message: bytes) -> bytes:
        """Build a Command frame (TYPE=A)."""
        return cls._build(0x41, message)

    @classmethod
    def _reply(cls, msg_type: int, message: bytes) -> bytes:
        """Build a reply frame — dest/src swapped for response."""
        stx      = bytes([0x02])
        etx      = bytes([0x03])
        msg      = stx + message + etx
        msg_len  = cls._enc(len(msg), 2)
        # On reply: dest=0x30, src=monitor ID
        hdr_body = bytes([0x30, 0x30, cls._dest(), msg_type]) + msg_len
        full_msg = hdr_body + msg
        bcc      = cls._bcc(full_msg)
        return bytes([0x01]) + full_msg + bytes([bcc, 0x0D])

    @classmethod
    def _get_reply(cls, op_page: int, op_code: int,
                   max_val: int, cur_val: int) -> bytes:
        """Build a Get Parameter reply (TYPE=D)."""
        msg = (b'00' +                           # result: no error
               cls._enc(op_page, 2) +
               cls._enc(op_code, 2) +
               b'00' +                           # type: set parameter
               cls._enc(max_val, 4) +
               cls._enc(cur_val, 4))
        return cls._reply(0x44, msg)

    @classmethod
    def _set_reply(cls, op_page: int, op_code: int,
                   max_val: int, set_val: int) -> bytes:
        """Build a Set Parameter reply (TYPE=F)."""
        msg = (b'00' +
               cls._enc(op_page, 2) +
               cls._enc(op_code, 2) +
               b'00' +
               cls._enc(max_val, 4) +
               cls._enc(set_val, 4))
        return cls._reply(0x46, msg)

    @classmethod
    def _cmd_reply(cls, message: bytes) -> bytes:
        """Build a Command reply (TYPE=B)."""
        return cls._reply(0x42, message)

    # ── Frame validation ──────────────────────────────────────

    @classmethod
    def validate(cls, raw: str) -> tuple:
        """Validate an incoming NEC frame."""
        data = raw.encode('latin-1') if isinstance(raw, str) else raw
        if len(data) < 9:
            return False, "Too short"
        if data[0] != 0x01:
            return False, f"Bad SOH: 0x{data[0]:02X}"
        if data[-1] != 0x0D:
            return False, "Missing CR"
        # BCC = XOR of bytes 1..-2 (reserved through ETX, excluding SOH and BCC/CR)
        bcc_data = data[1:-2]
        exp = cls._bcc(bcc_data)
        got = data[-2]
        if exp != got:
            return False, f"Bad BCC: expected 0x{exp:02X} got 0x{got:02X}"
        return True, "OK"

    # ── Parser ────────────────────────────────────────────────

    @classmethod
    def parse(cls, raw: str, device) -> list:
        results = []
        if isinstance(raw, bytes):
            raw = raw.decode('latin-1')
        raw = raw.strip()

        ok, reason = cls.validate(raw)
        if not ok:
            device.log(f"SYS: NEC frame invalid — {reason}")
            return results

        data     = raw.encode('latin-1')
        msg_type = data[4]   # TYPE byte
        # Extract message content between STX and ETX
        try:
            stx_pos = data.index(0x02)
            etx_pos = data.index(0x03, stx_pos)
            msg = data[stx_pos+1:etx_pos].decode('ascii')
        except (ValueError, UnicodeDecodeError):
            return results

        # ── TYPE=C  Get Parameter ─────────────────────────────
        if msg_type == 0x43:
            if len(msg) < 4:
                return results
            op_page = int(msg[0:2], 16)
            op_code = int(msg[2:4], 16)

            # Power status: page=02, op=D6 (or page=01, op=D6)
            if op_code == 0xD6:
                pwr_val = 0x0001 if device.power == cls.POWER_ON else 0x0004
                results.append((
                    cls._get_reply(op_page, op_code, 0x0004, pwr_val)
                    .decode('latin-1'), None))

            # Volume: page=00, op=62
            elif op_page == 0x00 and op_code == 0x62:
                results.append((
                    cls._get_reply(0x00, 0x62, 0x0064, device.volume)
                    .decode('latin-1'), None))

            # Input: page=00, op=60
            elif op_page == 0x00 and op_code == 0x60:
                src_val = device.source if isinstance(device.source, int) else 0x0004
                results.append((
                    cls._get_reply(0x00, 0x60, 0x0100, src_val)
                    .decode('latin-1'), None))

            # Mute: page=00, op=8D
            elif op_page == 0x00 and op_code == 0x8D:
                results.append((
                    cls._get_reply(0x00, 0x8D, 0x0002, 0x0002)
                    .decode('latin-1'), None))

        # ── TYPE=E  Set Parameter ─────────────────────────────
        elif msg_type == 0x45:
            if len(msg) < 8:
                return results
            op_page  = int(msg[0:2], 16)
            op_code  = int(msg[2:4], 16)
            set_val  = int(msg[4:8], 16)

            # Volume set
            if op_page == 0x00 and op_code == 0x62:
                if device.power == cls.POWER_ON:
                    vol = max(0, min(100, set_val))
                    results.append((
                        cls._set_reply(0x00, 0x62, 0x0064, vol)
                        .decode('latin-1'),
                        {"volume": vol}))
                else:
                    results.append((
                        cls._set_reply(0x00, 0x62, 0x0064, set_val)
                        .decode('latin-1'), None))

            # Input set
            elif op_page == 0x00 and op_code == 0x60:
                if device.power == cls.POWER_ON and set_val in cls.SOURCE_LABELS:
                    results.append((
                        cls._set_reply(0x00, 0x60, 0x0100, set_val)
                        .decode('latin-1'),
                        {"source": set_val}))
                else:
                    results.append((
                        cls._set_reply(0x00, 0x60, 0x0100, set_val)
                        .decode('latin-1'), None))

            # Mute set
            elif op_page == 0x00 and op_code == 0x8D:
                results.append((
                    cls._set_reply(0x00, 0x8D, 0x0002, set_val)
                    .decode('latin-1'), None))

        # ── TYPE=A  Command ───────────────────────────────────
        elif msg_type == 0x41:
            # Power commands use special command format
            # Power ON:  message contains C203D60001
            # Power OFF: message contains C203D60004
            if 'C203D6' in msg.upper() or 'D6' in msg.upper():
                if '0001' in msg:
                    resp = cls._cmd_reply(b'C203D60001').decode('latin-1')
                    results.append((resp, {"power": cls.POWER_ON}))
                elif '0004' in msg:
                    resp = cls._cmd_reply(b'C203D60004').decode('latin-1')
                    results.append((resp, {"power": cls.POWER_OFF}))

        return results

    @classmethod
    def ui_buttons(cls):
        return [
            ("HDMI 1",      "HDMI 1"),
            ("HDMI 2",      "HDMI 2"),
            ("DisplayPort", "DisplayPort"),
            ("DVI",         "DVI"),
            ("VGA/RGB",     "VGA/RGB"),
            ("OPS/Option",  "OPS/Option"),
        ]

PROTOCOL_MAP = {
    ChristieProtocol.NAME:      ChristieProtocol,
    PhilipsSICPProtocol.NAME:   PhilipsSICPProtocol,
    LGProtocol.NAME:            LGProtocol,
    SamsungMDCProtocol.NAME:    SamsungMDCProtocol,
    NECProtocol.NAME:           NECProtocol,
}


# ─────────────────────────────────────────────────────────────
# 2. DEVICE INSTANCE
# ─────────────────────────────────────────────────────────────

class DisplayInstance:
    def __init__(self, config, log_callback, ui_update_callback):
        self.name      = config["name"]
        self.ip        = config["ip"]
        self.port      = int(config["port"])
        self.proto     = PROTOCOL_MAP[config["type"]]
        # Use POWER_OFF2 for Christie (matches real hardware default of 002)
        # Fall back to POWER_OFF for protocols that don't have POWER_OFF2
        self.power     = getattr(self.proto, 'POWER_OFF2', self.proto.POWER_OFF)
        self.source    = list(self.proto.SOURCE_MAP.values())[0]
        self.volume    = 50
        self.is_online = True
        self._log      = log_callback
        self._ui_upd   = ui_update_callback
        self.clients: list[asyncio.StreamWriter] = []
        self._server   = None

    def log(self, msg):
        self._log(msg)

    def _apply_update(self, update: dict):
        if "power"  in update: self.power  = update["power"]
        if "source" in update: self.source = update["source"]
        if "volume" in update: self.volume = update["volume"]
        self._ui_upd()

    def _broadcast(self, response):
        if isinstance(response, str):
            response = response.encode()
        dead = []
        for w in self.clients:
            try:
                w.write(response)
            except Exception:
                dead.append(w)
        for w in dead:
            self.clients.remove(w)

    def ui_set_power(self, on: bool):
        if not self.is_online:
            self.log("SIM: Ignored — network offline")
            return
        if on:
            self.power = self.proto.POWER_ON
        else:
            self.power = getattr(self.proto, 'POWER_OFF2', self.proto.POWER_OFF)
        self._ui_upd()
        # No broadcast — real hardware is silent when changed via remote/front panel.
        # Crestron must poll PWR? to detect the change.
        self.log(f"SIM: Power → {'ON' if on else 'OFF'} (silent — poll PWR? to detect)")

    def ui_set_source(self, key: str):
        if not self.is_online:
            self.log("SIM: Ignored — network offline")
            return
        mapped = self.proto.SOURCE_MAP.get(key, key)
        self.source = mapped
        self._ui_upd()
        # No broadcast — real hardware is silent when changed via remote/front panel.
        # Crestron must poll SRC? to detect the change.
        self.log(f"SIM: Source → {key} (code={mapped!r}, silent — poll SRC? to detect)")

    def ui_set_volume(self, vol: int):
        if not self.is_online:
            return
        self.volume = vol
        self._ui_upd()
        # No broadcast — real hardware is silent when changed via remote/front panel.
        # Crestron must poll VOL? to detect the change.

    async def handle_client(self, reader: asyncio.StreamReader,
                            writer: asyncio.StreamWriter):
        if not self.is_online:
            writer.close()
            return
        is_binary = getattr(self.proto, "BINARY", False)
        peer = writer.get_extra_info("peername")
        self.clients.append(writer)
        self.log(f"SYS: Connected: {peer}")
        try:
            while True:
                data = await reader.read(1024)
                if not data or not self.is_online:
                    break
                if is_binary:
                    self.log(f"IN:  {data.hex(' ').upper()}")
                    results = self.proto.parse(data, self)
                    for response, update in results:
                        if update:
                            self._apply_update(update)
                        if response:
                            self.log(f"OUT: {response.hex(' ').upper()}")
                            writer.write(response)
                else:
                    # NEC uses latin-1 (has binary control bytes SOH/STX/ETX)
                    # All other ASCII protocols work fine with latin-1 too
                    raw = data.decode('latin-1').strip()
                    if not raw:
                        continue
                    self.log(f"IN:  {repr(raw)}")
                    results = self.proto.parse(raw, self)
                    for response, update in results:
                        if update:
                            self._apply_update(update)
                        if response:
                            self.log(f"OUT: {repr(response)}")
                            if isinstance(response, bytes):
                                writer.write(response)
                            else:
                                writer.write(response.encode('latin-1'))
                try:
                    await writer.drain()
                except (ConnectionResetError, BrokenPipeError):
                    break   # client disconnected cleanly
                except Exception as drain_err:
                    self.log(f"SYS: Drain error: {drain_err}")
                    break
        except asyncio.IncompleteReadError:
            pass
        except Exception as e:
            self.log(f"SYS: Error: {e}")
        finally:
            self.log(f"SYS: Disconnected: {peer}")
            writer.close()
            if writer in self.clients:
                self.clients.remove(writer)

    def drop_all_clients(self):
        for w in self.clients:
            try: w.close()
            except Exception: pass
        self.clients.clear()


# ─────────────────────────────────────────────────────────────
# 3. CONTROL PANEL  (one per device)
# ─────────────────────────────────────────────────────────────

def _set_bg(widget, color):
    try: widget.config(bg=color)
    except tk.TclError: pass
    for child in widget.winfo_children():
        _set_bg(child, color)


def _mk_btn(parent, text, cmd, bg=BTN, fg=TEXT, **kw):
    # Merge defaults so callers can override font/padx/pady via **kw
    props = dict(font=("Consolas", 9), padx=8, pady=4)
    props.update(kw)
    b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                  activebackground=BTN_HV, activeforeground=TEXT,
                  relief="flat", bd=0, cursor="hand2", **props)
    orig_bg = bg
    b.bind("<Enter>", lambda e: b.config(bg=BTN_HV))
    b.bind("<Leave>", lambda e: b.config(bg=orig_bg))
    return b


class ControlPanel(tk.Frame):
    def __init__(self, parent, instance: DisplayInstance):
        super().__init__(parent, bg=DARK)
        self.instance = instance
        self._src_buttons: dict[str, tk.Button] = {}
        self._build()

    def _section(self, parent, title):
        tk.Label(parent, text=title, bg=DARK, fg=DIM,
                 font=("Consolas", 7, "bold")).pack(anchor="w", pady=(10, 3))

    def _build(self):
        inst  = self.instance
        proto = inst.proto

        # ── Top bar ───────────────────────────────────────────
        top = tk.Frame(self, bg=PANEL, pady=6, padx=12)
        top.pack(fill="x")

        tk.Label(top, text=f"● {inst.name}", bg=PANEL, fg=ACCENT,
                 font=("Consolas", 11, "bold")).pack(side="left")
        tk.Label(top, text=f"  {proto.NAME}  •  {inst.ip}:{inst.port}",
                 bg=PANEL, fg=DIM, font=("Consolas", 9)).pack(side="left")

        self.net_btn = tk.Button(
            top, text="NETWORK: ONLINE", bg=GREEN, fg="white",
            font=("Consolas", 8, "bold"), relief="flat", padx=8,
            cursor="hand2", command=self._toggle_net)
        self.net_btn.pack(side="right", padx=4)

        self.pwr_label = tk.Label(top, text="STANDBY", bg=PANEL, fg=RED,
                                   font=("Consolas", 10, "bold"))
        self.pwr_label.pack(side="right", padx=12)

        # ── Scrollable body ───────────────────────────────────
        canvas = tk.Canvas(self, bg=DARK, highlightthickness=0)
        sb     = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        body = tk.Frame(canvas, bg=DARK, padx=16, pady=10)
        body_id = canvas.create_window((0, 0), window=body, anchor="nw")

        body.bind("<Configure>",
                  lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(body_id, width=e.width))
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(
                            int(-1 * (e.delta / 120)), "units"))

        # ── POWER ─────────────────────────────────────────────
        self._section(body, "POWER")
        pf = tk.Frame(body, bg=DARK)
        pf.pack(fill="x", pady=(0, 4))

        _mk_btn(pf, "  ▶  POWER ON",
                lambda: inst.ui_set_power(True),
                bg="#1a3a1a", fg=GREEN,
                font=("Consolas", 9, "bold")).pack(side="left", padx=(0, 6))
        _mk_btn(pf, "  ■  STANDBY",
                lambda: inst.ui_set_power(False),
                bg="#3a1a1a", fg=RED,
                font=("Consolas", 9, "bold")).pack(side="left")

        # ── INPUT SOURCE ──────────────────────────────────────
        self._section(body, "INPUT SOURCE")
        sf = tk.Frame(body, bg=DARK)
        sf.pack(fill="x", pady=(0, 4))

        COLS = 4
        for idx, (label, key) in enumerate(proto.ui_buttons()):
            r, c = divmod(idx, COLS)
            b = tk.Button(
                sf, text=label, width=10,
                command=lambda k=key: self._set_source(k),
                bg=BTN, fg=TEXT,
                activebackground=BTN_HV, activeforeground=TEXT,
                relief="flat", bd=0, cursor="hand2",
                font=("Consolas", 9), padx=4, pady=5)
            b.grid(row=r, column=c, padx=3, pady=3, sticky="ew")
            b.bind("<Enter>", lambda e, btn=b: btn.config(bg=BTN_HV))
            b.bind("<Leave>", lambda e, btn=b: btn.config(
                bg=ACCENT if btn == self._src_buttons.get(
                    self._active_src_key()) else BTN))
            self._src_buttons[key] = b

        for c in range(COLS):
            sf.grid_columnconfigure(c, weight=1)

        # ── VOLUME ────────────────────────────────────────────
        self._section(body, "VOLUME")
        vf = tk.Frame(body, bg=DARK)
        vf.pack(fill="x", pady=(0, 4))

        self.vol_val = tk.Label(vf, text=f"{inst.volume:03d}",
                                bg=DARK, fg=ACCENT,
                                font=("Consolas", 11, "bold"), width=4)
        self.vol_val.pack(side="right")
        self.vol_slider = tk.Scale(
            vf, from_=0, to=100, orient="horizontal",
            bg=DARK, fg=TEXT, troughcolor=BORDER,
            highlightthickness=0, showvalue=False,
            command=self._on_vol)
        self.vol_slider.set(inst.volume)
        self.vol_slider.pack(fill="x", expand=True)

        # ── TCP LOG ───────────────────────────────────────────
        log_hdr = tk.Frame(body, bg=DARK)
        log_hdr.pack(fill="x", pady=(10, 2))
        tk.Label(log_hdr, text="TCP LOG", bg=DARK, fg=DIM,
                 font=("Consolas", 7, "bold")).pack(side="left")
        _mk_btn(log_hdr, "CLEAR", lambda: self.log_box.delete("1.0", tk.END),
                font=("Consolas", 7), padx=4, pady=1).pack(side="right")

        self.log_box = scrolledtext.ScrolledText(
            body, height=12, bg="#0d0d0d", fg="#00FF41",
            font=("Consolas", 8), relief="flat",
            insertbackground=ACCENT)
        self.log_box.pack(fill="both", expand=True)
        self.log_box.tag_config("in",  foreground="#00FF41")
        self.log_box.tag_config("out", foreground=ACCENT)
        self.log_box.tag_config("sys", foreground=AMBER)
        self.log_box.tag_config("sim", foreground="#9b59b6")

    def _active_src_key(self):
        """Return the source button key matching current device source."""
        proto = self.instance.proto
        for key in self._src_buttons:
            if proto.SOURCE_MAP.get(key) == self.instance.source:
                return key
        return None

    def _set_source(self, key: str):
        for k, b in self._src_buttons.items():
            b.config(bg=ACCENT if k == key else BTN,
                     fg="white" if k == key else TEXT)
        self.instance.ui_set_source(key)

    def _on_vol(self, v):
        val = int(v)
        self.instance.ui_set_volume(val)
        self.vol_val.config(text=f"{val:03d}")

    def _toggle_net(self):
        inst = self.instance
        inst.is_online = not inst.is_online
        if inst.is_online:
            self.net_btn.config(text="NETWORK: ONLINE",  bg=GREEN)
            inst.log("SYS: Network enabled.")
        else:
            self.net_btn.config(text="NETWORK: OFFLINE", bg=RED)
            inst.log("SYS: Network disabled — connections dropped.")
            inst.drop_all_clients()

    def add_log(self, msg: str):
        tag = "sys"
        if   msg.startswith("IN:"):  tag = "in"
        elif msg.startswith("OUT:"): tag = "out"
        elif msg.startswith("SIM:"): tag = "sim"
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.insert(tk.END, f"[{ts}] {msg}\n", tag)
        self.log_box.see(tk.END)

    def refresh_ui(self):
        inst  = self.instance
        proto = inst.proto
        is_on = (inst.power == proto.POWER_ON)   # 001 and 002 both count as off
        self.pwr_label.config(text="POWERED ON" if is_on else "STANDBY",
                               fg=GREEN if is_on else RED)
        self.vol_slider.set(inst.volume)
        self.vol_val.config(text=f"{inst.volume:03d}")
        # Highlight active source
        active_key = self._active_src_key()
        for k, b in self._src_buttons.items():
            b.config(bg=ACCENT if k == active_key else BTN,
                     fg="white" if k == active_key else TEXT)


# ─────────────────────────────────────────────────────────────
# 4. ADD DISPLAY DIALOG  (modal)
# ─────────────────────────────────────────────────────────────

class AddDisplayDialog(tk.Toplevel):
    def __init__(self, parent, existing_devices: list, next_index: int):
        super().__init__(parent)
        self.title("Add Display")
        self.configure(bg=DARK)
        self.resizable(False, False)
        self.grab_set()
        self.result = None
        self._existing = existing_devices
        self._build(next_index)
        self.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width()  - self.winfo_width())  // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{px}+{py}")
        self.wait_window()

    def _build(self, idx):
        pad = dict(padx=14, pady=6)

        tk.Label(self, text="ADD DISPLAY", bg=DARK, fg=ACCENT,
                 font=("Consolas", 13, "bold")).grid(
                     row=0, columnspan=2, pady=(18, 4))
        tk.Label(self, text="Configure a new emulated device instance",
                 bg=DARK, fg=DIM, font=("Consolas", 9)).grid(
                     row=1, columnspan=2, pady=(0, 16))

        self._entries = {}
        fields = [
            ("Device Name", "name", f"Display_{idx}"),
            ("IP Address",  "ip",   "0.0.0.0"),
            ("TCP Port",    "port", "5000"),
        ]
        for r, (label, key, default) in enumerate(fields, start=2):
            tk.Label(self, text=label, bg=DARK, fg=TEXT,
                     font=("Consolas", 9), anchor="w").grid(
                         row=r, column=0, sticky="w", **pad)
            e = tk.Entry(self, width=26, bg=PANEL, fg=TEXT,
                         insertbackground=ACCENT, relief="flat",
                         font=("Consolas", 9))
            e.insert(0, default)
            e.grid(row=r, column=1, **pad)
            self._entries[key] = e

        tk.Label(self, text="Protocol", bg=DARK, fg=TEXT,
                 font=("Consolas", 9), anchor="w").grid(
                     row=5, column=0, sticky="w", **pad)
        self._proto_var = tk.StringVar(value=ChristieProtocol.NAME)
        proto_cb = ttk.Combobox(self, textvariable=self._proto_var,
                                values=list(PROTOCOL_MAP.keys()),
                                width=24, state="readonly",
                                font=("Consolas", 9))
        proto_cb.grid(row=5, column=1, **pad)
        proto_cb.bind("<<ComboboxSelected>>", self._on_proto)

        # Buttons row
        bf = tk.Frame(self, bg=DARK)
        bf.grid(row=6, columnspan=2, pady=18)
        tk.Button(bf, text="CANCEL", command=self.destroy,
                  bg=BORDER, fg=DIM, font=("Consolas", 9),
                  relief="flat", padx=14, pady=6,
                  cursor="hand2").pack(side="left", padx=6)
        tk.Button(bf, text="▶  LAUNCH", command=self._submit,
                  bg=ACCENT, fg="white", font=("Consolas", 9, "bold"),
                  relief="flat", padx=18, pady=6,
                  cursor="hand2").pack(side="left", padx=6)

        self._status = tk.Label(self, text="", bg=DARK, fg=RED,
                                font=("Consolas", 8))
        self._status.grid(row=7, columnspan=2, pady=(0, 10))

    def _on_proto(self, *_):
        proto = PROTOCOL_MAP[self._proto_var.get()]
        self._entries["port"].delete(0, tk.END)
        self._entries["port"].insert(0, str(proto.DEFAULT_PORT))

    def _submit(self):
        name  = self._entries["name"].get().strip() or f"Display_{len(self._existing)+1}"
        ip    = self._entries["ip"].get().strip()
        port  = self._entries["port"].get().strip()
        ptype = self._proto_var.get()

        if not ip:
            self._status.config(text="IP address is required.")
            return
        try:
            port_int = int(port)
            if not (1 <= port_int <= 65535):
                raise ValueError
        except ValueError:
            self._status.config(text="Port must be an integer 1–65535.")
            return
        for dev in self._existing:
            if dev.ip == ip and dev.port == port_int:
                self._status.config(
                    text=f"Port {port} on {ip} already used by '{dev.name}'.")
                return

        self.result = {"name": name, "ip": ip, "port": port, "type": ptype}
        self.destroy()


# ─────────────────────────────────────────────────────────────
# 5. DEVICE SIDEBAR
# ─────────────────────────────────────────────────────────────

class DeviceSidebar(tk.Frame):
    """Left panel — lists all devices, lets you switch between them."""

    def __init__(self, parent, on_add, on_select):
        super().__init__(parent, bg=PANEL, width=210)
        self.pack_propagate(False)
        self._on_add    = on_add
        self._on_select = on_select
        self._build_header()
        self._list = tk.Frame(self, bg=PANEL)
        self._list.pack(fill="both", expand=True)

    def _build_header(self):
        hdr = tk.Frame(self, bg="#111111", pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text="DISPLAYS", bg="#111111", fg=ACCENT,
                 font=("Consolas", 10, "bold")).pack(side="left", padx=10)
        tk.Button(hdr, text=" + ", command=self._on_add,
                  bg=ACCENT, fg="white", font=("Consolas", 10, "bold"),
                  relief="flat", cursor="hand2", padx=6).pack(
                      side="right", padx=6)

    def refresh(self, devices: list, active_idx: int = -1):
        for w in self._list.winfo_children():
            w.destroy()

        if not devices:
            tk.Label(self._list,
                     text="No displays.\nClick  +  to add one.",
                     bg=PANEL, fg=DIM, font=("Consolas", 8),
                     justify="center").pack(pady=24)
        else:
            for i, dev in enumerate(devices):
                self._make_row(i, dev, selected=(i == active_idx))

            tk.Frame(self._list, bg=BORDER, height=1).pack(
                fill="x", pady=6, padx=8)
            tk.Button(self._list, text="＋  Add Display",
                      command=self._on_add,
                      bg=PANEL, fg=DIM, font=("Consolas", 8),
                      relief="flat", cursor="hand2", pady=5).pack(
                          fill="x", padx=10)

    def _make_row(self, idx: int, dev: DisplayInstance, selected: bool):
        is_on  = (dev.power == dev.proto.POWER_ON)
        row_bg = BORDER if selected else PANEL
        dot_fg = GREEN if is_on else DIM

        row = tk.Frame(self._list, bg=row_bg, cursor="hand2")
        row.pack(fill="x", padx=0, pady=1)

        # Online/power dot
        tk.Label(row, text="●", bg=row_bg, fg=dot_fg,
                 font=("Consolas", 9)).pack(side="left", padx=(8, 3), pady=8)

        # Text info
        inf = tk.Frame(row, bg=row_bg)
        inf.pack(side="left", fill="x", expand=True, pady=5)
        tk.Label(inf, text=dev.name, bg=row_bg, fg=TEXT,
                 font=("Consolas", 9, "bold"), anchor="w").pack(fill="x")
        tk.Label(inf, text=dev.proto.NAME, bg=row_bg, fg=DIM,
                 font=("Consolas", 7), anchor="w").pack(fill="x")
        tk.Label(inf, text=f"{dev.ip}:{dev.port}", bg=row_bg, fg=DIM,
                 font=("Consolas", 7), anchor="w").pack(fill="x")

        # Protocol badge colour strip
        badge_col = ACCENT if "Christie" in dev.proto.NAME else "#9b59b6"
        tk.Frame(row, bg=badge_col, width=3).pack(side="right", fill="y")

        # Click anywhere on row to select
        cb = lambda e, n=idx: self._on_select(n)
        for w in [row, inf] + list(inf.winfo_children()):
            w.bind("<Button-1>", cb)

        # Hover highlight
        def _enter(e, f=row, orig=row_bg):
            _set_bg(f, "#2e2e2e")
        def _leave(e, f=row, orig=row_bg):
            _set_bg(f, orig)
        row.bind("<Enter>", _enter)
        row.bind("<Leave>", _leave)


# ─────────────────────────────────────────────────────────────
# 6. MAIN APPLICATION
# ─────────────────────────────────────────────────────────────

class DisplayApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("AV Display Emulator")
        self.root.geometry("1080x700")
        self.root.configure(bg=DARK)
        self.root.minsize(820, 540)

        self.devices:     list[DisplayInstance] = []
        self.panels:      list[ControlPanel]    = []
        self.loops:       list[asyncio.AbstractEventLoop] = []
        self._active_idx  = -1
        self._current_panel: ControlPanel | None = None

        self._build_ui()

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")

        outer = tk.Frame(self.root, bg=DARK)
        outer.pack(fill="both", expand=True)

        self.sidebar = DeviceSidebar(outer,
                                     on_add=self._open_add_dialog,
                                     on_select=self._select_device)
        self.sidebar.pack(side="left", fill="y")
        tk.Frame(outer, bg=BORDER, width=1).pack(side="left", fill="y")

        self._main = tk.Frame(outer, bg=DARK)
        self._main.pack(side="left", fill="both", expand=True)

        self._show_welcome()

    def _show_welcome(self):
        for w in self._main.winfo_children():
            w.pack_forget()

        f = tk.Frame(self._main, bg=DARK)
        f.place(relx=0.5, rely=0.44, anchor="center")

        tk.Label(f, text="AV DISPLAY EMULATOR", bg=DARK, fg=ACCENT,
                 font=("Consolas", 19, "bold")).pack(pady=(0, 6))
        tk.Label(f,
                 text="Christie Secure II  (ASCII)   •   Philips SICP  (Binary)",
                 bg=DARK, fg=DIM, font=("Consolas", 10)).pack(pady=(0, 30))

        btn_f = tk.Frame(f, bg=DARK)
        btn_f.pack()
        tk.Button(btn_f, text="  ＋  Add Display",
                  command=self._open_add_dialog,
                  bg=ACCENT, fg="white", font=("Consolas", 12, "bold"),
                  relief="flat", padx=24, pady=12,
                  cursor="hand2").pack()

        hint = ("Use the sidebar to switch between\n"
                "displays once you have added them.")
        tk.Label(f, text=hint, bg=DARK, fg=DIM,
                 font=("Consolas", 8), justify="center").pack(pady=(20, 0))

    def _show_panel(self, panel: ControlPanel):
        if self._current_panel:
            self._current_panel.pack_forget()
        panel.pack(fill="both", expand=True, in_=self._main)
        self._current_panel = panel

    def _open_add_dialog(self):
        dlg = AddDisplayDialog(self.root, self.devices,
                               next_index=len(self.devices) + 1)
        if dlg.result:
            self._launch(dlg.result)

    def _launch(self, config: dict):
        panel_ref = [None]

        def log_cb(msg):
            if panel_ref[0]:
                self.root.after(0, lambda m=msg: panel_ref[0].add_log(m))

        def ui_cb():
            if panel_ref[0]:
                self.root.after(0, self._refresh_sidebar)
                self.root.after(0, panel_ref[0].refresh_ui)

        dev   = DisplayInstance(config, log_cb, ui_cb)
        panel = ControlPanel(self._main, dev)
        panel_ref[0] = panel

        idx = len(self.devices)
        self.devices.append(dev)
        self.panels.append(panel)
        self._active_idx = idx
        self._show_panel(panel)
        self._refresh_sidebar()

        threading.Thread(target=self._run_server, args=(dev,),
                         daemon=True).start()

    def _select_device(self, idx: int):
        if 0 <= idx < len(self.panels):
            self._active_idx = idx
            self._show_panel(self.panels[idx])
            self._refresh_sidebar()

    def _refresh_sidebar(self):
        self.sidebar.refresh(self.devices, self._active_idx)

    def _run_server(self, dev: DisplayInstance):
        import sys
        # ProactorEventLoop is required on Windows for TCP servers.
        # Created directly here to avoid the deprecated set_event_loop_policy API.
        if sys.platform == "win32":
            loop = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(loop)
        else:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        self.loops.append(loop)
        try:
            server = loop.run_until_complete(
                asyncio.start_server(dev.handle_client, dev.ip, dev.port))
            dev._server = server
            addrs = [s.getsockname() for s in server.sockets]
            dev.log(f"SYS: Listening on {dev.ip}:{dev.port} [{dev.proto.NAME}]")
            for addr in addrs:
                dev.log(f"SYS: Bound socket: {addr}")
            loop.run_forever()
        except OSError as e:
            dev.log(f"SYS: FAILED to bind {dev.ip}:{dev.port} — {e}")
            dev.log(f"SYS: Check firewall and that nothing else is using port {dev.port}")
        except Exception as e:
            dev.log(f"SYS: Server error — {e}")
        finally:
            loop.close()


# ─────────────────────────────────────────────────────────────
# 7. ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    root = tk.Tk()
    ttk.Style().theme_use("clam")
    app = DisplayApp(root)
    root.mainloop()