import logging
import os
import re
import sys
import time
import json
import queue
import shutil
import subprocess
from enum import Enum
from typing import Dict, Any, Tuple, List
import tkinter as tk
from tkinter import messagebox, ttk
import random

# --- Graphing Libraries ---
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

# --- External Libraries Placeholder Notification ---
import paho.mqtt.client as mqtt

import smtplib
from email.mime.text import MIMEText

try:
    from unified_planning.io import PDDLReader
    from unified_planning.shortcuts import OneshotPlanner
except ImportError:
    PDDLReader = None
    OneshotPlanner = None

init_conditions_prev=[]
goal_conditions_prev=[]

# --- Email Alert Configuration (SMTP) ---
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")

# Create output directory for logs
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
LOG_FILE = os.path.join(OUTPUT_DIR, "warehouse.log")

# Configure clean logging format for hardware execution to both console and file
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("WarehouseHardwareInterface")



class DeviceType(Enum):
    LIGHT = "light"
    FAN = "fan"
    HUMIDIFIER = "humidifier"
    MOTOR = "motor"


class InventoryManager:
    """Handles core repository logic for warehouse inventory items via a persistent JSON database file."""
    def __init__(self, filename: str = "inventory.json"):
        self.filename = filename
        self._stock: Dict[str, Dict[str, Any]] = {}
        self._load_from_json()

    def _load_from_json(self):
        """Loads repository tracking map data from a JSON file, initializing if missing."""
        if not os.path.exists(self.filename):
            self._stock = {
                "INV-001": {"name": "Standard Warehouse Units", "qty": 500, "min_threshold": 20}
            }
            self._save_to_json()
        else:
            try:
                with open(self.filename, 'r') as f:
                    self._stock = json.load(f)
            except Exception as e:
                logger.error(f"Error loading JSON file, initializing blank schema: {e}")
                self._stock = {}

    def _save_to_json(self):
        """Saves current memory stock values safely out to persistent disk files."""
        try:
            with open(self.filename, 'w') as f:
                json.dump(self._stock, f, indent=4)
        except Exception as e:
            logger.error(f"Failed writing dynamic inventory to storage format: {e}")

    def get_all_items(self) -> Dict[str, Dict[str, Any]]:
        return self._stock

    def update_stock(self, item_id: str, change: int) -> Tuple[bool, str]:
        if item_id not in self._stock:
            return False, "Item ID not found."
        
        new_qty = self._stock[item_id]["qty"] + change
        if new_qty < 0:
            return False, "INSUFFICIENT_STOCK"
        
        self._stock[item_id]["qty"] = new_qty
        self._save_to_json()
        
        if new_qty <= self._stock[item_id]["min_threshold"]:
            return True, f"LOW_STOCK_WARNING: {self._stock[item_id]['name']}"
        
        return True, "Success"


