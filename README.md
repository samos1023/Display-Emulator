# AV Display Emulator

A Python/Tkinter desktop application that emulates professional AV displays over TCP/IP, allowing you to test and develop control system programs (Crestron, AMX, Extron, etc.) without needing physical hardware.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)
![License](https://img.shields.io/badge/License-MIT-green)

---

## Supported Protocols

| Manufacturer | Protocol | Port | Type |
|---|---|---|---|
| Christie Secure Series II | K:ALL ASCII | 5000 | Text |
| Philips BDL / D-line | SICP v2.x (binary) | 5000 | Binary |
| LG Commercial | RS232/IP ASCII | 9761 | Text |
| Samsung Commercial | MDC (Multiple Display Control) | 1515 | Binary |
| NEC MultiSync | External Control (SOH/STX/ETX) | 7142 | Mixed |

---

## Features

- **Multiple simultaneous instances** — run as many emulated displays as you need, each on a different IP/port combination
- **Mixed protocol sessions** — run a Christie on port 5000 and a Samsung MDC on port 1515 at the same time
- **Sidebar navigation** — switch between display instances instantly
- **Full input switching** — all inputs per manufacturer spec, with active input highlighted
- **Volume control** — slider with real-time TCP feedback
- **Network toggle** — simulate a display going offline mid-session
- **Colour-coded TCP log** — IN (green), OUT (blue), SYS (amber), SIM (purple)
- **Accurate protocol emulation** — responses verified against real hardware captures

---

## Requirements

- Python 3.10 or higher
- Tkinter (included with most Python installations)
- No third-party packages required

### Windows
Tkinter is included with the standard Python installer from python.org. No additional steps needed.

### macOS
```bash
brew install python-tk
```

### Linux (Debian/Ubuntu)
```bash
sudo apt-get install python3-tk
```

---

## Installation

```bash
git clone https://github.com/yourusername/av-display-emulator.git
cd av-display-emulator
python displays.py
```

---

## Usage

### Adding a Display

1. Launch the application — the welcome screen appears with an **Add Display** button
2. Click **＋ Add Display** (also available in the sidebar at any time)
3. Fill in:
   - **Device Name** — a label for this instance (e.g. `Boardroom Left`)
   - **IP Address** — the IP your control system will connect to (use `0.0.0.0` to listen on all interfaces)
   - **TCP Port** — auto-fills with the correct default for the selected protocol
   - **Protocol** — select from the dropdown
4. Click **▶ LAUNCH** — the emulator starts listening immediately

### Control Panel

Each display gets its own tab in the sidebar and a full control panel:

- **POWER ON / STANDBY** — toggles power state; affects which commands the emulator responds to
- **INPUT SOURCE** — all inputs per the manufacturer spec; active input highlighted in blue
- **VOLUME** — slider sets current volume level
- **NETWORK: ONLINE/OFFLINE** — toggle to simulate network loss; drops all TCP connections
- **TCP LOG** — live feed of all incoming and outgoing traffic, colour-coded by direction

### Simulating Front Panel / Remote Control

The UI buttons simulate a user pressing physical buttons on the display. Unlike TCP commands, **UI button presses do not send any TCP response** — this matches real hardware behaviour where the display is silent when changed via remote or front panel. Your control system must poll to detect the change, exactly as it would with a real display.

---

## Protocol Reference

### Christie Secure Series II

**Port:** 5000 | **Format:** ASCII text | **Terminator:** `\r`

| Command | Send | Response |
|---|---|---|
| Power ON | `K:ALLPON.\r` | `ALL:PWR=000\r` + `ALL:FWV=A\r` + `ALL:MAC=A\r` |
| Power OFF | `K:ALLPOF.\r` | `ALL:POF=A\r` |
| Power query | `K:ALLPWR?\r` | `ALL:PWR=000\r` (on) / `ALL:PWR=002\r` (off) |
| Source query | `K:ALLSRC?\r` | `ALL:SRC=002\r` (silent when off) |
| Volume query | `K:ALLVOL?\r` | `ALL:VOL=050\r` (silent when off) |
| HDMI 1 | `K:ALLSH2.\r` | `ALL:SH2=A\r` |
| HDMI 2 | `K:ALLSH3.\r` | `ALL:SH3=A\r` |
| HDMI 3 | `K:ALLSH4.\r` | `ALL:SH4=A\r` |
| HDMI 4 | `K:ALLSH5.\r` | `ALL:SH5=A\r` |
| DP 1 | `K:ALLSH0.\r` | `ALL:SH0=A\r` |
| DP 2 | `K:ALLSH1.\r` | `ALL:SH1=A\r` |
| OPS/HDMI | `K:ALLSH7.\r` | `ALL:SH7=A\r` |
| OPS/DP | `K:ALLSH8.\r` | `ALL:SH8=A\r` |
| Volume set | `K:ALLVOL050.\r` | `ALL:VOL=A\r` |

**Notes:**
- All queries return silence when display is in standby, except `PWR?` which always responds
- Power ON returns three responses in a single burst (verified against real hardware)
- POF when already off returns `ALL:POF=N\r`

---

### Philips SICP (Binary)

**Port:** 5000 | **Format:** Binary | **Monitor ID:** `0x01` (configurable)

Frame: `[LEN][MON_ID][TYPE][CMD][PARAMS...][CHECKSUM]`
Checksum = XOR of all bytes before the checksum byte.

| Command | Hex |
|---|---|
| Power ON | `06 01 00 18 02 1D` |
| Power OFF | `06 01 00 18 01 1E` |
| Power query | `05 01 00 19 1D` |
| HDMI 1 | `06 01 00 AC 05 AE` *(see note)* |
| HDMI 2 | `06 01 00 AC 06 AD` |
| DisplayPort | `06 01 00 AC 0F A4` |
| Volume query | `05 01 00 44 40` |
| Volume set 50 | `06 01 00 45 32 70` |

**Response format:**
- Power ON/OFF ACK: `06 01 01 00 06 00`
- Power query ON: `06 01 01 19 02 1D`
- Power query OFF: `06 01 01 19 01 1E`

**Notes:**
- Monitor ID must match the display OSD setting: `Menu → Configuration 1 → Monitor ID`
- Change `MONITOR_ID` constant in `PhilipsSICPProtocol` class if your display uses a different ID
- SICP version query: send `06 01 00 A2 00 A5` — response contains version as ASCII (e.g. `2.09`)
- Input switching on Android-based models (D-line) may require enabling SICP control in the display settings

---

### LG Commercial

**Port:** 9761 | **Format:** ASCII text | **Terminator:** `\r`

Frame: `<cmd1><cmd2> <set_id> <data>\r`
Response: `<cmd2> <set_id> OK<data>x\r` (success) / `<cmd2> <set_id> NG<data>x\r` (error)

| Command | Send | Response |
|---|---|---|
| Power ON | `ka 01 01\r` | `a 01 OK01x\r` |
| Power OFF | `ka 01 00\r` | `a 01 OK00x\r` |
| Power query | `ka 01 ff\r` | `a 01 OK01x\r` or `a 01 OK00x\r` |
| HDMI 1 | `xb 01 90\r` | `b 01 OK90x\r` |
| HDMI 2 | `xb 01 91\r` | `b 01 OK91x\r` |
| HDMI 3 | `xb 01 92\r` | `b 01 OK92x\r` |
| DisplayPort | `xb 01 c0\r` | `b 01 OKc0x\r` |
| RGB/VGA | `xb 01 60\r` | `b 01 OK60x\r` |
| Source query | `xb 01 ff\r` | `b 01 OK90x\r` (example) |
| Volume set 50% | `kf 01 32\r` | `f 01 OK32x\r` |
| Volume query | `kf 01 ff\r` | `f 01 OK32x\r` (example) |
| Mute | `ke 01 00\r` | `e 01 OK00x\r` |
| Unmute | `ke 01 01\r` | `e 01 OK01x\r` |

**Notes:**
- Volume values are hexadecimal: `00`=0, `32`=50, `64`=100
- Set ID `01` = first display; use `ff` in the data field to query current value

---

### Samsung MDC (Binary)

**Port:** 1515 | **Format:** Binary

Frame: `[0xAA][CMD][ID][LEN][DATA...][CHECKSUM]`
Checksum = sum of all bytes after `0xAA`, keep lower byte only. Header `0xAA` excluded from checksum.

Response: `[0xAA][0xFF][ID][LEN][ACK][CMD][DATA...][CHECKSUM]`
ACK = `0x41` (success) / `0x4E` (error)

| Command | Hex |
|---|---|
| Power ON | `AA 11 FE 01 01 11` |
| Power OFF | `AA 11 FE 01 00 10` |
| HDMI 1 | `AA 14 FE 01 21 34` |
| HDMI 2 | `AA 14 FE 01 23 36` |
| HDMI 3 | `AA 14 FE 01 31 44` |
| HDMI 4 | `AA 14 FE 01 33 46` |
| DisplayPort | `AA 14 FE 01 14 27` |
| DVI | `AA 14 FE 01 18 2B` |
| RGB/VGA | `AA 14 FE 01 0C 1F` |
| Volume set 50 | `AA 12 FE 01 32 43` |
| Mute ON | `AA 13 FE 01 01 13` |
| Mute OFF | `AA 13 FE 01 00 12` |
| Volume step up | `AA 62 FE 01 00 61` |
| Volume step down | `AA 62 FE 01 01 62` |

**Notes:**
- `0xFE` = broadcast ID (all displays). Use `0x01` for a specific display
- Before Samsung will respond to MDC commands you must set: `Home → ID Settings → PC Connection Cable → RS232C cable`

---

### NEC MultiSync

**Port:** 7142 | **Format:** ASCII-encoded HEX with binary control characters

Frame: `[SOH][0x30][DEST][0x30][TYPE][LEN_HI][LEN_LO][STX][MSG...][ETX][BCC][CR]`
BCC = XOR of all bytes from `0x30` (Reserved) through `ETX` inclusive.

Monitor ID 1 = destination `0x41` ('A') | All displays = `0x2A` ('*')

| Command | Hex |
|---|---|
| Power ON | `01 30 41 30 41 30 43 02 43 32 30 33 44 36 30 30 30 31 03 73 0D` |
| Power OFF | `01 30 41 30 41 30 43 02 43 32 30 33 44 36 30 30 30 34 03 76 0D` |
| HDMI 1 | `01 30 41 30 45 30 41 02 30 30 36 30 30 30 30 34 03 71 0D` |
| HDMI 2 | `01 30 41 30 45 30 41 02 30 30 36 30 30 30 31 31 03 72 0D` |
| DisplayPort | `01 30 41 30 45 30 41 02 30 30 36 30 30 31 30 30 03 73 0D` |
| Mute ON | `01 30 41 30 45 30 41 02 30 30 38 44 30 30 30 31 03 09 0D` |
| Mute OFF | `01 30 41 30 45 30 41 02 30 30 38 44 30 30 30 32 03 0A 0D` |

**OP Codes for Get/Set Parameter commands:**

| Function | Page | OP Code |
|---|---|---|
| Power | `02` | `D6` |
| Input Source | `00` | `60` |
| Volume | `00` | `62` |
| Mute | `00` | `8D` |

**Notes:**
- Wait **15 seconds** after Power ON/OFF before sending the next command (NEC spec requirement)
- Wait **10 seconds** after input switching
- Change `MONITOR_ID` constant in `NECProtocol` class if your display uses a different ID
- The monitor disconnects if no data is received for 15 minutes — reconnect before sending commands

---

## Windows Firewall

If your control system (Crestron, AMX, etc.) cannot connect but localhost telnet works, Windows Firewall is blocking inbound connections. Run in an elevated PowerShell:

```powershell
netsh advfirewall firewall add rule name="AV Emulator" protocol=TCP dir=in localport=5000,1515,7142,9761 action=allow profile=any
```

Also confirm your network adapter is set to **Private** profile:

```powershell
Get-NetConnectionProfile
Set-NetConnectionProfile -InterfaceAlias "Ethernet" -NetworkCategory Private
```

---

## Architecture

```
displays.py
├── Protocol classes (one per manufacturer)
│   ├── ChristieProtocol      — ASCII text, parse() returns (response, state_update)
│   ├── PhilipsSICPProtocol   — Binary, _build_cmd() / _build_response()
│   ├── LGProtocol            — ASCII text, ok() / ng() helpers
│   ├── SamsungMDCProtocol    — Binary, _build_cmd() / _build_ack() / _build_nak()
│   └── NECProtocol           — ASCII-encoded hex, _build() / _get_param() / _set_param()
│
├── DisplayInstance           — Device state + asyncio TCP server
│   ├── handle_client()       — async TCP handler, dispatches to protocol parser
│   ├── ui_set_power/source/volume() — UI-driven state changes (silent, no TCP)
│   └── _broadcast()          — send bytes to all connected clients
│
├── ControlPanel              — Tkinter UI for one device instance
├── DeviceSidebar             — Left panel, device list and navigation
├── AddDisplayDialog          — Modal dialog for configuring a new instance
└── DisplayApp                — Main application shell
```

Each protocol class is self-contained and follows the same interface:
- `NAME` — display name for the dropdown
- `DEFAULT_PORT` — auto-filled in the dialog
- `BINARY` — `True` for binary protocols, `False` for text
- `SOURCE_MAP` — maps UI button labels to protocol source codes
- `parse(raw, device)` — returns `[(response, state_update), ...]`
- `ui_buttons()` — returns list of `(label, key)` tuples for the input source grid

---

## Adding a New Protocol

1. Create a new class following the pattern above
2. Implement `NAME`, `DEFAULT_PORT`, `BINARY`, `SOURCE_MAP`, `POWER_ON`, `POWER_OFF`, `parse()`, `ui_buttons()`
3. Add it to `PROTOCOL_MAP`

That's it — the UI, TCP server, and state management are all handled automatically.

---

## Known Limitations

- **Philips SICP input switching** on Android-based models (D-line, E-line) may not work via SICP alone — the display's Android layer can intercept input commands. Requires the display to be configured with SICP Control as the active control app.
- **NEC 15-minute timeout** — the real NEC protocol disconnects idle TCP connections after 15 minutes. The emulator does not implement this timeout but your control system should handle reconnection.
- **Samsung MDC** — the emulator responds to broadcast ID `0xFE`. If your control system addresses a specific display ID, update `DISPLAY_ID` in `SamsungMDCProtocol`.

---

## License

MIT License — free to use, modify, and distribute.

---

## Contributing

Pull requests welcome. When adding a new protocol, please include:
- Frame structure documentation in the class docstring
- Verified command/response examples from real hardware or an official spec
- Unit tests in the inline test block at the bottom of the file