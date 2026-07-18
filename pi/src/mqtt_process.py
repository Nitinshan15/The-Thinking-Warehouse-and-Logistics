"""mqtt_process.py

Provides a small MQTT helper that connects to a mosquitto broker and
exposes `publish_all` and `publish_sensor` methods used by `main.py`.
"""
import json
import logging
import os
import time
from uuid import uuid4

try:
    import paho.mqtt.client as mqtt
except Exception:
    mqtt = None

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MQTT_CONFIG_PATH = os.path.join(BASE_DIR, "configs", "mqtt_config.json")


def load_mqtt_config(path=MQTT_CONFIG_PATH):
    default = {
        "host": "localhost",
        "port": 1883,
        "base_topic": "sensors",
        "client_id": "Warehouse1",
        "zone": "zone1",
        "building": "building1",
        "floor": "floor0",
        "publish_interval": 1
    }
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            cfg = json.load(f)
            default.update(cfg)
            return default
    except Exception:
        return default


class MQTTProcessor:
    def __init__(self, config=None):
        self.cfg = config or load_mqtt_config()
        self.host = self.cfg.get("host")
        self.port = self.cfg.get("port", 1883)
        self.base = self.cfg.get("base_topic", "sensors")
        self.zone = self.cfg.get("zone", "zone1")
        self.building = self.cfg.get("building", "building1")
        self.floor = self.cfg.get("floor", "floor0")
        self.client_id = self.cfg.get("client_id")
        self.client = None

    def connect(self):
        if mqtt is None:
            raise RuntimeError("paho-mqtt is not installed")
        self.client = mqtt.Client(client_id=self.client_id)
        try:
            self.client.connect(self.host, self.port)
            self.client.loop_start()
            logging.info("MQTT connected to %s:%s", self.host, self.port)
        except Exception as e:
            logging.error("MQTT connect failed: %s", e)
            raise

    def disconnect(self):
        try:
            if self.client:
                self.client.loop_stop()
                self.client.disconnect()
        except Exception:
            pass

    def publish(self, topic, payload):
        if self.client is None:
            raise RuntimeError("MQTT client not connected")
        # ensure payload contains a timestamp
        try:
            if isinstance(payload, dict) and "timestamp" not in payload:
                payload = dict(payload)
                payload["timestamp"] = time.time()
        except Exception:
            pass

        self.client.publish(topic, json.dumps(payload))

    def publish_all(self, payload):
        building = payload.get("building", self.building)
        zone = payload.get("zone", self.zone)
        topic = f"{building}/{self.floor}/{zone}/all"
        self.publish(topic, payload)

    def publish_sensor(self, name, data, timestamp=None):
        # Derive building/zone from data if present
        building = None
        zone = None
        if isinstance(data, dict):
            building = data.get("zone") or data.get("building")
            zone = data.get("zone")

        # fallback to processor config
        building = building or self.building
        zone = zone or self.zone

        # Map sensor keys to required topic names and payloads
        if name == "temperature_humidity":
            # publish temperature and humidity separately
            temp = data.get("temperature_c") if isinstance(data, dict) else None
            hum = data.get("humidity_pct") if isinstance(data, dict) else None
            if temp is not None:
                topic_t = f"{building}/{self.floor}/{zone}/temperature"
                self.publish(topic_t, {"temperature_c": temp, "temphigh_threshold": data.get("temphigh_threshold"), "templow_threshold": data.get("templow_threshold"), "timestamp": timestamp})
            if hum is not None:
                topic_h = f"{building}/{self.floor}/{zone}/humidity"
                self.publish(topic_h, {"humidity_pct": hum, "threshold": data.get("humidity_threshold"), "timestamp": timestamp})
            return

        if name == "sound":
            topic = f"{building}/{self.floor}/{zone}/sound"
            payload = {"raw_max": data.get("raw_max") if isinstance(data, dict) else data, "threshold": data.get("threshold") if isinstance(data, dict) else None, "timestamp": timestamp}
            self.publish(topic, payload)
            return

        if name == "light":
            topic = f"{building}/{self.floor}/{zone}/light"
            self.publish(topic, {"raw": data.get("raw"), "lighthigh_threshold": data.get("lighthigh_threshold"), "lightlow_threshold": data.get("lightlow_threshold"), "timestamp": timestamp})
            return

        if name == "motion":
            topic = f"{building}/{self.floor}/{zone}/motiondetected"
            # raw is expected under data['raw'] or as a value
            val = data.get("raw") if isinstance(data, dict) else data
            self.publish(topic, {"value": val, "timestamp": timestamp})
            return

        if name == "ultrasonic":
            # publish presence under productdetected, and full data under ultrasonic
            present = data.get("present") if isinstance(data, dict) else None
            topic_p = f"{building}/{self.floor}/{zone}/productdetected"
            self.publish(topic_p, {"present": present, "timestamp": timestamp})
            # also publish ultrasonic raw/calibrated
            topic_u = f"{building}/{self.floor}/{zone}/ultrasonic"
            self.publish(topic_u, {"raw": data.get("raw"), "threshold": data.get("threshold"), "timestamp": timestamp})
            return

        # # default: publish under sensor name
        # topic = f"{building}/{self.floor}/{zone}/{name}"
        # payload = {"data": data, "timestamp": timestamp}
        # self.publish(topic, payload)


__all__ = ["MQTTProcessor", "load_mqtt_config"]
