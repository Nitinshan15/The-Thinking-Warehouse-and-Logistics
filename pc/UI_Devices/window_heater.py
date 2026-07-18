import tkinter as tk
from PIL import Image, ImageTk
import paho.mqtt.client as mqtt
import time

# --- CONFIGURATION ---
MQTT_BROKER = "192.168.0.199" 
TOPIC_WINDOW = "building1/floor0/zone1/actions"
TOPIC_HEATER = "building1/floor0/zone1/actions"

class WarehouseUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Smart Warehouse Monitor")
        self.root.geometry("600x400")

        # Container for Window
        self.win_frame = tk.Frame(root)
        self.win_frame.pack(side="left", padx=20)
        self.win_label = tk.Label(self.win_frame, text="Window Status", font=("Arial", 12))
        self.win_label.pack()
        
        # Load Window Images
        self.img_win_open = ImageTk.PhotoImage(Image.open("window_open.png").resize((150, 150)))
        self.img_win_closed = ImageTk.PhotoImage(Image.open("window_closed.png").resize((150, 150)))
        self.win_img_display = tk.Label(self.win_frame, image=self.img_win_closed)
        self.win_img_display.pack()

        # Container for Heater
        self.heat_frame = tk.Frame(root)
        self.heat_frame.pack(side="right", padx=20)
        self.heat_label = tk.Label(self.heat_frame, text="Heater Status", font=("Arial", 12))
        self.heat_label.pack()

        # Load Heater Images
        self.img_heat_on = ImageTk.PhotoImage(Image.open("heater_on.png").resize((150, 150)))
        self.img_heat_off = ImageTk.PhotoImage(Image.open("heater_off.png").resize((150, 150)))
        self.heat_img_display = tk.Label(self.heat_frame, image=self.img_heat_off)
        self.heat_img_display.pack()

    def update_window(self, status):
        img = self.img_win_open if status.upper() == "OPEN" else self.img_win_closed
        self.win_img_display.config(image=img)

    def update_heater(self, status):
        img = self.img_heat_on if status.upper() == "ON" else self.img_heat_off
        self.heat_img_display.config(image=img)

# --- MQTT SETUP ---
def on_message(client, userdata, msg):

    payload_str = msg.payload.decode()
    raw_payload = payload_str

    try:
        actions_list = [line.strip() for line in raw_payload.split("\n") if line.strip()]
    
        print(f"\n[{time.strftime('%X')}] Received Action Batch. Processed List: {actions_list}")
    
        # 3. Iterate through the actions list and match commands
        for action in actions_list:
            
            # --- FAN CONTROLS ---
            if "window-open" in action:
                app.root.after(0, lambda: app.update_window("OPEN"))
            else:
                app.root.after(0, lambda: app.update_window("CLOSED"))

            # --- HEATER CONTROLS ---
            if "heater-on" in action:
                app.root.after(0, lambda: app.update_heater("ON"))
            else:
                app.root.after(0, lambda: app.update_heater("OFF"))

    except Exception as e:
        print(f"[-] Failed to process MQTT command action: {e}")

root = tk.Tk()
app = WarehouseUI(root)

client = mqtt.Client()
client.on_message = on_message
client.connect(MQTT_BROKER, 1883, 60)
client.subscribe([(TOPIC_WINDOW, 0), (TOPIC_HEATER, 0)])
client.loop_start()

root.mainloop()