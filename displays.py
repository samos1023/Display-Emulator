import asyncio
import threading
import json
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

# --- EMULATOR LOGIC CLASS ---
class VirtualDisplayInstance:
    def __init__(self, name, ip, port, display_type, log_callback):
        self.name = name
        self.ip = ip
        self.port = port
        self.display_type = display_type
        self.log = log_callback
        
        self.status = "ONLINE" 
        
        # Unified virtual device state
        self.state = {
            "PWR": "001",  # 000=On, 001=Off
            "SRC": "002",  # Default HDMI 1
            "VOL": "025",  # 0-100 decimal
            "MUT": "000"   
        }

    # ==========================================
    # NETWORK HANDLING (Applies to ALL Brands)
    # ==========================================
    async def handle_client(self, reader, writer):
        addr = writer.get_extra_info('peername')
        
        if self.status == "OFFLINE":
            self.log(f"[!] {self.name}: Connection refused from {addr}")
            writer.close()
            await writer.wait_closed()
            return

        self.log(f"[*] {self.name} ({self.display_type} @ {self.ip}): Connected to {addr}")
        
        try:
            while True:
                if self.status == "OFFLINE":
                    self.log(f"[!] {self.name}: Went OFFLINE. Dropping {addr}.")
                    break

                try:
                    data = await asyncio.wait_for(reader.read(1024), timeout=1.0)
                except asyncio.TimeoutError:
                    continue 

                if not data:
                    self.log(f"[*] {self.name}: Client {addr} disconnected.")
                    break
                
                if self.status == "TIMEOUT":
                    self.log(f"[!] {self.name} (Timeout Mode): Ignoring command.")
                    continue
                
                # Route to Parser
                responses = self.process_data(data)
                
                # Send Responses
                for resp in responses:
                    if isinstance(resp, str):
                        self.log(f"[>] {self.name} TX: {repr(resp)}")
                        writer.write(resp.encode('ascii'))
                    else:
                        self.log(f"[>] {self.name} TX (HEX): {resp.hex().upper()}")
                        writer.write(resp)
                        
                await writer.drain()

        except Exception as e:
            self.log(f"[!] {self.name} Error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    def process_data(self, data):
        # Text-based protocols
        if self.display_type in ["Christie Secure", "LG SV", "Sharp PN", "Panasonic Pro"]:
            msg = data.decode('ascii', errors='ignore')
            self.log(f"[<] {self.name} RX: {repr(msg)}")
            
            if self.display_type == "Christie Secure": return self.parse_christie(msg.strip())
            elif self.display_type == "LG SV": return self.parse_lg(msg.strip())
            elif self.display_type == "Sharp PN": return self.parse_sharp(msg)
            elif self.display_type == "Panasonic Pro": return self.parse_panasonic(msg)

        # Hex-based protocols
        elif self.display_type in ["Philips SICP", "Samsung MDC", "Sony Bravia", "NEC MultiSync"]:
            self.log(f"[<] {self.name} RX (HEX): {data.hex().upper()}")
            
            if self.display_type == "Philips SICP": return self.parse_philips(data)
            elif self.display_type == "Samsung MDC": return self.parse_samsung(data)
            elif self.display_type == "Sony Bravia": return self.parse_sony(data)
            elif self.display_type == "NEC MultiSync": return self.parse_nec(data)
            
        return []

    # ==========================================
    # PROTOCOL 1: NEC MULTISYNC (HEX/ASCII Hybrid)
    # ==========================================
    def parse_nec(self, data):
        """ Format: SOH[01] Res[30] ID[xx] ID[xx] Type[xx] Len[xx][xx] STX[02] [Payload] ETX[03] BCC[xx] CR[0D] """
        responses = []
        if len(data) < 10 or data[0] != 0x01 or data[-1] != 0x0D: return responses
        
        try:
            stx_idx, etx_idx = data.index(0x02), data.index(0x03)
            msg_type = data[4] # 0x41(A)=Cmd, 0x43(C)=Get, 0x45(E)=Set
            payload = data[stx_idx+1:etx_idx]
        except ValueError:
            return responses
        
        # Determine Response Type (B=Cmd Reply, D=Get Reply, F=Set Reply)
        resp_type = 0x42 
        if msg_type == 0x43: resp_type = 0x44 
        elif msg_type == 0x45: resp_type = 0x46
        
        op_code = payload[0:4].decode('ascii', errors='ignore') if len(payload) >= 4 else ""
        resp_payload = bytearray(payload)
        
        # GET Queries
        if msg_type == 0x43: 
            if op_code == "0200": # Power
                pwr = b"0001" if self.state["PWR"] == "000" else b"0004" # 1=On, 4=Off
                resp_payload = payload[0:4] + b"0000" + pwr
            elif op_code == "0062": # Vol
                vol_hex = f"{int(self.state['VOL']):04X}".encode('ascii')
                resp_payload = payload[0:4] + b"0000" + vol_hex
            elif op_code == "0060": # Input
                resp_payload = payload[0:4] + b"00000011" # 11 = HDMI
        
        # SET Commands
        elif msg_type in [0x45, 0x41]: 
            if op_code == "0200" or op_code == "C203": # Power
                if b"0001" in payload: self.state["PWR"] = "000"
                elif b"0004" in payload: self.state["PWR"] = "001"
            elif op_code == "0062" and len(payload) >= 8: # Vol
                try: self.state["VOL"] = str(int(payload[4:8].decode(), 16)).zfill(3)
                except: pass
            elif op_code == "0060": # Input
                self.state["SRC"] = "002"
            resp_payload = payload[0:4] + b"0000" # Success ACK

        # Build Packet
        header = bytearray([0x01, 0x30, data[3], data[2], resp_type]) # Swap Source/Dest IDs
        header.extend(f"{len(resp_payload):02X}".encode('ascii'))
        packet = header + b"\x02" + resp_payload + b"\x03"
        
        # Calculate BCC (XOR from byte 1 to ETX)
        bcc = 0
        for b in packet[1:]: bcc ^= b
        packet.append(bcc)
        packet.append(0x0D)
        
        responses.append(bytes(packet))
        return responses

    # ==========================================
    # PROTOCOL 2: SHARP PN SERIES (ASCII)
    # ==========================================
    def parse_sharp(self, msg):
        responses = []
        for cmd in msg.split('\r'):
            if len(cmd) < 8: continue
            header, param = cmd[0:4], cmd[4:8]
            if param == "????":
                if header == "POWR": responses.append(f"{'0001' if self.state['PWR'] == '000' else '0000'}\r")
                elif header == "VOLM": responses.append(f"{int(self.state['VOL']):04d}\r")
                elif header == "INPS": responses.append("0001\r")
                else: responses.append("ERR\r")
            else:
                if header == "POWR": self.state["PWR"] = "000" if param == "0001" else "001"
                elif header == "VOLM": self.state["VOL"] = str(int(param)).zfill(3)
                elif header == "INPS": self.state["SRC"] = "002"
                responses.append("OK\r")
        return responses

    # ==========================================
    # PROTOCOL 3: PANASONIC PRO (ASCII w/ STX/ETX)
    # ==========================================
    def parse_panasonic(self, msg):
        responses = []
        if '\x02' in msg and '\x03' in msg:
            for cmd in msg.split('\x02'):
                if not cmd or '\x03' not in cmd: continue
                payload = cmd.split('\x03')[0]
                if payload == "PON": self.state["PWR"] = "000"; responses.append("\x02PON\x03")
                elif payload == "POF": self.state["PWR"] = "001"; responses.append("\x02POF\x03")
                elif payload.startswith("AVL:"): self.state["VOL"] = payload[4:].zfill(3); responses.append(f"\x02{payload}\x03")
                elif payload.startswith("IMS:"): self.state["SRC"] = "002"; responses.append(f"\x02{payload}\x03")
                elif payload == "QPW": responses.append(f"\x02{'001' if self.state['PWR'] == '000' else '000'}\x03")
                elif payload == "QAV": responses.append(f"\x02{self.state['VOL']}\x03")
                elif payload == "QIM": responses.append("\x02HM1\x03") 
        return responses

    # ==========================================
    # PROTOCOL 4: SONY BRAVIA (HEX)
    # ==========================================
    def parse_sony(self, data):
        responses = []
        if len(data) < 6: return responses
        header, category, func, length, val = data[0], data[1], data[2], data[3], data[4]
        if data[-1] != (sum(data[:-1]) & 0xFF): return responses
            
        def build_sony_ack(f, v):
            ack = bytearray([0x70, 0x00, f, 0x02, v])
            ack.append(sum(ack) & 0xFF)
            return bytes(ack)

        if header == 0x8C: 
            if func == 0x00: self.state["PWR"] = "000" if val == 0x01 else "001"
            elif func == 0x05: self.state["VOL"] = str(val).zfill(3)
            elif func == 0x02: self.state["SRC"] = "002"
            responses.append(build_sony_ack(func, val))
        elif header == 0x83: 
            if func == 0x00: responses.append(build_sony_ack(func, 0x01 if self.state["PWR"] == "000" else 0x00))
            elif func == 0x05: responses.append(build_sony_ack(func, int(self.state["VOL"])))
            elif func == 0x02: responses.append(build_sony_ack(func, 0x03))
        return responses

    # ==========================================
    # PROTOCOL 5: CHRISTIE SECURE (ASCII)
    # ==========================================
    def parse_christie(self, cmd_str):
        responses = []
        commands = [c for c in cmd_str.split('.') if c.strip()]
        for cmd in commands:
            cmd = cmd.strip()
            if cmd.endswith('?'):
                key = cmd.replace('K:ALL', '').replace('?', '')
                responses.append(f"ALL: {key}={self.state.get(key, 'E')}")
            elif cmd.startswith('K:ALL'):
                raw = cmd.replace('K:ALL', '')
                if raw == "PON": self.state["PWR"] = "000"
                elif raw == "POF": self.state["PWR"] = "001"
                elif raw.startswith("SH"): self.state["SRC"] = raw[2:].zfill(3)
                elif raw.startswith("VOL"): self.state["VOL"] = raw[3:].zfill(3)
                responses.append(f"ALL:{raw}=A")
        return responses

    # ==========================================
    # PROTOCOL 6: PHILIPS SICP (HEX)
    # ==========================================
    def parse_philips(self, data):
        responses = []
        if len(data) < 4: return responses
        cs = 0
        for b in data[:-1]: cs ^= b
        if data[-1] != cs: return responses

        msg_type, mon_id, group = data[1], data[2], data[3]
        if msg_type == 0x02: 
            if group == 0x18: p = 0x02 if self.state["PWR"] == "000" else 0x01; resp = bytearray([0x06, 0x01, mon_id, 0x18, p])
            elif group == 0x44: resp = bytearray([0x07, 0x01, mon_id, 0x44, 0x00, int(self.state["VOL"])])
            elif group == 0xAC: resp = bytearray([0x07, 0x01, mon_id, 0xAC, 0x09, 0x01])
            else: resp = bytearray([0x05, 0x01, mon_id, group])
            cs_out = 0
            for b in resp: cs_out ^= b
            resp.append(cs_out)
            responses.append(bytes(resp))

        elif msg_type == 0x00: 
            if group == 0x18 and len(data) >= 6: self.state["PWR"] = "000" if data[4] == 0x02 else "001"
            elif group == 0x44 and len(data) >= 7 and data[4] == 0x00: self.state["VOL"] = str(data[5]).zfill(3)
            elif group == 0xAC: self.state["SRC"] = "002"
            ack = bytearray(data); ack[1] = 0x01; cs_ack = 0
            for b in ack[:-1]: cs_ack ^= b
            ack[-1] = cs_ack
            responses.append(bytes(ack))
        return responses

    # ==========================================
    # PROTOCOL 7: LG SV (ASCII)
    # ==========================================
    def parse_lg(self, cmd_str):
        responses = []
        parts = cmd_str.split()
        if len(parts) < 3: return responses
        cmd, set_id, val = parts[0], parts[1], parts[2]
        r_cmd = cmd[1] 

        if cmd == "ka": 
            if val == "01": self.state["PWR"] = "000"
            elif val == "00": self.state["PWR"] = "001"
            elif val.lower() == "ff": val = "01" if self.state["PWR"] == "000" else "00"
        elif cmd == "mc": 
            if val.lower() == "ff": val = f"{int(self.state['VOL']):02x}"
            else: self.state["VOL"] = str(int(val, 16)).zfill(3)
        elif cmd == "xb": 
            if val.lower() == "ff": val = "90"
            else: self.state["SRC"] = "002" 
        responses.append(f"{r_cmd} {set_id} OK{val}x")
        return responses

    # ==========================================
    # PROTOCOL 8: SAMSUNG MDC (HEX)
    # ==========================================
    def parse_samsung(self, data):
        responses = []
        if len(data) < 5 or data[0] != 0xAA: return responses
        cmd, mon_id, d_len = data[1], data[2], data[3]
        if data[-1] != (sum(data[1:-1]) & 0xFF): return responses

        def build_ack(payload):
            ack = bytearray([0xAA, 0xFF, mon_id, len(payload)]) + payload
            ack.append(sum(ack[1:]) & 0xFF)
            return bytes(ack)

        if cmd == 0x11: 
            if d_len == 1 and data[4] != 0x00: self.state["PWR"] = "000" if data[4] == 0x01 else "001"
            p = 0x01 if self.state["PWR"] == "000" else 0x00
            responses.append(build_ack(bytearray([0x41, 0x11, p])))
        elif cmd == 0x12: 
            if d_len == 1: self.state["VOL"] = str(data[4]).zfill(3)
            responses.append(build_ack(bytearray([0x41, 0x12, int(self.state["VOL"])])))
        elif cmd == 0x14: 
            if d_len == 1: self.state["SRC"] = "002"
            responses.append(build_ack(bytearray([0x41, 0x14, 0x21])))
        return responses

    async def start(self):
        try:
            server = await asyncio.start_server(self.handle_client, self.ip, self.port)
            self.log(f"[✔] Started '{self.name}' on {self.ip}:{self.port}")
            async with server:
                await server.serve_forever()
        except Exception as e:
            self.log(f"[!] FAILED to bind {self.name} to {self.ip}: {e}")

# ==========================================
# GUI INTERFACE CLASS
# ==========================================
class EmulatorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Universal AV Display Emulator (8 Brands)")
        self.root.geometry("1100x700")
        
        self.display_inputs = [] 
        self.displays = []       
        
        self.setup_frame = tk.Frame(self.root)
        self.run_frame = tk.Frame(self.root)
        
        self.build_setup_ui()
        self.setup_frame.pack(fill="both", expand=True, padx=20, pady=20)

    def build_setup_ui(self):
        tk.Label(self.setup_frame, text="Network & Protocol Configuration", font=("Arial", 16, "bold")).pack(pady=10)
        
        tool_bar = tk.Frame(self.setup_frame)
        tool_bar.pack(fill="x", pady=5)
        tk.Button(tool_bar, text="💾 Save Config", command=self.save_config).pack(side="left", padx=5)
        tk.Button(tool_bar, text="📂 Load Config", command=self.load_config).pack(side="left", padx=5)

        self.canvas = tk.Canvas(self.setup_frame)
        self.scrollbar = tk.Scrollbar(self.setup_frame, orient="vertical", command=self.canvas.yview)
        self.rows_frame = tk.Frame(self.canvas)

        self.rows_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.rows_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True, pady=10)
        self.scrollbar.pack(side="right", fill="y")
        
        self.add_display_row("NEC_Monitor", "192.168.1.101", "NEC MultiSync")
        
        bottom_bar = tk.Frame(self.setup_frame)
        bottom_bar.pack(side="bottom", fill="x", pady=10)
        tk.Button(bottom_bar, text="+ Add Display", command=lambda: self.add_display_row()).pack(side="left", padx=10)
        tk.Button(bottom_bar, text="▶ START EMULATOR", bg="lightgreen", font=("Arial", 10, "bold"), command=self.start_simulator).pack(side="right", padx=10)

    def add_display_row(self, name="", ip="", dtype="Christie Secure"):
        row = tk.Frame(self.rows_frame)
        row.pack(fill="x", pady=2)
        n_var, i_var, t_var = tk.StringVar(value=name), tk.StringVar(value=ip), tk.StringVar(value=dtype)
        
        tk.Label(row, text="Name:").pack(side="left")
        tk.Entry(row, textvariable=n_var, width=15).pack(side="left", padx=5)
        tk.Label(row, text="IP:").pack(side="left")
        tk.Entry(row, textvariable=i_var, width=15).pack(side="left", padx=5)
        
        # Now 8 Brands Supported
        brands = [
            "Christie Secure", "Philips SICP", "LG SV", "Samsung MDC", 
            "Sony Bravia", "Sharp PN", "Panasonic Pro", "NEC MultiSync"
        ]
        type_dropdown = ttk.Combobox(row, textvariable=t_var, values=brands, state="readonly", width=18)
        type_dropdown.pack(side="left", padx=5)
        
        tk.Button(row, text="X", fg="red", command=lambda r=row, n=n_var: self.remove_display_row(r, n)).pack(side="left", padx=10)
        self.display_inputs.append({"name": n_var, "ip": i_var, "type": t_var, "frame": row})

    def remove_display_row(self, frame, n_var):
        frame.destroy()
        self.display_inputs = [d for d in self.display_inputs if d["name"] != n_var]

    def save_config(self):
        data = [{"name": d["name"].get(), "ip": d["ip"].get(), "type": d["type"].get()} for d in self.display_inputs]
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if path:
            with open(path, 'w') as f: json.dump(data, f, indent=4)
            messagebox.showinfo("Success", "Configuration Saved.")

    def load_config(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if path:
            with open(path, 'r') as f: data = json.load(f)
            for d in self.display_inputs: d["frame"].destroy()
            self.display_inputs = []
            for item in data: 
                self.add_display_row(item["name"], item["ip"], item.get("type", "Christie Secure"))

    def start_simulator(self):
        for config in self.display_inputs:
            n, i, t = config["name"].get().strip(), config["ip"].get().strip(), config["type"].get().strip()
            if n and i:
                self.displays.append(VirtualDisplayInstance(n, i, 5000, t, self.gui_log))
        
        self.setup_frame.pack_forget()
        self.build_run_ui()
        self.run_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.start_async_thread()

    def build_run_ui(self):
        ctrl = tk.LabelFrame(self.run_frame, text="Active Displays Control Panel", padx=10, pady=10)
        ctrl.pack(fill="x", pady=5)

        for d in self.displays:
            row = tk.Frame(ctrl)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=f"{d.name} [{d.display_type}] ({d.ip})", width=45, anchor="w").pack(side="left")
            
            tk.Button(row, text="Online", bg="lightgreen", width=8, command=lambda d=d: self.set_status(d, "ONLINE")).pack(side="left", padx=2)
            tk.Button(row, text="Timeout", bg="lightyellow", width=8, command=lambda d=d: self.set_status(d, "TIMEOUT")).pack(side="left", padx=2)
            tk.Button(row, text="Offline", bg="salmon", width=8, command=lambda d=d: self.set_status(d, "OFFLINE")).pack(side="left", padx=2)

        log_box = tk.LabelFrame(self.run_frame, text="Live Network Console")
        log_box.pack(fill="both", expand=True, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_box, state='disabled', bg="black", fg="#00FF00", font=("Consolas", 10))
        self.log_text.pack(fill="both", expand=True)

    def set_status(self, d, s):
        d.status = s
        self.gui_log(f">>> FORCE OVERRIDE: {d.name} set to {s} mode <<<")

    def gui_log(self, msg):
        def append():
            self.log_text.config(state='normal')
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state='disabled')
        self.root.after(0, append)

    def start_async_thread(self):
        loop = asyncio.new_event_loop()
        def run():
            asyncio.set_event_loop(loop)
            loop.run_until_complete(asyncio.gather(*[d.start() for d in self.displays]))
        threading.Thread(target=run, daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    app = EmulatorGUI(root)
    root.mainloop()
