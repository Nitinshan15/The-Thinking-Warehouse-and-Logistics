"""actuators.py

Motor-control helpers and MQTT callbacks for the Raspberry Pi actuator layer.

This module is imported by main.py, which wires the callbacks onto the shared
MQTT client and calls _detach_servos() on shutdown.

Delivery flow (orchestrated by main.py):
  1. PC publishes to "delivery_request":
       { "command": "deliver_left"|"deliver_right",
         "transaction_id": "<id>",
         "item_id": "<id>",
         "destination": "<name>" }
  2. _on_message() dispatches to _handle_delivery_request().
  3. Motors run (guide first, then gate).
  4. "delivery_ack" is published back to the broker:
       { "transaction_id": "<id>",
         "item_id": "<id>",
         "status": "delivered"|"failed" }
"""

import json
import logging
import time
import sys
from plugwise_control import PlugwiseController
import re
from mqtt_process import MQTTProcessor, load_mqtt_config

import RPi.GPIO as GPIO
from grovepi import *


PORT = "/dev/ttyUSB0"
MY_PLUGS = ["000D6F0005693504", "000D6F0004B59311"]
MAC_FAN = "000D6F0005693504"
MAC_HUMIDIFIER = "000D6F0004B59311"

controller = PlugwiseController(serial_port=PORT, mac_addresses=MY_PLUGS)
controller.initialize()

# Configure GPIO pins for the servos using physical board layout
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BOARD)
GPIO.setup(38, GPIO.OUT)
GPIO.setup(40, GPIO.OUT)

# Initialize PWM on both pins at 50Hz (20ms period)
servo1_pwm = GPIO.PWM(38, 50)  # gate motor
servo2_pwm = GPIO.PWM(40, 50)  # guide motor

# Start PWM with 0 duty cycle (off/neutral to stop drawing holding current)
servo1_pwm.start(0)
servo2_pwm.start(0)

PIN_LED = 2  # GPIO pin for the light relay
pinMode(PIN_LED, "OUTPUT")  # Set the pin mode for the light relay

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("Actuator")

# ---------------------------------------------------------------------------
# MQTT setup
# ---------------------------------------------------------------------------
mqtt_cfg = load_mqtt_config()
processor = MQTTProcessor(mqtt_cfg)

DELIVERY_REQUEST_TOPIC = "delivery_request"
DELIVERY_ACK_TOPIC     = "delivery_ack"

FAN_ACT_STATUS_TOPIC = "building1/floor0/zone1/fan_actuator_status"
# ---------------------------------------------------------------------------
# Motor control helpers
# ---------------------------------------------------------------------------

def _run_guide_left():
    """Guide motor → left  (Frankfurt side) at 135 degrees."""
    logger.info("[MOTOR] Guide motor → LEFT (135°)")
    # 135 degrees = 10.0% duty cycle
    servo2_pwm.ChangeDutyCycle(10.0)
    time.sleep(2)
    servo2_pwm.ChangeDutyCycle(0)


def _run_guide_right():
    """Guide motor → right  (Stuttgart side) at 45 degrees."""
    logger.info("[MOTOR] Guide motor → RIGHT (45°)")
    # 45 degrees = 5.0% duty cycle
    servo2_pwm.ChangeDutyCycle(5.0)
    time.sleep(2)
    servo2_pwm.ChangeDutyCycle(0)


def _open_gate():
    """Gate motor → open at 135 degrees (let the product slide through)."""
    logger.info("[MOTOR] Gate motor → OPEN (135°)")
    # 135 degrees = 10.0% duty cycle
    servo1_pwm.ChangeDutyCycle(10.0)
    time.sleep(2)
    servo1_pwm.ChangeDutyCycle(0)


def _close_gate():
    """Gate motor → close at 45 degrees."""
    logger.info("[MOTOR] Gate motor → CLOSE (45°)")
    # 45 degrees = 5.0% duty cycle
    servo1_pwm.ChangeDutyCycle(5.0)
    time.sleep(2)
    servo1_pwm.ChangeDutyCycle(0)


def _detach_servos():
    try:
        servo1_pwm.stop()
        servo2_pwm.stop()
        GPIO.cleanup()
        logger.info("[MOTOR] Servos stopped and GPIO cleaned up.")
    except Exception as exc:
        logger.error("Error during GPIO cleanup: %s", exc)


# ---------------------------------------------------------------------------
# Delivery handler
# ---------------------------------------------------------------------------

