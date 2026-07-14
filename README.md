# The Thinking Warehouse & Logistics

A Smart Cities / IoT project using **AI planning (PDDL)** to automate a warehouse zone. A Raspberry Pi collects sensor data over MQTT; a PC synthesises a PDDL problem, solves it with a classical planner, and drives actuators via MQTT.

---



## Project Structure

```
├── mqtt_dashboard.py        # Live terminal MQTT monitor (optional)
├── pc/
│   ├── configs/mqtt.json    # Broker config
│   ├── pddl/domain.pddl    # PDDL domain & actions
│   └── src/
│       ├── warehouse.py     # GUI + planner + MQTT client
│       └── mqtt_read_send.py
└── pi/
    ├── configs/             # Broker & sensor thresholds
    └── src/
        ├── main.py          # Entry point
        ├── sensor_read.py   # GrovePi sensor drivers
        ├── mqtt_process.py  # MQTT publisher
        └── actuators.py     # Servo control
```

---

## Quick Start

### Requirements
- Python 3.9+, Mosquitto MQTT broker

### Raspberry Pi
```bash
pip install paho-mqtt gpiozero pigpio
# + GrovePi library: https://github.com/DexterInd/GrovePi
python pi/src/main.py
```

### PC
```bash
pip install paho-mqtt unified-planning matplotlib rich
python pc/src/warehouse.py
```

> Update `host` in `pi/configs/mqtt_config.json` and `pc/configs/mqtt.json` to your broker's IP.

---

## Hardware

GrovePi+ shield on Raspberry Pi with: PIR (D4), Light (A1), Sound (A0), Ultrasonic (D3), DHT (D7), and two servo motors (GPIO 17, 27).

---

*Smart Cities & IoT — University of Stuttgart, Semester 2*
