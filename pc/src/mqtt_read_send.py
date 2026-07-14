"""mqtt_read_send.py

Subscribe to MQTT messages and print each received payload in a single line.
"""
import json
import logging
import os

global payload

try:
    import paho.mqtt.client as mqtt
except Exception:
    mqtt = None

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.path.join(BASE_DIR, "configs", "mqtt.json")


def load_config(path=CONFIG_PATH):
    default = {
        "host": "localhost",
        "port": 1883,
        "client_id": "Warehouse1Reader",
        "subscribe_topics": ["building1/floor0/zone1/#"],
        "qos": 0
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


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logging.info("Connected to MQTT broker")
        for topic in userdata["subscribe_topics"]:
            client.subscribe(topic, qos=userdata.get("qos", 0))
            logging.info("Subscribed to %s", topic)
    else:
        logging.error("MQTT connection failed with code %s", rc)


def on_message(client, userdata, msg):
    global payload
    payload = msg.payload.decode("utf-8", errors="replace")
    print(f"{msg.topic} {payload}")



def main_mqtt():
    logging.basicConfig(level=logging.INFO)
    config = load_config()

    if mqtt is None:
        logging.error("paho-mqtt is not installed. Install with `pip install paho-mqtt`.")
        return

    client = mqtt.Client(client_id=config.get("client_id"), userdata=config)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(config["host"], config["port"])
    except Exception as e:
        logging.error("Cannot connect to MQTT broker %s:%s — %s", config["host"], config["port"], e)
        return

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        logging.info("Stopping MQTT subscriber")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main_mqtt()
