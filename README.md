A versatile Python-based network emulator for professional AV display protocols. This tool allows developers and AV programmers (Crestron, Extron, Q-SYS, etc.) to simulate multiple hardware displays simultaneously on a single computer.

## Features
- **Multi-Brand Support**: Emulates 8 major AV brands:
  - **Philips** (SICP Hex protocol)
  - **Samsung** (MDC Hex protocol)
  - **Sony** (Bravia Hex protocol)
  - **NEC** (MultiSync Hex/ASCII Hybrid)
  - **LG** (SV ASCII protocol)
  - **Panasonic** (Pro ASCII with STX/ETX)
  - **Sharp** (PN Series ASCII)
  - **Christie** (Secure ASCII)
- **Asynchronous Architecture**: Leverages `asyncio` to handle dozens of concurrent connections without performance lag.
- **Dynamic Control Panel**: Real-time GUI to manage virtual displays, monitor raw network traffic, and simulate device failures.
- **Failure Simulation**:
  - **Online**: Standard response behavior.
  - **Timeout**: Stops responding to commands to test control system retry logic.
  - **Offline**: Closes the socket to simulate a network disconnect.
- **Config Management**: Save and load your display setups as `.json` files for quick deployment.

## Installation
1. Ensure you have **Python 3.7+** installed.
2. No external dependencies are required (uses standard libraries: `tkinter`, `asyncio`, `threading`, `json`).
3. Clone this repository or download the script.

## Usage
1. Run the script:
   ```bash
   python python.py