class SmartWarehouseInterfaceGUI:
    """
    Tkinter GUI Interface integrated with hardware Raspberry Pi interactions,
    MQTT hierarchies, and dynamic Inventory Management features.
    """

    def __init__(self, root: tk.Tk, pin_mappings: Dict[str, int] = None):
        self.root = root
        self.root.title("Smart Warehouse Hardware Control Panel")
        self.root.geometry("850x760")  
        self.root.resizable(True, True)

        # Style customization for a cleaner layout look
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure(".", font=("Helvetica", 10))
        self.style.configure("TLabelframe.Label", font=("Helvetica", 10, "bold"), foreground="#2c3e50")
        self.style.configure("Accent.TButton", font=("Helvetica", 10, "bold"), foreground="white", background="#2980b9")
        self.style.map("Accent.TButton", background=[('active', '#3498db'), ('disabled', '#bdc3c7')], foreground=[('disabled', '#7f8c8d')])

        # Initialize Core Managers and History Data Lists for Graphs
        self.inventory_mgr = InventoryManager()
        self.history_limit = 20
        self.temp_history: List[float] = []
        self.humid_history: List[float] = []
        self.time_history: List[str] = []
        
        # Unified tracking properties
        self.delivery_count = 0
        self.is_waiting_for_mqtt = False
        self.active_destination = "None"

        self.alert_email_recipient = "operator@warehouse.com"
        self.base_topic = "building1/floor0/zone1"

        self.latest_sensors: Dict[str, Dict[str, Any]] = {}
        self._pending_deliveries: Dict[str, str] = {}
        self._last_product_present = None
        self._gui_event_queue: "queue.Queue[Tuple[callable, Tuple[Any, ...], Dict[str, Any]]]" = queue.Queue()

        # # Hardware Map Configuration (BCM Pinout Numbering)
        # self.pins = pin_mappings or {
        #     "light1": 3, "fan1": 4, "humid1": 5,
        #     "motor_dir": 7, "motor_step": 8,
        #     "motion_sensor": 17,   
        #     "light_sensor_ch": 0,  
        #     "sound_sensor_ch": 1   
        # }
        
        # self.motor_is_running = False
        self._initial_problem_run = False
        
        # Build UI Elements
        self._setup_ui()
        self.root.after(0, self._drain_gui_queue)
        self._init_mqtt()
        self._run_initial_problem_if_available()
        
        # Start background loops
        self._refresh_telemetry_loop()
        self._fetch_weather_service() 
        self._sync_inventory_to_mqtt()
        
        logger.info("Smart Warehouse Interface initialized.")

    def _init_mqtt(self):
        self.mqtt_client = None
        self.mqtt_connected = False

        if not mqtt:
            logger.warning("paho-mqtt not installed. Running in localized MQTT simulation mode.")
            return

        self.mqtt_host = "192.168.0.199"
        self.mqtt_port = 1883

        client = mqtt.Client(client_id="Warehouse1GUI")
        client.on_connect = self._on_mqtt_connect
        client.on_message = self._on_mqtt_message
        client.on_disconnect = self._on_mqtt_disconnect

        try:
            client.connect(self.mqtt_host, self.mqtt_port)
            client.loop_start()  
            self.mqtt_client = client
        except Exception as e:
            logger.error(f"Cannot connect to MQTT broker {self.mqtt_host}:{self.mqtt_port} — {e}")
            self.mqtt_client = None

    def _enqueue_gui_task(self, callback, *args, **kwargs):
        self._gui_event_queue.put((callback, args, kwargs))

    def _drain_gui_queue(self):
        while not self._gui_event_queue.empty():
            callback, args, kwargs = self._gui_event_queue.get_nowait()
            try:
                callback(*args, **kwargs)
            except Exception as exc:
                logger.exception("GUI queue callback failed: %s", exc)
        self.root.after(50, self._drain_gui_queue)

    def _on_mqtt_connect(self, client, userdata, *args):
        flags = 0
        rc = 0
        properties = None

        if len(args) >= 3:
            flags, rc, properties = args[0], args[1], args[2]
        elif len(args) == 2:
            flags, rc = args[0], args[1]
        elif len(args) == 1:
            rc = args[0]

        if rc == 0:
            self.mqtt_connected = True
            logger.info("Connected to MQTT broker")
            client.subscribe(f"{self.base_topic}/#", qos=0)
            # Also subscribe to delivery_ack so the Pi's confirmation is received
            client.subscribe("delivery_ack", qos=1)
            self._enqueue_gui_task(self._log_to_gui, "[MQTT] Connected and subscribed (sensors + delivery_ack).")
        else:
            self.mqtt_connected = False
            logger.error("MQTT connection failed with code %s", rc)

    def _on_mqtt_disconnect(self, client, userdata, *args):
        self.mqtt_connected = False
        rc = 0
        if args:
            rc = args[-1] if len(args) > 1 else args[0]
            logger.info("MQTT disconnected with code %s", rc)
        self._enqueue_gui_task(self._log_to_gui, "[MQTT] Disconnected from broker.")

    def _on_mqtt_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8", errors="replace")
        self._enqueue_gui_task(self._handle_incoming_mqtt, msg.topic, payload)

    def _handle_incoming_mqtt(self, topic: str, payload: str) -> None:
        print(f"[MQTT SUB] {topic} -> {payload}")
        sub_topic = topic.split("/")[-1]

        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            self._log_to_gui(f"[MQTT SUB] {topic} -> {payload}")
            return

        tokens = topic.split("/")
        if len(tokens) >= 2:
            zone = tokens[-2]
            if isinstance(data, dict):
                data["zone"] = zone

        self.latest_sensors[sub_topic] = data
        self._log_to_gui(f"[MQTT SUB] {topic} -> {payload}")

        self._update_telemetry_labels()

        if sub_topic == "productdetected":
            was_present = getattr(self, "_last_product_present", None)
            now_present = bool(data.get("present"))
            self._last_product_present = now_present
            if was_present and not now_present and getattr(self, "_pending_deliveries", None):
                seq_id, destination = next(iter(self._pending_deliveries.items()))
                self._pending_deliveries.pop(seq_id, None)
                self._on_mqtt_delivery_success_received(seq_id, destination)
        elif sub_topic == "Motors status":
            guide_val = data.get("guide_motor")
            if getattr(self, "_pending_deliveries", None):
                seq_id, destination = next(iter(self._pending_deliveries.items()))
                if (guide_val == "left" and destination == "Frankfurt") or \
                   (guide_val == "right" and destination == "Stuttgart"):
                    self._pending_deliveries.pop(seq_id, None)
                    self._on_mqtt_delivery_success_received(seq_id, destination)
        elif topic == "delivery_ack":
            # Pi publishes here after the guide motor completes its movement.
            # Match by transaction_id to confirm the correct delivery.
            ack_tx_id  = data.get("transaction_id")
            ack_status = data.get("status", "")          # "delivered" or "failed"
            ack_item   = ack_tx_id.split("_")[0] if (ack_tx_id and "_" in ack_tx_id) else "unknown"
            pending    = getattr(self, "_pending_deliveries", {})
            if ack_tx_id and ack_tx_id in pending:
                destination = pending.pop(ack_tx_id)
                if ack_status == "delivered":
                    logger.info("[DELIVERY ACK] %s confirmed delivered (item=%s)", ack_tx_id, ack_item)
                    self._on_mqtt_delivery_success_received(ack_tx_id, destination)
                else:
                    fail_msg = f"[DELIVERY ACK] Pi reported FAILURE for {ack_tx_id} (item={ack_item}). Check actuator."
                    self._log_to_gui(fail_msg)
                    if "delivery_request" in self.latest_sensors:
                        del self.latest_sensors["delivery_request"]
                    # Unlock UI even on failure so operator can retry
                    self.is_waiting_for_mqtt = False
                    self.active_destination = "None"
                    self.btn_left_100.config(state="normal")
                    self.btn_right_100.config(state="normal")
                    self.motor_frame.config(text=" Logistic Dispatch Hub (Ready) ")
                    self._update_telemetry_labels()
            else:
                logger.warning("[DELIVERY ACK] Unknown transaction_id '%s' — ignoring.", ack_tx_id)

    def _pending_destination_for(self, seq_id: str):
        return getattr(self, "_pending_deliveries", {}).pop(seq_id, None)

    def _publish_mqtt(self, sub_topic: str, payload: Any):
        full_topic = f"{self.base_topic}/{sub_topic}"

        if self.mqtt_client and self.mqtt_connected:
            try:
                self.mqtt_client.publish(full_topic, str(payload), qos=0)
                logger.info(f"[MQTT PUB] Topic: {full_topic} -> Payload: {payload}")
            except Exception as e:
                logger.error(f"[MQTT PUB] Failed to publish to {full_topic}: {e}")
        else:
            logger.info(f"[MQTT PUB - SIMULATED, no broker connection] Topic: {full_topic} -> Payload: {payload}")

    def _send_email_alert(self, subject: str, body: str):
        local_msg = f"[EMAIL ALERT] Target: {self.alert_email_recipient} | Subject: {subject} | Body: {body}."
        self._log_to_gui(local_msg)

        if not SMTP_USER or not SMTP_PASS:
            self._log_to_gui("[EMAIL ALERT] SMTP_USER/SMTP_PASS not set -- skipping real send.")
            return

        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = self.alert_email_recipient

        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=5) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_USER, [self.alert_email_recipient], msg.as_string())
            sent_msg = "[EMAIL ALERT] Sent via SMTP."
            self._log_to_gui(sent_msg)
        except Exception as e:
            err_msg = f"[EMAIL ALERT] Failed to send via SMTP: {e}"
            self._log_to_gui(err_msg)

    def _fetch_weather_service(self) -> None:
        self.mock_weather_data = "22°C, Scattered Clouds (OpenWeather API)"
        self.lbl_weather.config(text=f"Outdoor Weather: {self.mock_weather_data}")
        self._publish_mqtt("currentstate", f"Temp: 26.5, Humidity: 35.0, Weather: {self.mock_weather_data}")
        self.root.after(30000, self._fetch_weather_service)

    def _setup_ui(self) -> None:
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=12, pady=8)

        tab_operations = ttk.Frame(notebook)
        tab_graphs = ttk.Frame(notebook)
        tab_inventory = ttk.Frame(notebook)

        notebook.add(tab_operations, text="Operations & Telemetry")
        notebook.add(tab_graphs, text="Live Analytics Dashboard")
        notebook.add(tab_inventory, text="Inventory Dashboard")

        # TAB 1: OPERATIONS & TELEMETRY
        telemetry_frame = ttk.LabelFrame(tab_operations, text=" Warehouse Live Telemetry (MQTT Synchronized) ", padding=12)
        telemetry_frame.pack(fill="x", padx=10, pady=6)

        self.lbl_motion = ttk.Label(telemetry_frame, text="Motion Detection: --", font=("Helvetica", 10, "bold"))
        self.lbl_motion.grid(row=0, column=0, sticky="w", padx=15, pady=6)

        self.lbl_light = ttk.Label(telemetry_frame, text="Ambient Light: --")
        self.lbl_light.grid(row=0, column=1, sticky="w", padx=15, pady=6)

        self.lbl_sound = ttk.Label(telemetry_frame, text="Sound Threshold: --", font=("Helvetica", 10, "bold"))
        self.lbl_sound.grid(row=1, column=0, sticky="w", padx=15, pady=6)

        self.lbl_temp = ttk.Label(telemetry_frame, text="Current Temp: --°C")
        self.lbl_temp.grid(row=1, column=1, sticky="w", padx=15, pady=6)

        self.lbl_humidity = ttk.Label(telemetry_frame, text="Humidity Level: --%")
        self.lbl_humidity.grid(row=2, column=0, sticky="w", padx=15, pady=6)

        # self.lbl_motor = ttk.Label(telemetry_frame, text="Stepper Motor: [ STOPPED ]", foreground="#c0392b", font=("Helvetica", 10, "bold"))
        # self.lbl_motor.grid(row=2, column=1, sticky="w", padx=15, pady=6)

        self.lbl_weather = ttk.Label(telemetry_frame, text="Outdoor Weather: Fetching...", foreground="#2980b9", font=("Helvetica", 10, "italic"))
        self.lbl_weather.grid(row=3, column=0, columnspan=2, sticky="w", padx=15, pady=8)

        self.lbl_product = ttk.Label(telemetry_frame, text="Product Detected: --")
        self.lbl_product.grid(row=4, column=0, sticky="w", padx=15, pady=6)

        self.lbl_ultrasonic = ttk.Label(telemetry_frame, text="Ultrasonic (calibrated): --")
        self.lbl_ultrasonic.grid(row=4, column=1, sticky="w", padx=15, pady=6)

        # Logistic Delivery Destination Clusters
        self.motor_frame = ttk.LabelFrame(tab_operations, text=" Logistic Dispatch Hub (Awaiting MQTT Confirmation) ", padding=12)
        self.motor_frame.pack(fill="x", padx=10, pady=6)

        self.btn_left_100 = ttk.Button(self.motor_frame, text="📍 Deliver to Frankfurt", style="Accent.TButton", 
                                  command=lambda: self._execute_delivery(destination="Frankfurt", mqtt_payload="deliver_left", is_clockwise=False))
        self.btn_left_100.pack(side="left", fill="x", expand=True, padx=8, pady=6)

        self.btn_right_100 = ttk.Button(self.motor_frame, text="Deliver to Stuttgart 📍", style="Accent.TButton", 
                                   command=lambda: self._execute_delivery(destination="Stuttgart", mqtt_payload="deliver_right", is_clockwise=True))
        self.btn_right_100.pack(side="right", fill="x", expand=True, padx=8, pady=6)

        # Operator Panel Control Frame
        control_frame = ttk.LabelFrame(tab_operations, text=" Operator Panel Controls ", padding=12)
        control_frame.pack(fill="x", padx=10, pady=6)

        ttk.Button(control_frame, text="❌ Exit Control Panel", command=self.root.quit).pack(fill="x", pady=4)

        # TAB 2: LIVE ANALYTICS
        graph_frame = ttk.LabelFrame(tab_graphs, text=" Real-Time Environmental Metrics ", padding=12)
        graph_frame.pack(fill="both", expand=True, padx=10, pady=6)

        self.fig = Figure(figsize=(6, 4), dpi=100)
        self.ax_temp = self.fig.add_subplot(211)
        self.ax_humid = self.fig.add_subplot(212)
        self.fig.tight_layout(pad=3.0)

        self.line_temp, = self.ax_temp.plot([], [], color="#d35400", label="Temperature (°C)")
        self.line_humid, = self.ax_humid.plot([], [], color="#16a085", label="Humidity (%)")

        self.ax_temp.set_title("Live Temperature Log")
        self.ax_temp.set_ylabel("°C")
        self.ax_humid.set_title("Live Humidity Log")
        self.ax_humid.set_ylabel("%")

        self.canvas = FigureCanvasTkAgg(self.fig, master=graph_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # TAB 3: INVENTORY MANAGEMENT
        inv_display_frame = ttk.LabelFrame(tab_inventory, text=" Current Stock Tracking ", padding=12)
        inv_display_frame.pack(fill="both", expand=True, padx=10, pady=6)

        self.inv_tree = ttk.Treeview(inv_display_frame, columns=("ID", "Name", "Qty", "Min"), show="headings", height=8)
        self.inv_tree.heading("ID", text="Item ID")
        self.inv_tree.heading("Name", text="Description")
        self.inv_tree.heading("Qty", text="Quantity")
        self.inv_tree.heading("Min", text="Alert Threshold")
        self.inv_tree.column("ID", width=100, anchor="center")
        self.inv_tree.column("Qty", width=100, anchor="center")
        self.inv_tree.column("Min", width=120, anchor="center")
        self.inv_tree.pack(fill="both", expand=True)

        self._populate_inventory_tree()

        inv_action_frame = ttk.LabelFrame(tab_inventory, text=" Inventory Adjustments ", padding=12)
        inv_action_frame.pack(fill="x", padx=10, pady=6)

        ttk.Label(inv_action_frame, text="Change Amount:").pack(side="left", padx=8)
        self.ent_qty_change = ttk.Entry(inv_action_frame, width=8)
        self.ent_qty_change.insert(0, "10")
        self.ent_qty_change.pack(side="left", padx=8)

        ttk.Button(inv_action_frame, text="➕ Restock Selected", command=lambda: self._handle_stock_adjust(1)).pack(side="left", padx=6)
        ttk.Button(inv_action_frame, text="➖ Dispatch Selected", command=lambda: self._handle_stock_adjust(-1)).pack(side="left", padx=6)

        # SHARED CONSOLE LOG OUTPUT
        log_frame = ttk.LabelFrame(self.root, text=" MQTT Broadcast & Execution Output Log ", padding=12)
        log_frame.pack(fill="both", expand=True, padx=12, pady=8)

        self.log_box = tk.Text(log_frame, height=5, state="disabled", wrap="word", background="#2c3e50", foreground="#ecf0f1", font=("Courier", 10))
        self.log_box.pack(fill="both", expand=True, side="left")
        
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_box.yview)
        scrollbar.pack(fill="y", side="right")
        self.log_box.configure(yscrollcommand=scrollbar.set)

    def _populate_inventory_tree(self):
        for item in self.inv_tree.get_children():
            self.inv_tree.delete(item)
        for item_id, details in self.inventory_mgr.get_all_items().items():
            self.inv_tree.insert("", tk.END, values=(item_id, details["name"], details["qty"], details["min_threshold"]))

    def _handle_stock_adjust(self, direction: int):
        selected = self.inv_tree.selection()
        if not selected:
            return

        try:
            delta = int(self.ent_qty_change.get()) * direction
        except ValueError:
            return

        item_id = self.inv_tree.item(selected[0])["values"][0]
        success, info = self.inventory_mgr.update_stock(item_id, delta)

        if success:
            self._populate_inventory_tree()
            self._sync_inventory_to_mqtt()
            self._log_to_gui(f"[INVENTORY] Adjusted {item_id} stock by {delta} (Saved to JSON).")
            if "LOW_STOCK_WARNING" in info:
                self._send_email_alert("Inventory Alert: Low Stock", f"Item {item_id} has fallen below threshold limits.")

    def _sync_inventory_to_mqtt(self):
        payload_summary = {item_id: data["qty"] for item_id, data in self.inventory_mgr.get_all_items().items()}
        self._publish_mqtt("inventory", str(payload_summary))

    def _log_to_gui(self, message: str) -> None:
        # Also write all GUI logs to the file and stdout logger
        logger.info(message)

        # Check if the scrollbar is currently at the very bottom (1.0 or very close to it)
        at_bottom = self.log_box.yview()[1] >= 0.99

        self.log_box.configure(state="normal")
        self.log_box.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {message}\n")
        
        # Only auto-scroll down if the user was already at the bottom
        if at_bottom:
            self.log_box.see(tk.END) 
            
        self.log_box.configure(state="disabled")

    def actions_mqtt_publish(self,payload):
        self._publish_mqtt("actions", payload)
        self._log_to_gui(f"[MQTT PUB] actions -> {payload}")

    def run_planner(self, domain_dir, problem_dir):
        """
        Executes the Fast Downward planner using Unified Planning.
        """
        if not os.path.exists(domain_dir):
            self._log_to_gui(f"[PLANNER] Domain file not found: {domain_dir}")
            return

        if not os.path.exists(problem_dir):
            self._log_to_gui(f"[PLANNER] Problem file not found: {problem_dir}")
            return

        if PDDLReader is None or OneshotPlanner is None:
            self._log_to_gui("[PLANNER] unified_planning is not available. Install it to run the planner.")
            return

        self._log_to_gui(f"[PLANNER] Using Unified Planning with Fast Downward for {problem_dir}")

        try:
            reader = PDDLReader()
            problem = reader.parse_problem(domain_dir, problem_dir)

            with OneshotPlanner(name="fast-downward") as planner:
                result = planner.solve(problem)

            output_plan = os.path.join(os.path.dirname(problem_dir), f"plan_{os.path.basename(problem_dir)}.txt")

            status_name = getattr(getattr(result, "status", None), "name", None)
            if status_name in {"SOLVED_SATISFICING", "SOLVED_OPTIMALLY"}:
                plan_actions = [str(action) for action in getattr(getattr(result, "plan", None), "actions", [])]
                plan_text = "\n".join(plan_actions) if plan_actions else "No actions generated."
                with open(output_plan, "w", encoding="utf-8") as f:
                    f.write(plan_text)

                for action in plan_actions:
                    self._log_to_gui(f"[PLANNER] {action}")
                self.actions_mqtt_publish(plan_text)
                self._log_to_gui(f"[PLANNER] Finished planning for {problem_dir}. Plan saved to {output_plan}")
            else:
                with open(output_plan, "w", encoding="utf-8") as f:
                    f.write("No plan found.")
                self._log_to_gui(f"[PLANNER] No plan found for {problem_dir}.")
        except Exception as e:
            self._log_to_gui(f"[PLANNER] Error during planning execution: {e}")

    def _run_initial_problem_if_available(self) -> None:
        pddl_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pddl"))
        domain_path = os.path.join(pddl_dir, "domain.pddl")
        initial_problem_path = os.path.join(pddl_dir, "problem_1.pddl")

        if self._initial_problem_run:
            return

        if os.path.exists(domain_path) and os.path.exists(initial_problem_path):
            self._log_to_gui("[PLANNER] First startup detected; running existing problem_1.pddl.")
            self.run_planner(domain_path, initial_problem_path)
            self._initial_problem_run = True


    def generate_pddl_problem(
        self,
        init_conditions: List[str],
        goal_conditions: List[str],
        zone,  # Now handled as a set/iterable of zones
        item_name) -> str:
        
        pddl_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pddl"))
        os.makedirs(pddl_dir, exist_ok=True)

        domain_path = os.path.join(pddl_dir, "domain.pddl")
        if not os.path.exists(domain_path):
            raise FileNotFoundError(f"Domain file not found: {domain_path}")

        with open(domain_path, "r", encoding="utf-8") as f:
            domain_text = f.read()

        domain_match = re.search(r"\(define\s*\(domain\s+([^\s\)]+)\)", domain_text)
        domain_name = domain_match.group(1) if domain_match else "smart-zone-control"

        problem_files = [name for name in os.listdir(pddl_dir) if re.fullmatch(r"problem_(\d+)\.pddl", name)]
        numbers = []
        for name in problem_files:
            match = re.fullmatch(r"problem_(\d+)\.pddl", name)
            if match:
                numbers.append(int(match.group(1)))
        next_number = max(numbers) + 1 if numbers else 1
        problem_filename = f"problem_{next_number}.pddl"
        problem_path = os.path.join(pddl_dir, problem_filename)

        # 1. Convert set to a sorted list so PDDL output order remains deterministic
        zones = sorted(list(zone)) if zone else ["zone1"]


        item_name = item_name or "item1"

        # 2. Add required zone-in-building facts for all zones to init_conditions
        for z in reversed(zones):  # Reversed so they prepend in the correct logical order
            required_zone_fact = f"(zone-in-building {z} building1)"
            if required_zone_fact not in init_conditions:
                init_conditions = [required_zone_fact] + init_conditions

        # 3. Format the multiple zone objects for the PDDL block
        zones_objects_block = "\n    ".join(f"{z} - zone" for z in zones)

        init_block = "\n      ".join(init_conditions)
        goal_block = "\n      ".join(goal_conditions) if goal_conditions else ""

        problem_text = (
            ";; Auto-generated problem file\n"
            f"(define (problem problem_{next_number})\n"
            f"  (:domain {domain_name})\n\n"
            "  (:objects\n"
            "    building1 - building\n"
            f"    {zones_objects_block}\n"  # Renders each zone on its own line
            f"    {item_name} - item\n"
            "  )\n\n"
            "  (:init\n"
            f"    {init_block}\n"
            "  )\n\n"
            "  (:goal\n"
            "    (and\n"
            f"      {goal_block}\n"
            "    )\n"
            "  )\n"
            ")\n"
        )

        with open(problem_path, "w", encoding="utf-8") as f:
            f.write(problem_text)

        self._log_to_gui(f"Generated PDDL problem: {problem_filename}")
        
        self.run_planner(domain_path, problem_path)


    def aiplanner(
        self,
        temperature,
        humidity,
        light,
        sound,
        motion,
        product,
        ultrasonic,
        delivery_request,
        motors_status=None ):

        # Placeholder for AI planning logic based on sensor inputs
        pddl_init = []
        pddl_goals = []
        zone=set()
        global init_conditions_prev, goal_conditions_prev

        if delivery_request and isinstance(delivery_request, dict):
            item_name = f"item_{delivery_request.get('transaction_id', '1')}"
        else:
            # Predict the next item ID based on current delivery count
            next_count = getattr(self, "delivery_count", 0) + 1
            item_name = f"item_INV-001_{next_count}"

        if light:
            if motion["value"]:
                zone.add(motion['zone'])
                # FIX: Wrap predicate in parentheses ( )
                pddl_init.append(f"(motion-detected {motion['zone']})")
                zone.add(light['zone'])
                if(light["raw"] >= light["lighthigh_threshold"]):
                    
                    pddl_init.append(f"(light-high {light['zone']})")
                    pddl_goals.append(f"(not (led-on {light['zone']}))")

                elif(light["raw"] >= light["lightlow_threshold"] and light["raw"] < light["lighthigh_threshold"]):
                    
                    pddl_init.append(f"(light-normal {light['zone']})")
                    pddl_goals.append(f"(led-on {light['zone']})")

                else:
                    
                    pddl_init.append(f"(light-low {light['zone']})")
                    pddl_goals.append(f"(led-on {light['zone']})")

            else:
                zone.add(light['zone'])
                
                pddl_goals.append(f"(not (led-on {light['zone']}))")

                if(light["raw"] >= light["lighthigh_threshold"]):
                    pddl_init.append(f"(light-high {light['zone']})")

                elif(light["raw"] >= light["lightlow_threshold"] and light["raw"] < light["lighthigh_threshold"]):
                    pddl_init.append(f"(light-normal {light['zone']})")

                else:
                    pddl_init.append(f"(light-low {light['zone']})")

        if temperature:
            zone.add(temperature['zone'])
            if(temperature["temperature_c"] >= temperature["threshold"]):
                
                pddl_init.append(f"(temperature-high {temperature['zone']})")
                pddl_goals.append(f"(fan-on {temperature['zone']})")
            else:
                
                pddl_init.append(f"(temperature-normal {temperature['zone']})")
                pddl_goals.append(f"(not (fan-on {temperature['zone']}))")

        if humidity:
            zone.add(humidity['zone'])
            if(humidity["humidity_pct"] >= humidity["threshold"]):
                
                pddl_init.append(f"(humidity-normal {humidity['zone']})")
                pddl_goals.append(f"(not (humidifier-on {humidity['zone']}))")
            else:
                
                pddl_init.append(f"(humidity-low {humidity['zone']})")
                pddl_goals.append(f"(humidifier-on {humidity['zone']})")

        if sound:
            zone.add(sound['zone'])
            if(sound["raw_max"] >= sound["threshold"]):
                
                pddl_init.append(f"(sound-high {sound['zone']})")
                pddl_goals.append(f"(send-notification {sound['zone']})")

        if ultrasonic:
            zone.add(ultrasonic['zone'])
            if ultrasonic["raw"] <= ultrasonic["threshold"]:
                # Product detected — planner will see product-available and choose
                # open-gate -> guide-left/right -> delivery-request-handled
                pddl_init.append(f"(product-available {item_name} {ultrasonic['zone']})")
            # If NOT detected — we simply omit product-available from :init.
            # The planner will then autonomously pick notify-unavailable-left/right
            # because open-gate requires (product-available ...) as a precondition.

        if delivery_request:
            zone.add(delivery_request['zone'])
            if delivery_request["command"] == "deliver_left":
                pddl_init.append(f"(delivery-requested-left {item_name} {delivery_request['zone']})")
            elif delivery_request["command"] == "deliver_right":
                pddl_init.append(f"(delivery-requested-right {item_name} {delivery_request['zone']})")

            # Single stable goal — the planner decides whether to deliver or notify.
            # Python never pre-computes the outcome anymore.
            pddl_goals.append(f"(delivery-request-handled {item_name} {delivery_request['zone']})")

        # Motor status (gate_motor, guide_motor) is tracked via MQTT in
        # self.latest_sensors["Motors status"] for monitoring/display purposes.
        # We do NOT translate motor states into PDDL init facts here —
        # the planner decides what actions to take based on delivery requests and goals.


        if init_conditions_prev != pddl_init or goal_conditions_prev != pddl_goals:
            init_conditions_prev = pddl_init
            goal_conditions_prev = pddl_goals
            self._log_to_gui("pddl_init - " + str(pddl_init))
            self._log_to_gui("pddl_goals - " + str(pddl_goals))
            self.generate_pddl_problem(pddl_init, pddl_goals, zone, item_name)
        else:
            self._log_to_gui("No changes in conditions; skipping PDDL generation.")
            
    def read_environment_sensors(self) -> Dict[str, Any]:

        temperature = self.latest_sensors.get("temperature")
        humidity = self.latest_sensors.get("humidity")
        motion = self.latest_sensors.get("motiondetected")
        light = self.latest_sensors.get("light")
        sound = self.latest_sensors.get("sound")
        product = self.latest_sensors.get("productdetected")
        ultrasonic = self.latest_sensors.get("ultrasonic")
        delivery_request = self.latest_sensors.get("delivery_request")
        motors_status = self.latest_sensors.get("Motors status")


        self.aiplanner(
            temperature=temperature,
            humidity=humidity,
            light=light,
            sound=sound,
            motion=motion,
            product=product,
            ultrasonic=ultrasonic,
            delivery_request=delivery_request,
            motors_status=motors_status
        )

        current_temp = 0
        current_humid = 0
        motion_state = False
        light_label = "Unknown"
        sound_label = "Unknown"
        product_present = None
        ultrasonic_val = None


        if isinstance(temperature, dict):
            temp_value = temperature.get("temperature_c")
            if temp_value is not None:
                current_temp = temp_value

        if isinstance(humidity, dict):
            hum_value = humidity.get("humidity_pct")
            if hum_value is not None:
                current_humid = hum_value

        if isinstance(motion, dict):
            motion_state = bool(motion.get("value", False))

        if isinstance(light, dict):
            raw_value = light.get("raw")
            high_threshold = light.get("lighthigh_threshold")
            low_threshold = light.get("lightlow_threshold")

            if raw_value is not None:
                if high_threshold is not None and raw_value >= high_threshold:
                    light_label = "Bright"
                elif low_threshold is not None and raw_value >= low_threshold:
                    light_label = "Normal"
                else:
                    light_label = "Low"

        if isinstance(sound, dict):
            raw_value = sound.get("raw_max")
            threshold = sound.get("threshold")
            if raw_value is not None and threshold is not None:
                sound_label = "High" if raw_value >= threshold else "Low"
            elif raw_value is not None:
                sound_label = "High" if raw_value > 0 else "Low"

        if isinstance(product, dict):
            product_present = product.get("present")
            if product_present is not None:
                product_present = bool(product_present)

        if isinstance(ultrasonic, dict):
            ultrasonic_val = ultrasonic.get("raw")

        return {
            "light_level": light_label,
            "sound_level": sound_label,
            "temperature": current_temp,
            "humidity": current_humid,
            "motion_detected": motion_state,
            "product_present": product_present,
            "ultrasonic": ultrasonic_val,
            "delivery_request": delivery_request,
        }

    def _update_plots(self, current_time: str, temp: float, humid: float):
        self.time_history.append(current_time)
        self.temp_history.append(temp)
        self.humid_history.append(humid)

        if len(self.time_history) > self.history_limit:
            self.time_history.pop(0)
            self.temp_history.pop(0)
            self.humid_history.pop(0)

        self.ax_temp.cla()
        self.ax_humid.cla()

        x_indices = list(range(len(self.time_history)))

        self.ax_temp.plot(x_indices, self.temp_history, color="#d35400", marker=".", linewidth=2)
        self.ax_temp.set_title("Live Temperature Stream (°C)")
        self.ax_temp.grid(True, linestyle="--", alpha=0.5)
        self.ax_temp.set_xticks(x_indices)
        self.ax_temp.set_xticklabels(self.time_history)
        self.ax_temp.tick_params(axis='x', rotation=35, labelsize=8)

        self.ax_humid.plot(x_indices, self.humid_history, color="#16a085", marker=".", linewidth=2)
        self.ax_humid.set_title("Live Humidity Stream (%)")
        self.ax_humid.grid(True, linestyle="--", alpha=0.5)
        self.ax_humid.set_xticks(x_indices)
        self.ax_humid.set_xticklabels(self.time_history)
        self.ax_humid.tick_params(axis='x', rotation=35, labelsize=8)

        self.fig.tight_layout()
        self.canvas.draw()

    def _update_telemetry_labels(self) -> None:
        """Refreshes the on-screen labels in real-time."""
        data = self.read_environment_sensors()

        motion_str = "[ ACTIVE ]" if data["motion_detected"] else "[ CLEAR ]"
        self.lbl_motion.config(text=f"Motion Detection: {motion_str}", foreground="#c0392b" if data["motion_detected"] else "#27ae60")
        self.lbl_sound.config(text=f"Sound Threshold: {data['sound_level']}", foreground="#c0392b" if data["sound_level"] == "High" else "black")

        self.lbl_light.config(text=f"Ambient Light: {data['light_level']}")
        self.lbl_temp.config(text=f"Current Temp: {data['temperature']}°C")
        self.lbl_humidity.config(text=f"Humidity Level: {data['humidity']}%")

        if data["product_present"] is not None:
            product_str = "[ PRESENT ]" if data["product_present"] else "[ ABSENT ]"
            self.lbl_product.config(text=f"Product Detected: {product_str}", foreground="#27ae60" if data["product_present"] else "#7f8c8d")

        if data["ultrasonic"] is not None:
            self.lbl_ultrasonic.config(text=f"Ultrasonic (calibrated): {data['ultrasonic']}")

        # # Build clean real-time binary state representation for current_state.json
        # export_states = {
        #     "light_state": data["light_level"],
        #     "sound_state": data["sound_level"],
        #     "temperature_state": "High" if data["temperature"] > 30.0 else "Low",
        #     "humidity_state": "High" if data["humidity"] > 50.0 else "Low",
        #     "motion_detected": bool(data["motion_detected"]),
        #     "destination": self.active_destination
        # }

        # try:
        #     with open("current_state.json", "w") as f:
        #         json.dump(export_states, f, indent=4)
        # except Exception as e:
        #     logger.error(f"Failed to write real-time state parameters: {e}")

    def _refresh_telemetry_loop(self) -> None:
        try:
            data = self.read_environment_sensors()
            ts = time.strftime('%H:%M:%S')

            self._update_plots(ts, data["temperature"], data["humidity"])
            self._update_telemetry_labels()

            if data["sound_level"] == "High":
                self._send_email_alert("Dangerously High Sound Level", f"Alert! Sound registered as {data['sound_level']}.")

            # if self.motor_is_running:
            #     self.lbl_motor.config(text="Stepper Motor: [ RUNNING ]", foreground="#27ae60")
            # else:
            #     self.lbl_motor.config(text="Stepper Motor: [ STOPPED ]", foreground="#c0392b")
        except Exception as exc:
            logger.exception("Telemetry refresh failed: %s", exc)

        self.root.after(4000, self._refresh_telemetry_loop)

    def _execute_delivery(self, destination: str, mqtt_payload: str, is_clockwise: bool) -> None:
        if self.is_waiting_for_mqtt:
            return

        # -------------------------------------------------------
        # Step 1: Ultrasonic pre-check — confirm product is present
        # before touching inventory or publishing anything.
        # This mirrors the PDDL domain's open-gate precondition:
        #   (product-available ?i ?z)
        # and the notify-unavailable-left/right actions.
        # -------------------------------------------------------
        ultrasonic_data = self.latest_sensors.get("ultrasonic")
        product_data    = self.latest_sensors.get("productdetected")

        product_physically_present = False
        if isinstance(ultrasonic_data, dict):
            raw       = ultrasonic_data.get("raw")
            threshold = ultrasonic_data.get("threshold")
            if raw is not None and threshold is not None:
                product_physically_present = (raw <= threshold)
            elif raw is not None:
                product_physically_present = (raw > 0)
        elif isinstance(product_data, dict):
            # Fall back to binary product-detected flag if ultrasonic not yet received
            product_physically_present = bool(product_data.get("present", False))

        if not product_physically_present:
            # PDDL equivalent: notify-unavailable-left / notify-unavailable-right
            no_product_msg = (
                f"⚠️  No product detected in the dispatch zone!\n\n"
                f"Destination:  {destination}\n"
                f"Direction:    {'Left (Frankfurt)' if 'left' in mqtt_payload else 'Right (Stuttgart)'}\n\n"
                "Please place a package before retrying."
            )
            logger.warning("[DELIVERY ABORT] %s — no product detected by ultrasonic sensor.", destination)
            self._log_to_gui(f"[DELIVERY ABORT] No product detected. Dispatch to {destination} cancelled.")
            messagebox.showwarning("No Product Detected", no_product_msg)
            return  # Abort — do NOT deduct stock or publish MQTT

        # Clear any old/stale actuator feedback when beginning a new request
        if "Motors status" in self.latest_sensors:
            del self.latest_sensors["Motors status"]

        # -------------------------------------------------------
        # Step 2: Product confirmed — deduct inventory
        # -------------------------------------------------------
        item_id = "INV-001"
        
        success, info = self.inventory_mgr.update_stock(item_id, -1)
        if not success:
            err_msg = f"[INVENTORY ABORT] Cannot dispatch to {destination}. Reason: Zero or Insufficient stock balance."
            self._log_to_gui(err_msg)
            return
            
        # -------------------------------------------------------
        # Step 3: Lock UI and publish delivery_request over MQTT
        # -------------------------------------------------------
        self.is_waiting_for_mqtt = True
        self.active_destination = destination
        self.btn_left_100.config(state="disabled")
        self.btn_right_100.config(state="disabled")
        self.motor_frame.config(text=" Logistic Dispatch Hub (LOCKOUT: Awaiting Confirmation) ")

        self._populate_inventory_tree()
        self._sync_inventory_to_mqtt()
        self._update_telemetry_labels()  # Instantly refresh destination state out to JSON file
        
        if "LOW_STOCK_WARNING" in info:
            self._send_email_alert("Inventory Alert: Low Stock Warning", f"Item {item_id} has breached threshold parameters.")

        self.delivery_count += 1
        seq_id = f"{item_id}_{self.delivery_count}"

        msg = f"[LOGISTICS] Dispatching {destination}. Transaction ID: {seq_id} (Awaiting Callback...)"
        self._log_to_gui(msg)

        delivery_payload = json.dumps({
            "command": mqtt_payload,          # "deliver_left" or "deliver_right"
            "transaction_id": seq_id,
            "destination": destination,
        })
        self._publish_mqtt("delivery_request", delivery_payload)

        if not hasattr(self, "_pending_deliveries"):
            self._pending_deliveries = {}
        self._pending_deliveries[seq_id] = destination

        if not (self.mqtt_client and self.mqtt_connected):
            self.root.after(2500, lambda: self._on_mqtt_delivery_success_received(
                seq_id, self._pending_deliveries.pop(seq_id, destination)))

    def _on_mqtt_delivery_success_received(self, transaction_id: str, destination: str):
        success_msg = f"[MQTT SUB] Received Success Acknowledgment back for {transaction_id} at {destination}."
        self._log_to_gui(success_msg)

        if "delivery_request" in self.latest_sensors:
            del self.latest_sensors["delivery_request"]

        self.is_waiting_for_mqtt = False
        self.active_destination = "None"
        self.btn_left_100.config(state="normal")
        self.btn_right_100.config(state="normal")
        self.motor_frame.config(text=" Logistic Dispatch Hub (Ready) ")
        self._update_telemetry_labels()  # Return destination state back to "None"

    def _send_notification(self, zone: str) -> bool:
        payload = {"zone": zone, "alert": "Dangerously High Sound Level"}
        msg = f"[NOTIFICATION] Alert dispatched: {payload}"
        self._log_to_gui(msg)
        return True


def on_close_clean(app_interface: SmartWarehouseInterfaceGUI, root_window: tk.Tk):
    #app_interface.execute_action("stop-motor", ())
    if getattr(app_interface, "mqtt_client", None):
        try:
            app_interface.mqtt_client.loop_stop()
            app_interface.mqtt_client.disconnect()
        except Exception:
            pass
    root_window.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    warehouse_gui = SmartWarehouseInterfaceGUI(root)
    root.protocol("WM_DELETE_WINDOW", lambda: on_close_clean(warehouse_gui, root))
    
    try:
        root.mainloop()
    except KeyboardInterrupt:
        # warehouse_gui.execute_action("stop-motor", ())
        if getattr(warehouse_gui, "mqtt_client", None):
            try:
                warehouse_gui.mqtt_client.loop_stop()
                warehouse_gui.mqtt_client.disconnect()
            except Exception:
                pass
        sys.exit(0)