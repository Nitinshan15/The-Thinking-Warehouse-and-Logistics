"""main.py

Launcher that ties `sensor_read` and `mqtt_process` together.
Reads sensor configs and publishes raw readings via MQTT.
"""
import time
import logging
from sensor_read import gather_readings, load_config
from mqtt_process import MQTTProcessor, load_mqtt_config

logging.basicConfig(level=logging.INFO)


def main():
    mqtt_cfg = load_mqtt_config()
    sensor_cfg = load_config()

    processor = MQTTProcessor(mqtt_cfg)
    try:
        processor.connect()
    except Exception as e:
        logging.error("Failed to connect to MQTT broker: %s", e)
        return

    interval = mqtt_cfg.get("publish_interval", 1)
    zone = mqtt_cfg.get("zone", "zone1")

    try:
        while True:
            sensor_cfg = load_config()
            data = gather_readings(sensor_cfg, zone=zone)

            # publish aggregated
            #processor.publish_all(data)

            # publish per-sensor
            for name, val in data["sensors"].items():
                processor.publish_sensor(name, val, timestamp=data.get("timestamp"))

            time.sleep(interval)
    except KeyboardInterrupt:
        logging.info("Stopping main loop")
    finally:
        processor.disconnect()


if __name__ == "__main__":
    main()
