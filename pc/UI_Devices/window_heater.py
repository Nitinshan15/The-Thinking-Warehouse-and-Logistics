import json
import tkinter as tk
from PIL import Image, ImageTk
import paho.mqtt.client as mqtt
import time
import re
from sympy import re

# --- CONFIGURATION ---
MQTT_BROKER = "192.168.0.199" 
TOPIC_WINDOW = "building1/floor0/zone1/actions"
TOPIC_HEATER = "building1/floor0/zone1/actions"

TOPIC_WINDOW_ACT = "building1/floor0/zone1/window_actuator_status"
TOPIC_HEATER_ACT = "building1/floor0/zone1/heater_actuator_status"

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

    actions_list = [line.strip() for line in raw_payload.split("\n") if line.strip()]
    
    print(f"\n[{time.strftime('%X')}] Received Action Batch. Processed List: {actions_list}")

    try:
        
    
        clean_actions = [action.split("(", 1)[0].strip() for action in actions_list]

    
        
        # --- FAN CONTROLS ---
        if "open-window" in clean_actions:
            app.root.after(0, lambda: app.update_window("OPEN"))
            payload_str = {"status": "window-open"}
            client.publish(TOPIC_WINDOW_ACT, json.dumps(payload_str), qos=1, retain=True)
        else:
            app.root.after(0, lambda: app.update_window("CLOSED"))
            payload_str = {"status": "window-closed"}
            client.publish(TOPIC_WINDOW_ACT, json.dumps(payload_str), qos=1, retain=True)

        # --- HEATER CONTROLS ---
        if "heater-on" in clean_actions:
            app.root.after(0, lambda: app.update_heater("ON"))
            payload_str = {"status": "heater-on"}
            client.publish(TOPIC_HEATER_ACT, json.dumps(payload_str), qos=1, retain=True)
        else:
            app.root.after(0, lambda: app.update_heater("OFF"))
            payload_str = {"status": "heater-off"}
            client.publish(TOPIC_HEATER_ACT, json.dumps(payload_str), qos=1, retain=True)

    except Exception as e:
        print(f"[-] Failed to process MQTT command action: {e}")

root = tk.Tk()
app = WarehouseUI(root)

client = mqtt.Client()
client.on_message = on_message
client.connect(MQTT_BROKER, 1883, 60)
client.subscribe([(TOPIC_WINDOW, 0), (TOPIC_HEATER, 0)])
client.publish(TOPIC_WINDOW_ACT, "window-closed", qos=1, retain=True)
client.publish(TOPIC_HEATER_ACT, "heater-off", qos=1, retain=True)
client.loop_start()

root.mainloop()