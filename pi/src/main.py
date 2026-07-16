"""main.py

Launcher that ties `sensor_read`, `mqtt_process`, and `actuators` together.

Two concurrent responsibilities:
  1. Sensor loop  — reads sensors every `publish_interval` seconds and
                    publishes each reading to the MQTT broker.
  2. Actuator listener — subscribes to "delivery_request" and fires the
                    servos when the PC requests a delivery, then publishes
                    a "delivery_ack" back to the broker.

Both loops share a single MQTTProcessor / paho client connection so only
one TCP session is opened to the broker.
"""

import logging
import threading
import time

from sensor_read import gather_readings, load_config
from mqtt_process import MQTTProcessor, load_mqtt_config

# Import motor helpers and MQTT callbacks from actuators (no GPIO init runs
# at import time — that happens inside the try/except block in actuators.py).
import actuators

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("Main")


# ---------------------------------------------------------------------------
# Sensor publishing loop  (runs in a background thread)
# ---------------------------------------------------------------------------

def _sensor_loop(processor: MQTTProcessor, mqtt_cfg: dict) -> None:
    """Continuously read sensors and publish to the broker."""
    interval = mqtt_cfg.get("publish_interval", 1)
    zone     = mqtt_cfg.get("zone", "zone1")

    logger.info("Sensor loop started (interval=%ss, zone=%s)", interval, zone)
    try:
        while True:
            sensor_cfg = load_config()
            data = gather_readings(sensor_cfg, zone=zone)

            for name, val in data["sensors"].items():
                processor.publish_sensor(name, val, timestamp=data.get("timestamp"))

            time.sleep(interval)
    except Exception as exc:
        logger.exception("Sensor loop crashed: %s", exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    mqtt_cfg   = load_mqtt_config()
    load_config()  # validate sensor config at startup

    # One shared MQTTProcessor for both the sensor loop and the actuator
    processor = MQTTProcessor(mqtt_cfg)

    # Give actuators.py access to the same processor so it can publish acks.
    actuators.processor = processor

    try:
        processor.connect()
    except Exception as exc:
        logger.error("Failed to connect to MQTT broker: %s", exc)
        return

    # Wire the actuator callbacks onto the connected client.
    # Because loop_start() is already running in a background thread, these
    # callbacks will fire automatically without blocking the main thread.
    processor.client.on_connect = actuators._on_connect
    processor.client.on_message = actuators._on_message

    # Manually subscribe now (in case connection was established before callbacks were set)
    try:
        topic = f"{processor.building}/{processor.floor}/{processor.zone}/delivery_request"
        processor.client.subscribe(topic, qos=1)
        logger.info("Subscribed to '%s'", topic)
    except Exception as exc:
        logger.error("Failed to subscribe: %s", exc)

    logger.info("Actuator listener active (running in loop_start background thread)")

    # Run the sensor loop on the main thread
    try:
        _sensor_loop(processor, mqtt_cfg)
    except KeyboardInterrupt:
        logger.info("Shutting down …")
    finally:
        actuators._detach_servos()
        processor.disconnect()


if __name__ == "__main__":
    main()