def _handle_delivery_request(payload_str: str):
    """
    Parse the delivery_request payload, operate the motors,
    and publish a delivery_ack back to the broker.
    """
    try:
        data = json.loads(payload_str)
    except json.JSONDecodeError as exc:
        logger.error("Bad JSON in delivery_request: %s — %s", payload_str, exc)
        return

    command        = data.get("command", "")         # "deliver_left" | "deliver_right"
    transaction_id = data.get("transaction_id", "")
    item_id        = transaction_id.split("_")[0] if (transaction_id and "_" in transaction_id) else "unknown"
    destination    = data.get("destination", "unknown")

    logger.info(
        "[DELIVERY] tx=%s | item=%s | dest=%s | cmd=%s",
        transaction_id, item_id, destination, command,
    )

    status = "failed"
    try:
        if command == "deliver_left":
            # Guide motor directs product left → gate opens → product delivered
            _run_guide_left()
            _open_gate()
            logger.info("[DELIVERY] ✅ Product delivered LEFT to %s", destination)
            status = "delivered"
            _close_gate()

        elif command == "deliver_right":
            # Guide motor directs product right → gate opens → product delivered
            _run_guide_right()
            _open_gate()
            logger.info("[DELIVERY] ✅ Product delivered RIGHT to %s", destination)
            status = "delivered"
            _close_gate()
            
        else:
            logger.warning("[DELIVERY] Unknown command '%s' — no motor action taken.", command)

    except Exception as exc:
        logger.exception("[DELIVERY] Motor error during %s: %s", command, exc)
        status = "failed"

    # Always publish the ack so the PC can unlock its UI
    ack_payload = {
        "transaction_id": transaction_id,
        "item_id":        item_id,
        "destination":    destination,
        "status":         status,
        "timestamp":      time.time(),
    }
    try:
        processor.client.publish(DELIVERY_ACK_TOPIC, json.dumps(ack_payload), qos=1)
        logger.info("[DELIVERY ACK] Published → %s : %s", DELIVERY_ACK_TOPIC, ack_payload)
    except Exception as exc:
        logger.error("[DELIVERY ACK] Failed to publish ack: %s", exc)

def _handle_actions_request(payload_str: str):

    
    raw_payload = payload_str
    try:
        actions_list = [line.strip() for line in raw_payload.split("\n") if line.strip()]
    
        print(f"\n[{time.strftime('%X')}] Received Action Batch. Processed List: {actions_list}")
    
        clean_actions = [re.sub(r"\([^)]*\)", "", action) for action in actions_list]

        
        # --- FAN CONTROLS ---
        if "turn-fan-on" in clean_actions:
            print("[*] Target found: Fan -> Command: ON")
            controller.turn_on(MAC_FAN)
            mode = "fan-on"
        
        elif "turn-fan-off" in clean_actions:
            print("[*] Target found: Fan -> Command: OFF")
            controller.turn_off(MAC_FAN)
            mode = "fan-off"


        else:
            print("[*] Going to default state : Fan -> Command: OFF")
            controller.turn_off(MAC_FAN)
            mode = "fan-off"

        payload_fan_state = {"status": mode}
        processor.client.publish(FAN_ACT_STATUS_TOPIC, json.dumps(payload_fan_state), qos=1, retain=True)


        # --- HUMIDIFIER CONTROLS ---
        if "humidifier-turn-on" in clean_actions:
            print("[*] Target found: Humidifier -> Command: ON")
            controller.turn_on(MAC_HUMIDIFIER)

        else:
            print("[*] Target found: Humidifier -> Command: OFF")
            controller.turn_off(MAC_HUMIDIFIER)
        
        if "lights-on" in clean_actions:
            print("[*] Target found: Light -> Command: ON")
            digitalWrite(PIN_LED, GPIO.HIGH)
        else:
            print("[*] Target found: Light -> Command: OFF")
            digitalWrite(PIN_LED, GPIO.LOW)


    except Exception as e:
        print(f"[-] Failed to process MQTT command action: {e}")

# ---------------------------------------------------------------------------
# MQTT callbacks
# ---------------------------------------------------------------------------

def _on_connect(client, userdata, flags, rc):
    if rc == 0:
        logger.info("Connected to MQTT Broker successfully.")
        
        # Define topics relative to the shared processor
        delivery_topic = f"{processor.building}/{processor.floor}/{processor.zone}/delivery_request"
        actions_topic  = f"{processor.building}/{processor.floor}/{processor.zone}/actions"
        
        # 💡 SUBSCRIPTIONS HAPPEN HERE NOW
        client.subscribe(delivery_topic, qos=1)
        client.subscribe(actions_topic, qos=1)
        logger.info("Subscribed/Re-subscribed to topics.")
    else:
        logger.error("Connection failed with code %d", rc)


def _on_message(client, userdata, msg):
    topic   = msg.topic
    payload = msg.payload.decode("utf-8", errors="replace")
    logger.info("[MQTT] Received on '%s': %s", topic, payload)

    delivery_topic = f"{processor.building}/{processor.floor}/{processor.zone}/delivery_request"
    actions_topic  = f"{processor.building}/{processor.floor}/{processor.zone}/actions"
    if topic == delivery_topic:
        _handle_delivery_request(payload)
    if topic == actions_topic:
        _handle_actions_request(payload)
