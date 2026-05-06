import asyncio
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext

class VirtualDisplayInstance:
    def __init__(self, name, ip, port, display_type, log_callback, ui_update_callback):
        self.name = name
        self.ip = ip
        self.port = port
        self.display_type = display_type
        self.log = log_callback
        self.ui_update = ui_update_callback
        self.status = "ONLINE" 
        
        # Internal State - initialized to common defaults
        self.state = {
            "PWR": "OFF",
            "SRC": "HDMI 1",
            "VOL": 25,
            "MUT": "OFF"   
        }

    def set_state(self, key, value):
        self.state[key] = value
        self.log(f"[LOCAL] {self.name}: {key} changed to {value}")
        self.ui_update()

    async def handle_client(self, reader, writer):
        # Protocol logic would go here (Philips SICP, Samsung MDC, etc.)
        # If reader receives a 'Set Input' command, it calls self.set_state("SRC", "HDMI 2")
        pass

class DeviceRemoteControl(tk.Frame):
    def __init__(self, parent, device):
        super().__init__(parent, bg="#2e2e2e", padx=20, pady=20)
        self.device = device
        
        tk.Label(self, text=f"Remote: {device.name}", fg="white", bg="#2e2e2e", font=("Arial", 12, "bold")).pack(pady=10)

        # --- POWER SECTION ---
        pwr_frame = tk.LabelFrame(self, text="Power", bg="#2e2e2e", fg="white", padx=10, pady=10)
        pwr_frame.pack(fill="x", pady=5)
        self.btn_on = tk.Button(pwr_frame, text="ON", width=10, command=lambda: device.set_state("PWR", "ON"))
        self.btn_on.pack(side="left", padx=5)
        self.btn_off = tk.Button(pwr_frame, text="OFF", width=10, command=lambda: device.set_state("PWR", "OFF"))
        self.btn_off.pack(side="left", padx=5)

        # --- INPUT SWITCHING SECTION ---
        src_frame = tk.LabelFrame(self, text="Input Source Selection", bg="#2e2e2e", fg="white", padx=10, pady=10)
        src_frame.pack(fill="x", pady=5)
        
        self.src_buttons = {}
        sources = ["HDMI 1", "HDMI 2", "DisplayPort", "VGA", "Internal Player"]
        
        for i, src in enumerate(sources):
            btn = tk.Button(src_frame, text=src, width=12, 
                            command=lambda s=src: device.set_state("SRC", s))
            # Grid them 3 per row
            btn.grid(row=i//3, column=i%3, padx=5, pady=5)
            self.src_buttons[src] = btn

        # --- VOLUME SECTION ---
        vol_frame = tk.LabelFrame(self, text="Audio", bg="#2e2e2e", fg="white", padx=10, pady=10)
        vol_frame.pack(fill="x", pady=5)
        tk.Button(vol_frame, text="VOL +", width=5, command=lambda: device.set_state("VOL", min(100, device.state["VOL"]+1))).pack(side="left", padx=2)
        tk.Button(vol_frame, text="VOL -", width=5, command=lambda: device.set_state("VOL", max(0, device.state["VOL"]-1))).pack(side="left", padx=2)
        self.vol_label = tk.Label(vol_frame, text="Vol: 0", bg="#2e2e2e", fg="#00FF00", width=10, font=("Arial", 10, "bold"))
        self.vol_label.pack(side="left", padx=10)

        self.refresh_ui()

    def refresh_ui(self):
        # Update Power Button Styling
        pwr_status = self.device.state["PWR"]
        self.btn_on.config(bg="#006400" if pwr_status == "ON" else "#444444", fg="white")
        self.btn_off.config(bg="#8b0000" if pwr_status == "OFF" else "#444444", fg="white")

        # Update Input Button Styling (Highlight the active source in Amber)
        current_src = self.device.state["SRC"]
        for src_name, btn in self.src_buttons.items():
            if src_name == current_src:
                btn.config(bg="#FF8C00", fg="black") # Active
            else:
                btn.config(bg="#555555", fg="white") # Inactive

        # Update Volume
        self.vol_label.config(text=f"LEVEL: {self.device.state['VOL']}%")

class DisplayEmulatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Display Emulator v2.1")
        self.root.geometry("600x550")
        
        # Simple setup for one device for this demo
        self.dev = VirtualDisplayInstance("Meeting Room 1", "127.0.0.1", 5000, "Philips SICP", print, self.safe_refresh)
        
        self.remote = DeviceRemoteControl(root, self.dev)
        self.remote.pack(fill="both", expand=True)

    def safe_refresh(self):
        self.root.after(0, self.remote.refresh_ui)

if __name__ == "__main__":
    root = tk.Tk()
    app = DisplayEmulatorApp