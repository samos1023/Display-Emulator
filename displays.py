import asyncio
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext

# --- EMULATOR LOGIC CLASS ---
class VirtualDisplayInstance:
    def __init__(self, name, ip, port, display_type, log_callback, ui_update_callback):
        self.name = name
        self.ip = ip
        self.port = port
        self.display_type = display_type
        self.log = log_callback
        self.ui_update = ui_update_callback
        self.status = "ONLINE" 
        
        # Unified virtual device state
        self.state = {
            "PWR": "001",  # 000=On, 001=Off
            "SRC": "002",  # Default HDMI 1
            "VOL": "025",  # 0-100 decimal
            "MUT": "000"   
        }

    def set_state(self, key, value):
        self.state[key] = value
        self.log(f"[LOCAL] {self.name}: {key} -> {value}")
        self.ui_update()

    async def handle_client(self, reader, writer):
        addr = writer.get_extra_info('peername')
        self.log(f"[*] {self.name}: Connected to {addr}")
        
        try:
            while True:
                data = await reader.read(1024)
                if not data: break
                
                # Network log incoming data
                self.log(f"[RX] {self.name}: {data.hex().upper() if isinstance(data, bytes) else data}")
                
                # Mock response (ACK)
                writer.write(b"ACK\r\n")
                await writer.drain()
        except Exception as e:
            self.log(f"[!] {self.name} Error: {e}")
        finally:
            writer.close()

# --- REMOTE CONTROL UI ---
class DeviceRemoteControl(tk.Frame):
    def __init__(self, parent, device):
        super().__init__(parent, bg="#2e2e2e", padx=20, pady=20)
        self.device = device
        
        tk.Label(self, text=f"{device.name} ({device.display_type})", fg="white", bg="#2e2e2e", font=("Arial", 12, "bold")).pack(pady=10)

        # Power Section
        p_frame = tk.Frame(self, bg="#2e2e2e")
        p_frame.pack(pady=5)
        self.btn_on = tk.Button(p_frame, text="POWER ON", width=12, command=lambda: device.set_state("PWR", "000"))
        self.btn_on.pack(side="left", padx=5)
        self.btn_off = tk.Button(p_frame, text="POWER OFF", width=12, command=lambda: device.set_state("PWR", "001"))
        self.btn_off.pack(side="left", padx=5)

        # Inputs Section
        tk.Label(self, text="Source Selection", fg="white", bg="#2e2e2e").pack(pady=10)
        self.src_btns = {}
        s_frame = tk.Frame(self, bg="#2e2e2e")
        s_frame.pack()
        for i, s in enumerate(["HDMI 1", "HDMI 2", "DisplayPort", "VGA"]):
            code = f"00{i+1}"
            btn = tk.Button(s_frame, text=s, width=12, command=lambda c=code: device.set_state("SRC", c))
            btn.grid(row=i//2, column=i%2, padx=5, pady=5)
            self.src_btns[code] = btn
            
        self.refresh_ui()

    def refresh_ui(self):
        # Update colors based on current state
        self.btn_on.config(bg="#006400" if self.device.state["PWR"]=="000" else "#555", fg="white")
        self.btn_off.config(bg="#8b0000" if self.device.state["PWR"]=="001" else "#555", fg="white")
        for code, btn in self.src_btns.items():
            btn.config(bg="#FF8C00" if self.device.state["SRC"]==code else "#555", fg="black" if self.device.state["SRC"]==code else "white")

# --- MASTER APPLICATION ---
class IntegratedEmulatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Universal AV Display Emulator")
        self.root.geometry("1000x750")
        
        self.device_configs = []
        self.active_devices = []

        # Tabs
        self.main_tabs = ttk.Notebook(root)
        self.setup_page = tk.Frame(self.main_tabs)
        self.remote_page = ttk.Notebook(self.main_tabs)
        self.console_page = tk.Frame(self.main_tabs)
        
        self.main_tabs.add(self.setup_page, text="1. Setup & Config")
        self.main_tabs.add(self.remote_page, text="2. Device Remotes")
        self.main_tabs.add(self.console_page, text="3. Network Logs")
        self.main_tabs.pack(fill="both", expand=True)

        self.setup_ui()
        
        # Log Text Box
        self.log_text = scrolledtext.ScrolledText(self.console_page, bg="black", fg="#00FF00", font=("Consolas", 10))
        self.log_text.pack(fill="both", expand=True)

    def setup_ui(self):
        self.rows_container = tk.Frame(self.setup_page, padx=20, pady=20)
        self.rows_container.pack(fill="x")
        
        tk.Button(self.setup_page, text="+ Add Display Row", command=self.add_config_row).pack(pady=5)
        tk.Button(self.setup_page, text="START EMULATOR SUITE", bg="lightgreen", font=("Arial", 10, "bold"), 
                  command=self.launch_all).pack(pady=20)
        
        # Add the first row automatically
        self.add_config_row()

    def add_config_row(self):
        row = tk.Frame(self.rows_container)
        row.pack(fill="x", pady=2)
        
        n_var = tk.StringVar(value=f"Display_{len(self.device_configs)+1}")
        ip_var = tk.StringVar(value="127.0.0.1")
        brand_var = tk.StringVar()
        
        tk.Entry(row, textvariable=n_var, width=15).pack(side="left", padx=5)
        tk.Entry(row, textvariable=ip_var, width=15).pack(side="left", padx=5)
        
        # FULL 8 BRANDS
        brands = [
            "Christie Secure", "Philips SICP", "LG SV", "Samsung MDC", 
            "Sony Bravia", "Sharp PN", "Panasonic Pro", "NEC MultiSync"
        ]
        cb = ttk.Combobox(row, textvariable=brand_var, values=brands, width=20, state="readonly")
        cb.set("Christie Secure")
        cb.pack(side="left", padx=5)
        
        tk.Button(row, text="X", fg="red", command=lambda r=row: self.remove_row(r)).pack(side="left", padx=10)
        self.device_configs.append({"name": n_var, "ip": ip_var, "brand": brand_var, "frame": row})

    def remove_row(self, row_frame):
        self.device_configs = [c for c in self.device_configs if c["frame"] != row_frame]
        row_frame.destroy()

    def launch_all(self):
        for idx, cfg in enumerate(self.device_configs):
            if not cfg["frame"].winfo_exists(): continue
            
            dev = VirtualDisplayInstance(cfg["name"].get(), cfg["ip"].get(), 5000+idx, cfg["brand"].get(), self.log, self.safe_refresh)
            self.active_devices.append(dev)
            
            # Create a remote control tab for each device
            self.remote_page.add(DeviceRemoteControl(self.remote_page, dev), text=dev.name)
            
            # Start network thread for this device
            threading.Thread(target=self.run_net, args=(dev,), daemon=True).start()
            self.log(f"[SYS] Started {dev.name} ({dev.display_type}) on {dev.ip}:{dev.port}")
            
        self.main_tabs.select(self.remote_page)

    def log(self, msg):
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)

    def safe_refresh(self):
        self.root.after(0, self.refresh_all)

    def refresh_all(self):
        for tab in self.remote_page.winfo_children():
            if hasattr(tab, 'refresh_ui'): tab.refresh_ui()

    def run_net(self, dev):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(asyncio.start_server(dev.handle_client, dev.ip, dev.port))
            loop.run_forever()
        except Exception as e:
            self.log(f"[ERROR] Networking failed for {dev.name}: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = IntegratedEmulatorApp(root)
    root.mainloop()