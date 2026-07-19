"""sensor_read.py

This module reads raw sensor values (GrovePi+ / ultrasonic / DHT)
and returns exact sensor readings and calibrated values.

Design goals:
- No interpretation or boolean classification of sensor values.
- Provide a simple API `gather_readings()` for external publishers.
"""

import json
import math
import time
import random
import os

import grovepi
import logging



# ---- Pin assignments -- adjust these to match your actual wiring ----
LIGHT_PORT = 1        # analog A1
SOUND_PORT = 0        # analog A0
MOTION_PORT = 4       # digital D2 (PIR)
ULTRASONIC_PORT = 3   # digital D3
DHT_PORT = 7          # digital D4 (combined temperature + humidity sensor)
DHT_MODULE_TYPE = 0   # 0 = blue/white Grove DHT, 1 = DHT22 variant

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.path.join(BASE_DIR, "configs", "sensor_configs.json")

# Motion detection persistence: keep motion true for 30 seconds after detection
_motion_last_detected = None
MOTION_PERSISTENCE_SECONDS = 30

grovepi.pinMode(SOUND_PORT, "INPUT")
grovepi.pinMode(LIGHT_PORT, "INPUT")
grovepi.pinMode(MOTION_PORT, "INPUT")

logger = logging.getLogger(__name__)


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    except json.JSONDecodeError as exc:
        logger.error(
            "Invalid sensor configuration; retaining last valid config: %s",
            exc,
        )
        return None


# mqtt config is handled by mqtt_process.py; sensor_read only needs sensor_configs


def analog_read(port):
    return grovepi.analogRead(port) 

def digital_read(port):
    return grovepi.digitalRead(port) 

def ultrasonic_read(port):
    return grovepi.ultrasonicRead(port) 

def dht_read(port, module_type):
    return grovepi.dht(port, module_type) 


# ============================================================
# Individual sensor readers -- each classified against config
# ============================================================

def read_motion_raw():
    """Return digital value from PIR (0/1), keeping motion true for 30 seconds after detection."""
    global _motion_last_detected
    
    raw = digital_read(MOTION_PORT)
    now = time.time()
    
    # If motion detected now, update the timestamp
    if raw == 1:
        _motion_last_detected = now
        return 1
    
    # If no motion detected, check if we're still within the persistence window
    if _motion_last_detected is not None:
        time_since_detection = now - _motion_last_detected
        if time_since_detection < MOTION_PERSISTENCE_SECONDS:
            return 1
        else:
            _motion_last_detected = None
    
    return 0

def read_light_raw_and_calibrated(config):
    cfg = config.get("light_sensor", {})
    raw = analog_read(LIGHT_PORT)
    cal = raw - cfg.get("light_sensor_calibration", 0)
    return {"raw": raw, "lighthigh_threshold": cfg.get("lighthigh_threshold"), "lightlow_threshold": cfg.get("lightlow_threshold")}


def read_sound_raw(config, samples=50, sample_delay=0.005):
    cfg = config.get("sound_sensor", {})
    threshold = cfg.get("soundhigh_threshold")

    max_raw = float("-inf")
    for _ in range(samples):
        raw = analog_read(SOUND_PORT)
        if raw > max_raw:
            max_raw = raw
        time.sleep(sample_delay)

    return {"raw_max": max_raw, "threshold": threshold}


def read_ultrasonic_raw_and_calibrated(config):
    cfg = config.get("ultrasonic_sensor", {})
    raw = ultrasonic_read(ULTRASONIC_PORT)
    cal = cfg.get("ultrasonic_sensor_calibration", 0)
    threshold = cfg.get("objectdetected_threshold")
    # determine presence (True if calibrated is less than threshold)
    present = False
    if (raw - cal) < threshold:
        present = True
    else:
        present = False

    # print presence as requested
    #print(present)

    return {"raw": raw, "calibrated": cal, "threshold": threshold, "present": present}


_last_dht_read = {
    "timestamp": 0,
    "temperature": None,
    "humidity": None,
}


def _is_valid_dht_read(temp, humidity):
    if temp is None or humidity is None:
        return False
    if isinstance(temp, float) and math.isnan(temp):
        return False
    if isinstance(humidity, float) and math.isnan(humidity):
        return False
    return True


def read_temperature_and_humidity_raw(config):
    global _last_dht_read
    now = time.time()
    read_new = False

    if _last_dht_read["temperature"] is None or _last_dht_read["humidity"] is None:
        read_new = True
    elif now - _last_dht_read["timestamp"] >= 1.0:
        read_new = True

    if read_new:
        temp, humidity = dht_read(DHT_PORT, DHT_MODULE_TYPE)
        if _is_valid_dht_read(temp, humidity):
            _last_dht_read["timestamp"] = now
            _last_dht_read["temperature"] = temp
            _last_dht_read["humidity"] = humidity
        else:
            temp = _last_dht_read["temperature"]
            humidity = _last_dht_read["humidity"]
    else:
        temp = _last_dht_read["temperature"]
        humidity = _last_dht_read["humidity"]

    temp_cfg = config.get("temperature_sensor", {})
    hum_cfg = config.get("humidity_sensor", {})
    humidity_threshold = hum_cfg.get("humidityhigh_threshold") or hum_cfg.get("humidifieroff_threshold")
    return {
        "temperature_c": temp,
        "humidity_pct": humidity,
        "temphigh_threshold": temp_cfg.get("temphigh_threshold"),
        "templow_threshold": temp_cfg.get("templow_threshold"),
        "humidity_threshold": humidity_threshold,
    }


def gather_readings(config=None, zone="zone1", building="building1"):
    """Gather raw & calibrated readings and thresholds for all sensors."""
    if config is None:
        config = load_config()
    # read ultrasonic — the reader now computes and prints presence
    ultrasonic_data = read_ultrasonic_raw_and_calibrated(config)

    data = {
        "zone": zone,
        "building": building,
        "timestamp": time.time(),
        "sensors": {
            "motion": {"raw": read_motion_raw()},
            "light": read_light_raw_and_calibrated(config),
            "sound": read_sound_raw(config),
            "ultrasonic": ultrasonic_data,
            "temperature_humidity": read_temperature_and_humidity_raw(config),
        }
    }

    try:
        motion_raw = data["sensors"]["motion"]["raw"]
        light_raw = data["sensors"]["light"]["raw"]
        sound_raw = data["sensors"]["sound"]["raw_max"]
        us_raw = data["sensors"]["ultrasonic"]["raw"]
        temp = data["sensors"]["temperature_humidity"]["temperature_c"]
        hum = data["sensors"]["temperature_humidity"]["humidity_pct"]
        motion_text = "true" if motion_raw else "false"
        print(f"Sound : {sound_raw}   | Light : {light_raw}   | Ultrasonic : {us_raw} cm | Temp: {temp:.2f}°C | Hum: {hum:.2f}% | Motion: {motion_text}")
    except Exception:
        pass

    return data

