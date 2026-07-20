import json
import time
import tkinter as tk
from tkinter import ttk
import paho.mqtt.client as mqtt

MQTT_BROKER = "10.16.170.211"
MQTT_PORT = 1883

TOPIC_ACTIONS = "building1/floor0/zone1/actions"
TOPIC_WINDOW_STATUS = "building1/floor0/zone1/window_actuator_status"
TOPIC_HEATER_STATUS = "building1/floor0/zone1/heater_actuator_status"

STATE_PUBLISH_INTERVAL_MS = 30_000


class WarehouseUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Smart Warehouse · Climate Actuators")
        self.root.geometry("760x460")
        self.root.minsize(680, 420)
        self.root.configure(bg="#101828")

        self.window_state = "closed"
        self.heater_state = "off"
        self.mqtt_connected = False
        self.client = mqtt.Client(client_id="warehouse-window-heater-ui")

        self._configure_style()
        self._build_ui()
        self._configure_mqtt()

        self.root.after(1_000, self.publish_current_state)
        self.root.after(STATE_PUBLISH_INTERVAL_MS, self._periodic_state_publish)

    def _configure_style(self) -> None:
        self.style = ttk.Style()
        self.style.theme_use("clam")

        self.style.configure(
            "TFrame",
            background="#101828",
        )
        self.style.configure(
            "Card.TFrame",
            background="#1D2939",
            relief="flat",
        )
        self.style.configure(
            "Title.TLabel",
            background="#101828",
            foreground="#F9FAFB",
            font=("Segoe UI Semibold", 20),
        )
        self.style.configure(
            "Sub.TLabel",
            background="#101828",
            foreground="#98A2B3",
            font=("Segoe UI", 10),
        )
        self.style.configure(
            "CardTitle.TLabel",
            background="#1D2939",
            foreground="#98A2B3",
            font=("Segoe UI Semibold", 11),
        )
        self.style.configure(
            "State.TLabel",
            background="#1D2939",
            foreground="#F9FAFB",
            font=("Segoe UI Semibold", 22),
        )
        self.style.configure(
            "Status.TLabel",
            background="#101828",
            foreground="#98A2B3",
            font=("Segoe UI", 10),
        )
        self.style.configure(
            "Primary.TButton",
            font=("Segoe UI Semibold", 10),
            foreground="#FFFFFF",
            background="#1570EF",
            padding=(12, 8),
            borderwidth=0,
        )
        self.style.map(
            "Primary.TButton",
            background=[("active", "#175CD3")],
        )
        self.style.configure(
            "Secondary.TButton",
            font=("Segoe UI Semibold", 10),
            foreground="#E4E7EC",
            background="#344054",
            padding=(12, 8),
            borderwidth=0,
        )
        self.style.map(
            "Secondary.TButton",
            background=[("active", "#475467")],
        )

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=22)
        main.pack(fill="both", expand=True)

        ttk.Label(
            main,
            text="Climate Actuator Panel",
            style="Title.TLabel",
        ).pack(anchor="w")

        ttk.Label(
            main,
            text="Window and heater states are synchronised through MQTT.",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(4, 20))

        cards = ttk.Frame(main)
        cards.pack(fill="both", expand=True)

        cards.columnconfigure(0, weight=1)
        cards.columnconfigure(1, weight=1)
        cards.rowconfigure(0, weight=1)

        self.window_card = ttk.Frame(cards, style="Card.TFrame", padding=22)
        self.window_card.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, 10),
        )

        self.heater_card = ttk.Frame(cards, style="Card.TFrame", padding=22)
        self.heater_card.grid(
            row=0,
            column=1,
            sticky="nsew",
            padx=(10, 0),
        )

        self._build_window_card()
        self._build_heater_card()

        self.lbl_mqtt = ttk.Label(
            main,
            text="● MQTT connecting",
            style="Status.TLabel",
        )
        self.lbl_mqtt.pack(anchor="w", pady=(18, 0))

    def _build_window_card(self) -> None:
        ttk.Label(
            self.window_card,
            text="WINDOW",
            style="CardTitle.TLabel",
        ).pack(anchor="w")

        self.lbl_window_icon = tk.Label(
            self.window_card,
            text="▣",
            bg="#1D2939",
            fg="#98A2B3",
            font=("Segoe UI Symbol", 70),
        )
        self.lbl_window_icon.pack(pady=(20, 0))

        self.lbl_window_state = ttk.Label(
            self.window_card,
            text="CLOSED",
            style="State.TLabel",
        )
        self.lbl_window_state.pack(pady=(6, 8))

        ttk.Label(
            self.window_card,
            style="CardTitle.TLabel",
            wraplength=250,
        ).pack(anchor="center", pady=(0, 12))

    def _build_heater_card(self) -> None:
        ttk.Label(
            self.heater_card,
            text="HEATER",
            style="CardTitle.TLabel",
        ).pack(anchor="w")

        self.lbl_heater_icon = tk.Label(
            self.heater_card,
            text="▦\n≋≋≋",
            bg="#1D2939",
            fg="#98A2B3",
            font=("Segoe UI Symbol", 34, "bold"),
            justify="center",
        )
        self.lbl_heater_icon.pack(pady=(20, 0))

        self.lbl_heater_state = ttk.Label(
            self.heater_card,
            text="OFF",
            style="State.TLabel",
        )
        self.lbl_heater_state.pack(pady=(6, 8))

        ttk.Label(
            self.heater_card,
            style="CardTitle.TLabel",
            wraplength=250,
        ).pack(anchor="center", pady=(0, 12))
    
    def _configure_mqtt(self) -> None:
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        try:
            self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.client.loop_start()
        except Exception as exc:
            self._set_mqtt_label(f"● MQTT offline: {exc}", "#F97066")

    def _on_connect(self, client, userdata, flags, rc, properties=None) -> None:
        if rc == 0:
            self.mqtt_connected = True
            client.subscribe(TOPIC_ACTIONS, qos=1)
            self.root.after(
                0,
                lambda: self._set_mqtt_label("● MQTT connected", "#32D583"),
            )
            self.root.after(0, self.publish_current_state)
        else:
            self.root.after(
                0,
                lambda: self._set_mqtt_label(
                    f"● MQTT connection failed ({rc})",
                    "#F97066",
                ),
            )

    def _on_disconnect(
        self,
        client,
        userdata,
        disconnect_flags=None,
        reason_code=None,
        properties=None,
    ) -> None:
        self.mqtt_connected = False
        self.root.after(
            0,
            lambda: self._set_mqtt_label("● MQTT disconnected", "#F97066"),
        )

    def _on_message(self, client, userdata, msg) -> None:
        payload = msg.payload.decode("utf-8", errors="replace")
        actions = self._parse_actions(payload)

        if "open-window" in actions:
            self.root.after(0, lambda: self.set_window_state("open"))
        elif "close-window" in actions:
            self.root.after(0, lambda: self.set_window_state("closed"))

        if "turn-heater-on" in actions:
            self.root.after(0, lambda: self.set_heater_state("on"))
        elif "heater-off" in actions:
            self.root.after(0, lambda: self.set_heater_state("off"))

    @staticmethod
    def _parse_actions(payload: str) -> set[str]:
        actions = set()

        try:
            decoded = json.loads(payload)

            if isinstance(decoded, list):
                raw_actions = decoded
            elif isinstance(decoded, dict):
                raw_actions = decoded.get("actions", [])
            else:
                raw_actions = []

            for action in raw_actions:
                actions.add(str(action).split("(", 1)[0].strip().lower())

        except json.JSONDecodeError:
            for line in payload.splitlines():
                action = line.split("(", 1)[0].strip().lower()
                if action:
                    actions.add(action)

        return actions

    def set_window_state(self, state: str) -> None:
        if state not in ("open", "closed"):
            return

        self.window_state = state
        is_open = state == "open"

        self.lbl_window_state.config(text=state.upper())
        self.lbl_window_icon.config(
            text="▯" if is_open else "▣",
            fg="#32D583" if is_open else "#98A2B3",
        )

        self.publish_current_state()

    def set_heater_state(self, state: str) -> None:
        if state not in ("on", "off"):
            return

        self.heater_state = state
        is_on = state == "on"

        self.lbl_heater_state.config(text=state.upper())
        self.lbl_heater_icon.config(
            text="▦\n≋≋≋" if is_on else "▦",
            fg="#FDB022" if is_on else "#98A2B3",
        )

        self.publish_current_state()

    def publish_current_state(self) -> None:
        if not self.mqtt_connected:
            return

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")

        window_payload = {
            "status": f"window-{self.window_state}",
            "zone": "zone1",
            "timestamp": timestamp,
        }

        heater_payload = {
            "status": f"heater-{self.heater_state}",
            "zone": "zone1",
            "timestamp": timestamp,
        }

        self.client.publish(
            TOPIC_WINDOW_STATUS,
            json.dumps(window_payload),
            qos=1,
            retain=True,
        )

        self.client.publish(
            TOPIC_HEATER_STATUS,
            json.dumps(heater_payload),
            qos=1,
            retain=True,
        )

        print(
            f"[{time.strftime('%X')}] Published states: "
            f"window={self.window_state}, heater={self.heater_state}"
        )

    def _periodic_state_publish(self) -> None:
        self.publish_current_state()
        self.root.after(
            STATE_PUBLISH_INTERVAL_MS,
            self._periodic_state_publish,
        )

    def _set_mqtt_label(self, text: str, color: str) -> None:
        self.lbl_mqtt.config(text=text, foreground=color)

    def close(self) -> None:
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = WarehouseUI(root)
    root.protocol("WM_DELETE_WINDOW", app.close)
    root.mainloop()