# Complete Smart Warehouse UI
# Replace your current GUI source with this file.

import json
import logging
import os
import re
import queue
import sys
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Tuple
import tkinter as tk
from tkinter import messagebox, ttk

from pathlib import Path

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

try:
    from unified_planning.io import PDDLReader
    from unified_planning.shortcuts import OneshotPlanner
except ImportError:
    PDDLReader = None
    OneshotPlanner = None

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

run_timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
LOG_FILE = os.path.join(
    OUTPUT_DIR,
    f"warehouse_{run_timestamp}.log",
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger("WarehouseHardwareInterface")

init_conditions_prev: list[str] = []
goal_conditions_prev: list[str] = []


class InventoryManager:
    def __init__(self, filename: str = "inventory.json"):
        self.filename = filename
        self._stock: Dict[str, Dict[str, Any]] = {}
        self._load_from_json()

    def _load_from_json(self) -> None:
        if not os.path.exists(self.filename):
            self._stock = {"INV-001": {"name": "Standard Warehouse Units", "qty": 500, "min_threshold": 20}}
            self._save_to_json()
            return
        try:
            with open(self.filename, "r", encoding="utf-8") as file:
                self._stock = json.load(file)
        except Exception as exc:
            logger.error("Inventory load failed: %s", exc)
            self._stock = {}

    def _save_to_json(self) -> None:
        try:
            with open(self.filename, "w", encoding="utf-8") as file:
                json.dump(self._stock, file, indent=4)
        except Exception as exc:
            logger.error("Inventory save failed: %s", exc)

    def get_all_items(self) -> Dict[str, Dict[str, Any]]:
        return self._stock

    def update_stock(self, item_id: str, change: int) -> Tuple[bool, str]:
        if item_id not in self._stock:
            return False, "Item ID not found"
        new_qty = self._stock[item_id]["qty"] + change
        if new_qty < 0:
            return False, "INSUFFICIENT_STOCK"
        self._stock[item_id]["qty"] = new_qty
        self._save_to_json()
        if new_qty <= self._stock[item_id]["min_threshold"]:
            return True, "LOW_STOCK_WARNING"
        return True, "Success"


class SmartWarehouseInterfaceGUI:
    def __init__(self, root: tk.Tk, pin_mappings: Dict[str, int] | None = None):
        self.root = root
        self.root.title("Smart Warehouse Control Panel")
        self.root.geometry("1050x780")
        self.root.minsize(900, 700)
        self.root.resizable(True, True)

        self.style = ttk.Style()
        self.night_mode = False
        self.weather_simulated = False
        self.inventory_mgr = InventoryManager()
        self.history_limit = 20
        self.temp_history: List[float] = []
        self.humid_history: List[float] = []
        self.time_history: List[str] = []
        self.delivery_count = 0
        self.is_waiting_for_mqtt = False
        self.active_destination: str | None = None
        self.base_topic = "building1/floor0/zone1"
        self.latest_sensors: Dict[str, Dict[str, Any]] = {}
        self._pending_deliveries: Dict[str, str] = {}
        self._last_product_present = None
        self._gui_event_queue: queue.Queue = queue.Queue()
        self.mqtt_client = None
        self.mqtt_connected = False
        self.log_visible = True

        self._setup_ui()
        self.root.after(0, self._drain_gui_queue)
        self._init_mqtt()
        self._run_initial_problem_if_available()
        self._fetch_weather_service()
        self._refresh_telemetry_loop()
        
        self._sync_inventory_to_mqtt()
        logger.info("Smart Warehouse interface initialized")

    def _configure_ui_style(self) -> None:
        self.colors = {"bg": "#F5F7FA", "surface": "#FFFFFF", "surface_alt": "#EEF3F8", "text": "#172033", "muted": "#667085", "primary": "#1479B8", "primary_hover": "#0E639A", "success": "#16865B", "danger": "#C33B3B", "log_bg": "#152334", "log_fg": "#DDE8F2"}
        self.root.configure(bg=self.colors["bg"])
        self.style.theme_use("clam")
        self.style.configure(".", font=("Segoe UI", 10), background=self.colors["bg"], foreground=self.colors["text"])
        self.style.configure("TFrame", background=self.colors["bg"])
        self.style.configure("Card.TFrame", background=self.colors["surface"], relief="solid", borderwidth=1)
        self.style.configure("Section.TLabelframe", background=self.colors["bg"], borderwidth=1, relief="solid")
        self.style.configure("Section.TLabelframe.Label", background=self.colors["bg"], foreground=self.colors["text"], font=("Segoe UI Semibold", 10))
        self.style.configure("Title.TLabel", background=self.colors["bg"], foreground=self.colors["text"], font=("Segoe UI Semibold", 18))
        self.style.configure("Subtitle.TLabel", background=self.colors["bg"], foreground=self.colors["muted"], font=("Segoe UI", 9))
        self.style.configure("CardTitle.TLabel", background=self.colors["surface"], foreground=self.colors["muted"], font=("Segoe UI", 9))
        self.style.configure("CardValue.TLabel", background=self.colors["surface"], foreground=self.colors["text"], font=("Segoe UI Semibold", 13))
        self.style.configure("Status.TLabel", background=self.colors["surface_alt"], foreground=self.colors["primary"], font=("Segoe UI Semibold", 10), padding=(12, 7))
        self.style.configure("Primary.TButton", font=("Segoe UI Semibold", 10), foreground="white", background=self.colors["primary"], padding=(12, 10), borderwidth=0)
        self.style.map("Primary.TButton", background=[("active", self.colors["primary_hover"]), ("disabled", "#A9B8C5")])
        self.style.configure("Secondary.TButton", font=("Segoe UI Semibold", 10), foreground=self.colors["text"], background=self.colors["surface_alt"], padding=(12, 9), borderwidth=1)
        self.style.configure("Danger.TButton", font=("Segoe UI Semibold", 10), foreground="white", background=self.colors["danger"], padding=(12, 9), borderwidth=0)
        self.style.configure("TNotebook.Tab", padding=(14, 9), font=("Segoe UI Semibold", 10), background="#E7ECF2", foreground=self.colors["muted"])
        self.style.map("TNotebook.Tab", background=[("selected", self.colors["surface"])], foreground=[("selected", self.colors["primary"])])
        self.style.configure("Treeview", rowheight=30, font=("Segoe UI", 10), background=self.colors["surface"], fieldbackground=self.colors["surface"])
        self.style.configure("Treeview.Heading", font=("Segoe UI Semibold", 10), background=self.colors["surface_alt"], foreground=self.colors["text"])

    def _telemetry_card(self, parent, row: int, column: int, title: str, initial: str = "—") -> ttk.Label:
        card = ttk.Frame(parent, style="Card.TFrame", padding=(14, 11))
        card.grid(row=row, column=column, sticky="nsew", padx=5, pady=5)
        ttk.Label(card, text=title.upper(), style="CardTitle.TLabel").pack(anchor="w")
        value = ttk.Label(card, text=initial, style="CardValue.TLabel")
        value.pack(anchor="w", pady=(5, 0))
        return value

    def _setup_ui(self) -> None:
        self._configure_ui_style()
        main = ttk.Frame(self.root, padding=(16, 14))
        main.pack(fill="both", expand=True)
        header = ttk.Frame(main)
        header.pack(fill="x", pady=(0, 12))
        left = ttk.Frame(header)
        left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text="Smart Warehouse", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="Operations, telemetry, inventory, and delivery control", style="Subtitle.TLabel").pack(anchor="w", pady=(2, 0))
        self.lbl_connection = ttk.Label(header, text="● MQTT connecting", style="Status.TLabel")
        self.lbl_connection.pack(side="right", anchor="n")

        notebook = ttk.Notebook(main)
        notebook.pack(fill="both", expand=True)
        tab_operations = ttk.Frame(notebook, padding=(4, 10, 4, 4))
        tab_graphs = ttk.Frame(notebook, padding=(4, 10, 4, 4))
        tab_inventory = ttk.Frame(notebook, padding=(4, 10, 4, 4))
        notebook.add(tab_operations, text="Operations")
        notebook.add(tab_graphs, text="Analytics")
        notebook.add(tab_inventory, text="Inventory")

        telemetry = ttk.LabelFrame(tab_operations, text=" Live telemetry ", style="Section.TLabelframe", padding=10)
        telemetry.pack(fill="x", padx=4, pady=(0, 10))
        for col in range(3): telemetry.columnconfigure(col, weight=1)
        self.lbl_motion = self._telemetry_card(telemetry, 0, 0, "Motion detection", "CLEAR")
        self.lbl_light = self._telemetry_card(telemetry, 0, 1, "Ambient light", "Unknown")
        self.lbl_sound = self._telemetry_card(telemetry, 0, 2, "Sound level", "Unknown")
        self.lbl_temp = self._telemetry_card(telemetry, 1, 0, "Indoor temperature", "0 °C")
        self.lbl_humidity = self._telemetry_card(telemetry, 1, 1, "Indoor humidity", "0%")
        self.lbl_product = self._telemetry_card(telemetry, 1, 2, "Product detection", "—")

        lower = ttk.Frame(tab_operations)
        lower.pack(fill="both", expand=True, padx=4)
        lower.columnconfigure(0, weight=3); lower.columnconfigure(1, weight=2); lower.rowconfigure(0, weight=1)
        dispatch = ttk.LabelFrame(lower, text=" Dispatch control ", style="Section.TLabelframe", padding=14)
        dispatch.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ttk.Label(dispatch, text="Select the destination for the detected item.", style="Subtitle.TLabel").pack(anchor="w")
        status_card = ttk.Frame(dispatch, style="Card.TFrame", padding=10)
        status_card.pack(fill="x", pady=(12, 12))
        self.lbl_dispatch_status = ttk.Label(status_card, text="Ready for a delivery request", style="Status.TLabel")
        self.lbl_dispatch_status.pack(fill="x")
        button_row = ttk.Frame(dispatch); button_row.pack(fill="x"); button_row.columnconfigure(0, weight=1); button_row.columnconfigure(1, weight=1)
        self.btn_left_100 = ttk.Button(button_row, text="Deliver to Frankfurt", style="Primary.TButton", command=lambda: self._execute_delivery("Frankfurt", "deliver_left"))
        self.btn_left_100.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.btn_right_100 = ttk.Button(button_row, text="Deliver to Stuttgart", style="Primary.TButton", command=lambda: self._execute_delivery("Stuttgart", "deliver_right"))
        self.btn_right_100.grid(row=0, column=1, sticky="ew", padx=(5, 0))
        ttk.Label(dispatch, text="The buttons stay locked until delivery is confirmed.", style="Subtitle.TLabel").pack(anchor="w", pady=(12, 0))

        right = ttk.Frame(lower); right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        weather = ttk.LabelFrame(right, text=" Outdoor weather ", style="Section.TLabelframe", padding=12)
        weather.pack(fill="x", pady=(0, 10))
        self.lbl_weather = ttk.Label(weather, text="Loading weather data…", style="CardValue.TLabel")
        self.lbl_weather.pack(anchor="w", pady=(0, 10))
        self.var_sim_mode = tk.BooleanVar(value=False)
        self.chk_sim_mode = ttk.Checkbutton(weather, text="Use simulated weather", variable=self.var_sim_mode, command=self._on_weather_mode_toggle)
        self.chk_sim_mode.pack(anchor="w", pady=(0, 8))
        inputs = ttk.Frame(weather); inputs.pack(fill="x"); inputs.columnconfigure(1, weight=1)
        
        ttk.Label(inputs, text="Temperature (°C)").grid(row=0, column=0, sticky="w", pady=4)

        self.ent_temp_sim = ttk.Entry(inputs, width=10)
        self.ent_temp_sim.insert(0, "22")
        self.ent_temp_sim.grid(
            row=0, column=1, sticky="ew", padx=(10, 0), pady=4
        )

        ttk.Label(inputs, text="Humidity (%)").grid(row=1, column=0, sticky="w", pady=4)

        self.ent_humidity_sim = ttk.Entry(inputs, width=10)
        self.ent_humidity_sim.insert(0, "45")
        self.ent_humidity_sim.grid(
            row=1, column=1, sticky="ew", padx=(10, 0), pady=4
        )

        self.var_rain_sim = tk.BooleanVar(value=False)

        self.chk_rain_sim = ttk.Checkbutton(weather, text="Raining", variable=self.var_rain_sim); self.chk_rain_sim.pack(anchor="w", pady=(7, 0))
        for widget in (self.ent_temp_sim, self.ent_humidity_sim, self.chk_rain_sim): widget.config(state="disabled")
        operator = ttk.LabelFrame(right, text=" Operator controls ", style="Section.TLabelframe", padding=12); operator.pack(fill="x")
        self.btn_night = ttk.Button(operator, text="Enable night mode", style="Secondary.TButton", command=self._toggle_night_mode); self.btn_night.pack(fill="x", pady=(0, 7))
        self.btn_toggle_log = ttk.Button(operator, text="Hide activity log", style="Secondary.TButton", command=self._toggle_log_panel); self.btn_toggle_log.pack(fill="x", pady=7)
        ttk.Button(operator, text="Exit control panel", style="Danger.TButton", command=self.root.quit).pack(fill="x", pady=(7, 0))

        graph_frame = ttk.LabelFrame(tab_graphs, text=" Environmental trends ", style="Section.TLabelframe", padding=12)
        graph_frame.pack(fill="both", expand=True, padx=4, pady=4)
        self.fig = Figure(figsize=(7.5, 5.2), dpi=100); self.fig.patch.set_facecolor("#FFFFFF")
        self.ax_temp = self.fig.add_subplot(211); self.ax_humid = self.fig.add_subplot(212)
        for axis in (self.ax_temp, self.ax_humid): axis.set_facecolor("#FFFFFF"); axis.grid(True, linestyle="--", alpha=0.28)
        self.ax_temp.set_title("Temperature (°C)", loc="left", fontsize=11); self.ax_humid.set_title("Humidity (%)", loc="left", fontsize=11)
        self.fig.tight_layout(pad=2.4)
        self.canvas = FigureCanvasTkAgg(self.fig, master=graph_frame); self.canvas.get_tk_widget().pack(fill="both", expand=True)

        inv_frame = ttk.LabelFrame(tab_inventory, text=" Current stock ", style="Section.TLabelframe", padding=12); inv_frame.pack(fill="both", expand=True, padx=4, pady=(4, 10))
        self.inv_tree = ttk.Treeview(inv_frame, columns=("ID", "Name", "Qty", "Min"), show="headings", height=12)
        for key, title, width, anchor in (("ID", "Item ID", 120, "center"), ("Name", "Description", 430, "w"), ("Qty", "Available", 110, "center"), ("Min", "Minimum", 110, "center")):
            self.inv_tree.heading(key, text=title); self.inv_tree.column(key, width=width, anchor=anchor)
        scroll = ttk.Scrollbar(inv_frame, orient="vertical", command=self.inv_tree.yview); self.inv_tree.configure(yscrollcommand=scroll.set)
        self.inv_tree.pack(side="left", fill="both", expand=True); scroll.pack(side="right", fill="y"); self._populate_inventory_tree()
        actions = ttk.LabelFrame(tab_inventory, text=" Stock adjustment ", style="Section.TLabelframe", padding=12); actions.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Label(actions, text="Quantity").pack(side="left")
        self.ent_qty_change = ttk.Entry(actions, width=8); self.ent_qty_change.insert(0, "10"); self.ent_qty_change.pack(side="left", padx=8)
        ttk.Button(actions, text="Restock selected", style="Primary.TButton", command=lambda: self._handle_stock_adjust(1)).pack(side="left", padx=(4, 6))
        ttk.Button(actions, text="Dispatch selected", style="Secondary.TButton", command=lambda: self._handle_stock_adjust(-1)).pack(side="left")

        self.log_frame = ttk.LabelFrame(main, text=" Activity log ", style="Section.TLabelframe", padding=8); self.log_frame.pack(fill="both", expand=False, pady=(10, 0))
        self.log_box = tk.Text(self.log_frame, height=14, state="disabled", wrap="word", background=self.colors["log_bg"], foreground=self.colors["log_fg"], insertbackground="white", relief="flat", font=("Cascadia Mono", 9), padx=10, pady=8)
        self.log_box.pack(side="left", fill="both", expand=True)
        log_scroll = ttk.Scrollbar(self.log_frame, command=self.log_box.yview); log_scroll.pack(side="right", fill="y"); self.log_box.configure(yscrollcommand=log_scroll.set)


    # -------------------- PDDL planner integration --------------------
    def actions_mqtt_publish(self, payload: str) -> None:
        self._publish_mqtt("actions", payload)
        self._log_to_gui(f"[MQTT PUB] actions → {payload}")

    def _pddl_dir(self) -> str:
        return os.environ.get(
            "PDDL_DIR",
            os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pddl")),
        )

    def run_planner(self, domain_path: str, problem_path: str) -> None:
        if not os.path.exists(domain_path):
            self._log_to_gui(f"[PLANNER] Domain file not found: {domain_path}")
            return
        if not os.path.exists(problem_path):
            self._log_to_gui(f"[PLANNER] Problem file not found: {problem_path}")
            return
        if PDDLReader is None or OneshotPlanner is None:
            self._log_to_gui("[PLANNER] Unified Planning is unavailable. Install unified-planning and Fast Downward.")
            return
        self._log_to_gui(f"[PLANNER] Solving {os.path.basename(problem_path)} with Fast Downward.")
        try:
            problem = PDDLReader().parse_problem(domain_path, problem_path)
            with OneshotPlanner(name="fast-downward") as planner:
                result = planner.solve(problem)
            plan_path = os.path.join(os.path.dirname(problem_path), f"plan_{os.path.basename(problem_path)}.txt")
            status = getattr(getattr(result, "status", None), "name", "UNKNOWN")
            if status in {"SOLVED_SATISFICING", "SOLVED_OPTIMALLY"}:
                actions = [str(action) for action in getattr(getattr(result, "plan", None), "actions", [])]
                plan_text = "\n".join(actions) if actions else "No actions generated."
                Path(plan_path).write_text(plan_text, encoding="utf-8")
                for action in actions:
                    self._log_to_gui(f"[PLANNER] {action}")
                self.actions_mqtt_publish(plan_text)
                self._log_to_gui(f"[PLANNER] Plan saved: {plan_path}")
            else:
                Path(plan_path).write_text("No plan found.", encoding="utf-8")
                self._log_to_gui(f"[PLANNER] No plan found ({status}).")
        except Exception as exc:
            self._log_to_gui(f"[PLANNER] Error: {exc}")

    def _run_initial_problem_if_available(self) -> None:
        pddl_dir = self._pddl_dir()
        domain_path = os.path.join(pddl_dir, "domain.pddl")
        problem_path = os.path.join(pddl_dir, "problem_1.pddl")
        if os.path.exists(domain_path) and os.path.exists(problem_path):
            self._log_to_gui("[PLANNER] Startup problem detected; running problem_1.pddl.")
            self.run_planner(domain_path, problem_path)
        else:
            self._log_to_gui("[PLANNER] Startup domain/problem not found; waiting for live telemetry.")

    def generate_pddl_problem(self, init_conditions: List[str], goal_conditions: List[str], zones, item_name: str) -> str | None:
        pddl_dir = self._pddl_dir()
        os.makedirs(pddl_dir, exist_ok=True)
        domain_path = os.path.join(pddl_dir, "domain.pddl")
        if not os.path.exists(domain_path):
            self._log_to_gui(f"[PLANNER] Domain file not found: {domain_path}")
            return None
        domain_text = Path(domain_path).read_text(encoding="utf-8")
        match = re.search(r"\(define\s*\(domain\s+([^\s\)]+)\)", domain_text)
        domain_name = match.group(1) if match else "smart-zone-control"
        numbers = [int(m.group(1)) for name in os.listdir(pddl_dir) if (m := re.fullmatch(r"problem_(\d+)\.pddl", name))]
        number = max(numbers, default=0) + 1
        zone_list = sorted(set(zones)) or ["zone1"]
        conditions = list(dict.fromkeys(init_conditions))
        for zone in reversed(zone_list):
            fact = f"(zone-in-building {zone} building1)"
            if fact not in conditions:
                conditions.insert(0, fact)
        if not goal_conditions:
            self._log_to_gui("[PLANNER] No goals generated; PDDL problem skipped.")
            return None
        objects = "\n    ".join(f"{zone} - zone" for zone in zone_list)
        init_text = "\n    ".join(conditions)
        goal_text = "\n      ".join(dict.fromkeys(goal_conditions))
        problem_text = f""";; Auto-generated from live warehouse telemetry
(define (problem problem_{number})
  (:domain {domain_name})

  (:objects
    building1 - building
    {objects}
    {item_name or "item1"} - item
  )

  (:init
    {init_text}
  )

  (:goal
    (and
      {goal_text}
    )
  )
)
"""
        problem_path = os.path.join(pddl_dir, f"problem_{number}.pddl")
        Path(problem_path).write_text(problem_text, encoding="utf-8")
        self._log_to_gui(f"[PLANNER] Generated {os.path.basename(problem_path)}.")
        self.run_planner(domain_path, problem_path)
        return problem_path

    def aiplanner(self, temperature, humidity, light, sound, motion, product, ultrasonic, delivery_request, weather_outdoor,fanstatus,windowstatus,heaterstatus) -> None:
        global init_conditions_prev, goal_conditions_prev
        init_conditions: List[str] = []
        goal_conditions: List[str] = []
        zones = set()
        item_name = f"item_INV-001_{self.delivery_count + 1}"
        if isinstance(delivery_request, dict):
            item_name = f"item_{delivery_request.get('transaction_id', '1')}"

        def get_zone(payload, default="zone1"):
            return payload.get("zone", default) if isinstance(payload, dict) else default

        if isinstance(motion, dict):        
            if motion.get("value"):
                zone = get_zone(motion)
                zones.add(zone)
                init_conditions.append(f"(motion-detected {zone})")
        else:
            logger.warning("Motion data is not a dict or missing 'value': %s", motion)

        if isinstance(light, dict) and light.get("raw") is not None:
            zone = get_zone(light)
            zones.add(zone)
            raw_light = light.get("raw", 0)
            low_thresh_light = light.get("lightlow_threshold", 0)
            high_thresh_light = light.get("lighthigh_threshold", float("inf"))
            
            if(raw_light >= high_thresh_light):
                init_conditions.append(f"(light-high {zone})")

            elif(raw_light >= low_thresh_light and raw_light < high_thresh_light):
                init_conditions.append(f"(light-normal {zone})")

            else:
                init_conditions.append(f"(light-low {zone})")

            goal_conditions.append(f"(control-lights {zone})")

        else:
            logger.warning("Light data is not a dict or missing 'raw': %s", light)

        if isinstance(temperature, dict) and temperature.get("temperature_c") is not None:
            zone = get_zone(temperature)
            zones.add(zone)
            temp_current = temperature.get("temperature_c")
            temp_low = temperature.get("templow_threshold", 18)
            high = temperature.get("temphigh_threshold", 26)

            if temp_current >= high:
                init_conditions.append(f"(indoor-temp-hot {zone})")
            elif temp_current < temp_low:
                init_conditions.append(f"(indoor-temp-cold {zone})")
            else:

                init_conditions.append(f"(indoor-temp-ideal {zone})")
            goal_conditions.append(f"(comfortable {zone})")

        else:
            logger.warning("Temperature data is not a dict or missing 'temperature_c': %s", temperature)

        if isinstance(humidity, dict):
            zone = get_zone(humidity)
            zones.add(zone)
            humidity_value = humidity.get("humidity_pct")
            threshold = humidity.get("threshold", 40)

            if humidity_value is not None:
                if humidity_value <= threshold:
                    init_conditions.append(f"(humidity-low {zone})")

                goal_conditions.append(f"(control-humidity {zone})")
        else:
            logger.warning("Humidity data is not a dict or missing 'humidity_pct': %s", humidity)

        #print("Weather outdoor:", weather_outdoor)
        if isinstance(weather_outdoor, dict):
            temp = weather_outdoor.get("temperature_c")
            if temp is not None: 
                if temp>=30:
                    init_conditions.append("(outdoor-temp-hot)")
                else:
                    init_conditions.append("(outdoor-temp-cold)")
            
            if weather_outdoor.get("description") == "Raining": 
                init_conditions.append("(outdoor-raining)")

        else:
            logger.warning("Weather outdoor data is not a dict: %s", weather_outdoor)

        if isinstance(delivery_request, dict):
            zone = get_zone(delivery_request); zones.add(zone)
            command = delivery_request.get("command")
            if command == "deliver_left": init_conditions.append(f"(delivery-requested-left {item_name} {zone})")
            elif command == "deliver_right": init_conditions.append(f"(delivery-requested-right {item_name} {zone})")
            else: logger.warning("Invalid delivery request command: %s", command); return
            present = False
            if isinstance(ultrasonic, dict):
                raw, threshold = ultrasonic.get("raw"), ultrasonic.get("threshold")
                
                if raw is not None:
                    if raw <= threshold:
                        present = True
                    else:
                        present = False
                else:
                    logger.warning("Ultrasonic data is not a dict or missing 'raw': %s", ultrasonic)

            elif isinstance(product, dict): present = bool(product.get("present"))
            if present: init_conditions.append(f"(product-available {item_name} {zone})")
            goal_conditions.append(f"(delivery-request-handled {item_name} {zone})")


        if isinstance(fanstatus, dict):
            zone = get_zone(fanstatus)
            zones.add(zone)
            if fanstatus.get("status") == "on": init_conditions.append(f"(fan-on {zone})")
            else: init_conditions.append(f"(fan-off {zone})")

        else:
            init_conditions.append(f"(fan-off zone1)")
            #logger.warning("Fan status data is not a dict: %s", fanstatus)

        if isinstance(windowstatus, dict):
            zone = get_zone(windowstatus); zones.add(zone)
            if windowstatus.get("status") == "open": init_conditions.append(f"(window-open {zone})")
            else: init_conditions.append(f"(window-closed {zone})")
        else:
            init_conditions.append(f"(window-closed zone1)")
            logger.warning("Window status data is not a dict: %s", windowstatus)   

        if isinstance(heaterstatus, dict):
            zone = get_zone(heaterstatus); zones.add(zone)
            if heaterstatus.get("status") == "on":
                init_conditions.append(f"(heater-on {zone})")
            else: 
                init_conditions.append(f"(heater-off {zone})")
        else:
            init_conditions.append(f"(heater-off zone1)")
            logger.warning("Heater status data is not a dict: %s", heaterstatus)


        init_conditions = list(dict.fromkeys(init_conditions)); goal_conditions = list(dict.fromkeys(goal_conditions))
        if (init_conditions, goal_conditions) != (init_conditions_prev, goal_conditions_prev):
            init_conditions_prev, goal_conditions_prev = init_conditions, goal_conditions
            self._log_to_gui(f"[PLANNER] Init: {init_conditions}")
            self._log_to_gui(f"[PLANNER] Goals: {goal_conditions}")
            self.generate_pddl_problem(init_conditions, goal_conditions, zones, item_name)

    def _toggle_log_panel(self) -> None:
        if self.log_visible:
            self.log_frame.pack_forget()
            self.btn_toggle_log.config(text="Show activity log")
        else:
            self.log_frame.pack(fill="both", expand=False, pady=(10, 0))
            self.btn_toggle_log.config(text="Hide activity log")

        self.log_visible = not self.log_visible

    def _init_mqtt(self) -> None:
        if mqtt is None:
            self.lbl_connection.config(text="● MQTT simulation", foreground=self.colors["muted"]); self._log_to_gui("[MQTT] paho-mqtt unavailable; simulation mode enabled."); return
        host = os.environ.get("MQTT_HOST", "192.168.0.199"); port = int(os.environ.get("MQTT_PORT", "1883"))
        try:
            client = mqtt.Client(client_id="Warehouse1GUI")
            client.on_connect = self._on_mqtt_connect; client.on_message = self._on_mqtt_message; client.on_disconnect = self._on_mqtt_disconnect
            client.connect(host, port); client.loop_start(); self.mqtt_client = client
        except Exception as exc:
            self.lbl_connection.config(text="● MQTT offline", foreground=self.colors["danger"]); self._log_to_gui(f"[MQTT] Offline: {exc}")

    def _on_mqtt_connect(self, client, userdata, flags, rc, *args) -> None:
        if rc == 0:
            self.mqtt_connected = True
            client.subscribe(f"{self.base_topic}/#", qos=0)
            client.subscribe("delivery_ack", qos=1)
            self._enqueue_gui_task(self.lbl_connection.config, text="● MQTT connected", foreground=self.colors["success"])
            self._enqueue_gui_task(self._log_to_gui, "[MQTT] Connected and subscribed.")
        else:
            self._enqueue_gui_task(self.lbl_connection.config, text="● MQTT connection failed", foreground=self.colors["danger"])

    def _on_mqtt_disconnect(self, client, userdata, *args) -> None:
        self.mqtt_connected = False; self._enqueue_gui_task(self.lbl_connection.config, text="● MQTT offline", foreground=self.colors["danger"]); self._enqueue_gui_task(self._log_to_gui, "[MQTT] Disconnected.")

    def _on_mqtt_message(self, client, userdata, msg) -> None:
        self._enqueue_gui_task(self._handle_incoming_mqtt, msg.topic, msg.payload.decode("utf-8", errors="replace"))

    def _enqueue_gui_task(self, callback, *args, **kwargs) -> None:
        self._gui_event_queue.put((callback, args, kwargs))

    def _drain_gui_queue(self) -> None:
        while not self._gui_event_queue.empty():
            callback, args, kwargs = self._gui_event_queue.get_nowait()
            try: callback(*args, **kwargs)
            except Exception as exc: logger.exception("GUI callback failed: %s", exc)
        self.root.after(50, self._drain_gui_queue)

    def _handle_incoming_mqtt(self, topic: str, payload: str) -> None:
        try: data = json.loads(payload)
        except (TypeError, json.JSONDecodeError): self._log_to_gui(f"[MQTT SUB] {topic} → {payload}"); return
        if topic == "delivery_ack":
            tx_id = data.get("transaction_id"); status = data.get("status", "")
            if tx_id in self._pending_deliveries:
                destination = self._pending_deliveries.pop(tx_id)
                if status == "delivered": self._on_mqtt_delivery_success_received(tx_id, destination)
                else: self._reset_dispatch(f"Delivery failed for {destination}")
            return
        sub_topic = topic.split("/")[-1]
        if isinstance(data, dict): data["zone"] = topic.split("/")[-2] if len(topic.split("/")) >= 2 else "zone1"
        self.latest_sensors[sub_topic] = data
        #self._log_to_gui(f"[MQTT SUB] {topic} → {payload}")
        self._update_telemetry_labels()

    def _publish_mqtt(self, sub_topic: str, payload: Any) -> None:
        topic = f"{self.base_topic}/{sub_topic}"
        if self.mqtt_client and self.mqtt_connected:
            try: self.mqtt_client.publish(topic, str(payload), qos=0)
            except Exception as exc: self._log_to_gui(f"[MQTT PUB] Failed: {exc}")
        else: logger.info("[MQTT SIM] %s → %s", topic, payload)

    def _on_weather_mode_toggle(self) -> None:
        self.weather_simulated = self.var_sim_mode.get()
        state = "normal" if self.weather_simulated else "disabled"
        for widget in (self.ent_temp_sim, self.ent_humidity_sim, self.chk_rain_sim): widget.config(state=state)
        self._log_to_gui("[SYSTEM] Simulated weather enabled." if self.weather_simulated else "[SYSTEM] Live weather enabled.")
        self._fetch_weather_service()

    def _describe_weather_code(self, code: Any) -> str:
        try: return "Raining" if int(code) in {51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96, 99} else "Clear"
        except (TypeError, ValueError): return "Unknown"

    def _get_live_weather_data(self) -> Dict[str, Any]:
        city = os.environ.get("WEATHER_CITY", "Stuttgart")
        try:
            geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=1&language=en&format=json"
            with urllib.request.urlopen(geo_url, timeout=8) as response: place = json.load(response)["results"][0]
            url = f"https://api.open-meteo.com/v1/forecast?latitude={place['latitude']}&longitude={place['longitude']}&current=temperature_2m,relative_humidity_2m,weather_code&timezone=auto"
            with urllib.request.urlopen(url, timeout=8) as response: current = json.load(response).get("current", {})
            return {"temperature_c": round(float(current.get("temperature_2m", 0)), 1), "humidity_pct": int(current.get("relative_humidity_2m", 0)), "description": self._describe_weather_code(current.get("weather_code"))}
        except Exception as exc:
            logger.warning("Weather fetch failed: %s", exc); return {"temperature_c": None, "humidity_pct": None, "description": "Unavailable"}

    def _fetch_weather_service(self) -> None:
        if self.weather_simulated:
            try: temp = float(self.ent_temp_sim.get())
            except ValueError: temp = None
            try: humidity = int(self.ent_humidity_sim.get())
            except ValueError: humidity = None
            weather = {"temperature_c": temp, "humidity_pct": humidity, "description": "Raining" if self.var_rain_sim.get() else "Clear"}
            source = "simulated"
        else: weather = self._get_live_weather_data(); source = "live"

        self.latest_sensors["weather_outdoor"] = weather
        display_temp = "—" if weather["temperature_c"] is None else f"{weather['temperature_c']} °C"
        self.lbl_weather.config(
            text=f"{display_temp} · {weather['description']} ({source})"
        )
        self._publish_mqtt("weather_outdoor", json.dumps(weather))
        self.root.after(30000, self._fetch_weather_service)


    def _toggle_night_mode(self) -> None:
        self.night_mode = not self.night_mode
        self.btn_night.config(text="Disable night mode" if self.night_mode else "Enable night mode")
        self._log_to_gui("[SYSTEM] Night mode enabled." if self.night_mode else "[SYSTEM] Night mode disabled.")

    def _populate_inventory_tree(self) -> None:
        for item in self.inv_tree.get_children(): self.inv_tree.delete(item)
        for item_id, details in self.inventory_mgr.get_all_items().items(): self.inv_tree.insert("", tk.END, values=(item_id, details["name"], details["qty"], details["min_threshold"]))

    def _handle_stock_adjust(self, direction: int) -> None:
        selection = self.inv_tree.selection()
        if not selection: messagebox.showinfo("Select an item", "Select an inventory item first."); return
        try: delta = int(self.ent_qty_change.get()) * direction
        except ValueError: messagebox.showerror("Invalid quantity", "Enter a whole-number quantity."); return
        item_id = self.inv_tree.item(selection[0])["values"][0]; success, info = self.inventory_mgr.update_stock(item_id, delta)
        if not success: messagebox.showwarning("Inventory update", info); return
        self._populate_inventory_tree(); self._sync_inventory_to_mqtt(); self._log_to_gui(f"[INVENTORY] {item_id}: {delta:+d} units.")
        if info == "LOW_STOCK_WARNING": self._log_to_gui(f"[INVENTORY] Low stock warning for {item_id}.")

    def _sync_inventory_to_mqtt(self) -> None:
        self._publish_mqtt("inventory", json.dumps({item: data["qty"] for item, data in self.inventory_mgr.get_all_items().items()}))

    def _log_to_gui(self, message: str) -> None:
        logger.info(message)

        if not hasattr(self, "log_box"):
            return

        try:
            if not self.log_box.winfo_exists():
                return

            self.log_box.configure(state="normal")
            self.log_box.insert(
                tk.END,
                f"{time.strftime('%H:%M:%S')}  {message}\n",
            )
            self.log_box.see(tk.END)
            self.log_box.configure(state="disabled")

        except tk.TclError as exc:
            logger.error("Unable to write to GUI log: %s", exc)

    def read_environment_sensors(self) -> Dict[str, Any]:
        def payload(name): return self.latest_sensors.get(name, {}) if isinstance(self.latest_sensors.get(name, {}), dict) else {}
        temperature, humidity, motion, light, sound = payload("temperature"), payload("humidity"), payload("motiondetected"), payload("light"), payload("sound")
        ultrasonic, product = payload("ultrasonic"), payload("productdetected")
        light_raw, low, high = light.get("raw"), light.get("lightlow_threshold"), light.get("lighthigh_threshold")
        light_level = "Unknown" if light_raw is None else "Bright" if high is not None and light_raw >= high else "Normal" if low is not None and light_raw >= low else "Low"
        sound_raw, sound_threshold = sound.get("raw_max"), sound.get("threshold")
        sound_level = "Unknown" if sound_raw is None else "High" if sound_threshold is not None and sound_raw >= sound_threshold else "Low"
        raw, threshold = ultrasonic.get("raw"), ultrasonic.get("threshold")
        present = (raw <= threshold) if raw is not None and threshold is not None else product.get("present")
        return {"temperature": temperature.get("temperature_c", 0), "humidity": humidity.get("humidity_pct", 0), "motion_detected": bool(motion.get("value", False)), "light_level": light_level, "sound_level": sound_level, "product_present": present}

    def _invoke_planner_from_telemetry(self) -> None:
        required = (
            "temperature",
            "humidity",
            "light",
            "weather_outdoor"
        )

        missing = []

        for name in required:
            sensor_data = self.latest_sensors.get(name)
            
            # Check if the data is missing or is not a dictionary
            if not isinstance(sensor_data, dict):
                missing.append(name)


        if missing:
            self._log_to_gui(
                "[PLANNER] Waiting for telemetry: " + ", ".join(missing)
            )
            return

        self.aiplanner(
            self.latest_sensors.get("temperature"),
            self.latest_sensors.get("humidity"),
            self.latest_sensors.get("light"),
            self.latest_sensors.get("sound"),
            self.latest_sensors.get("motiondetected"),
            self.latest_sensors.get("productdetected"),
            self.latest_sensors.get("ultrasonic"),
            self.latest_sensors.get("delivery_request"),
            self.latest_sensors.get("weather_outdoor"),
            self.latest_sensors.get("fan_actuator_status"),
            self.latest_sensors.get("window_actuator_status"),
            self.latest_sensors.get("heater_actuator_status"),
        )

    def _update_telemetry_labels(self) -> None:
        self._invoke_planner_from_telemetry()
        data = self.read_environment_sensors()
        self.lbl_motion.config(text="ACTIVE" if data["motion_detected"] else "CLEAR", foreground=self.colors["danger"] if data["motion_detected"] else self.colors["success"])
        self.lbl_light.config(text=data["light_level"], foreground=self.colors["text"])
        self.lbl_sound.config(text=data["sound_level"], foreground=self.colors["danger"] if data["sound_level"] == "High" else self.colors["text"])
        self.lbl_temp.config(text=f"{data['temperature']} °C")
        self.lbl_humidity.config(text=f"{data['humidity']}%")
        if data["product_present"] is not None: self.lbl_product.config(text="PRESENT" if bool(data["product_present"]) else "ABSENT", foreground=self.colors["success"] if bool(data["product_present"]) else self.colors["muted"])

    def _update_plots(self, now: str, temp: float, humidity: float) -> None:
        self.time_history.append(now); self.temp_history.append(temp); self.humid_history.append(humidity)
        if len(self.time_history) > self.history_limit: self.time_history.pop(0); self.temp_history.pop(0); self.humid_history.pop(0)
        x = list(range(len(self.time_history)))
        for axis in (self.ax_temp, self.ax_humid): axis.clear(); axis.set_facecolor("#FFFFFF"); axis.grid(True, linestyle="--", alpha=0.28); axis.set_xticks(x); axis.set_xticklabels(self.time_history, rotation=35, fontsize=8)
        self.ax_temp.plot(x, self.temp_history, color="#D35400", marker=".", linewidth=2); self.ax_temp.set_title("Temperature (°C)", loc="left", fontsize=11)
        self.ax_humid.plot(x, self.humid_history, color="#16865B", marker=".", linewidth=2); self.ax_humid.set_title("Humidity (%)", loc="left", fontsize=11)
        self.fig.tight_layout(pad=2.4); self.canvas.draw_idle()

    def _refresh_telemetry_loop(self) -> None:
        try:
            data = self.read_environment_sensors(); self._update_plots(time.strftime("%H:%M:%S"), data["temperature"], data["humidity"]); self._update_telemetry_labels()
        except Exception as exc: logger.exception("Telemetry refresh failed: %s", exc)
        self.root.after(4000, self._refresh_telemetry_loop)

    def _product_present_for_dispatch(self) -> bool:
        data = self.read_environment_sensors(); return bool(data["product_present"])

    def _execute_delivery(self, destination: str, mqtt_payload: str) -> None:
        if self.is_waiting_for_mqtt: return
        if not self._product_present_for_dispatch():
            self._log_to_gui(f"[DELIVERY ABORT] No product detected for {destination}.")
            messagebox.showwarning("No product detected", "Place a package in the dispatch zone before retrying."); return
        success, info = self.inventory_mgr.update_stock("INV-001", -1)
        if not success: messagebox.showerror("Dispatch unavailable", "Insufficient stock."); return
        self.delivery_count += 1; transaction_id = f"INV-001_{self.delivery_count}"
        self.is_waiting_for_mqtt = True; self.active_destination = destination; self.btn_left_100.config(state="disabled"); self.btn_right_100.config(state="disabled")
        self.lbl_dispatch_status.config(text=f"Waiting for MQTT confirmation · {destination}", foreground=self.colors["primary"])
        self._populate_inventory_tree(); self._sync_inventory_to_mqtt()
        self._pending_deliveries[transaction_id] = destination
        payload = json.dumps({"command": mqtt_payload, "transaction_id": transaction_id, "destination": destination})
        self._publish_mqtt("delivery_request", payload); self._log_to_gui(f"[LOGISTICS] Dispatching to {destination} ({transaction_id}).")
        if not (self.mqtt_client and self.mqtt_connected): self.root.after(2500, lambda: self._on_mqtt_delivery_success_received(transaction_id, self._pending_deliveries.pop(transaction_id, destination)))

    def _on_mqtt_delivery_success_received(
        self,
        transaction_id: str,
        destination: str,) -> None:

        active_request = self.latest_sensors.get("delivery_request")

        if (
            isinstance(active_request, dict)
            and active_request.get("transaction_id") == transaction_id
        ):
            self.latest_sensors.pop("delivery_request", None)

        self._log_to_gui(
            f"[DELIVERY] Confirmed: {transaction_id} delivered to {destination}."
        )

        self._reset_dispatch(f"Delivered successfully to {destination}")
        self._update_telemetry_labels()

    def _reset_dispatch(self, status: str = "Ready for a delivery request") -> None:
        self.is_waiting_for_mqtt = False; self.active_destination = None; self.btn_left_100.config(state="normal"); self.btn_right_100.config(state="normal")
        self.lbl_dispatch_status.config(text=status, foreground=self.colors["success"] if status.startswith("Delivered") else self.colors["primary"])


def on_close_clean(app: SmartWarehouseInterfaceGUI, root: tk.Tk) -> None:
    if app.mqtt_client:
        try: app.mqtt_client.loop_stop(); app.mqtt_client.disconnect()
        except Exception: pass
    root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = SmartWarehouseInterfaceGUI(root)
    root.protocol("WM_DELETE_WINDOW", lambda: on_close_clean(app, root))
    try: root.mainloop()
    except KeyboardInterrupt: on_close_clean(app, root); sys.exit(0)
