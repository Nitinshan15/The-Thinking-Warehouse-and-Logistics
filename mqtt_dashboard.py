import os
import sys
import time
from collections import defaultdict
from datetime import datetime

import paho.mqtt.client as mqtt
from rich.console import Console
from rich.live import Live
from rich.table import Table

# ==========================================
# CONFIGURATION
# ==========================================
MQTT_BROKER = "192.168.0.199"  # Change to localhost or your broker IP
MQTT_PORT = 1883
MQTT_TOPIC = "#"  # '#' subscribes to ALL topics
MQTT_USER = None  # Add username if required
MQTT_PASS = None  # Add password if required

# Global dictionary to store the latest message details per topic
# Format: { topic: {"payload": str, "time": str, "count": int} }
topic_data = defaultdict(lambda: {"payload": "", "time": "", "count": 0})


def make_dashboard_table() -> Table:
    """Generates the Rich Table containing the current MQTT state."""
    table = Table(
        title=f"[bold green]MQTT Live Dashboard[/bold green] — Connected to [cyan]{MQTT_BROKER}[/cyan]",
        border_style="blue",
        highlight=True,
    )

    # Define columns
    table.add_column("Topic", style="magenta", no_wrap=True)
    table.add_column("Latest Payload", style="green")
    table.add_column("Last Updated", style="yellow", justify="center")
    table.add_column("Msg Count", style="cyan", justify="right")

    # If no data has arrived yet
    if not topic_data:
        table.add_row(
            "[italic dim]Waiting for data...[/italic dim]", "", "", ""
        )
        return table

    # Sort topics alphabetically for clean visual structure
    for topic in sorted(topic_data.keys()):
        data = topic_data[topic]
        table.add_row(
            topic,
            str(data["payload"]),
            data["time"],
            str(data["count"]),
        )

    return table


# ==========================================
# MQTT CALLBACKS
# ==========================================
def on_connect(client, userdata, flags, rc, properties=None):
    """Callback when client connects to broker."""
    if rc == 0:
        client.subscribe(MQTT_TOPIC)
    else:
        print(f"Connection failed with code {rc}")
        sys.exit(1)


def on_message(client, userdata, msg):
    """Callback when a MQTT message is received."""
    try:
        payload = msg.payload.decode("utf-8")
    except UnicodeDecodeError:
        payload = f"<Binary Data: {len(msg.payload)} bytes>"

    # Update our global state
    topic_data[msg.topic]["payload"] = payload
    topic_data[msg.topic]["time"] = datetime.now().strftime("%H:%M:%S")
    topic_data[msg.topic]["count"] += 1


# ==========================================
# MAIN EXECUTION
# ==========================================
def main():
    # paho-mqtt v2.x compatibility
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2
    )

    if MQTT_USER and MQTT_PASS:
        client.username_pw_set(MQTT_USER, MQTT_PASS)

    client.on_connect = on_connect
    client.on_message = on_message

    console = Console()
    console.print(
        f"[yellow]Connecting to MQTT Broker at {MQTT_BROKER}:{MQTT_PORT}...[/yellow]"
    )

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
    except Exception as e:
        console.print(f"[red]Could not connect: {e}[/red]")
        sys.exit(1)

    # Start the network loop in the background
    client.loop_start()

    # Clear screen initially
    os.system("cls" if os.name == "nt" else "clear")

    # Run the live-updating UI
    try:
        with Live(
            make_dashboard_table(), screen=True, auto_refresh=False
        ) as live:
            while True:
                # Update the table UI with fresh data
                live.update(make_dashboard_table(), refresh=True)
                time.sleep(0.2)  # Limit UI redraw to ~5 times a second
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping MQTT client...[/yellow]")
    finally:
        client.loop_stop()
        client.disconnect()
        console.print("[green]Disconnected cleanly.[/green]")


if __name__ == "__main__":
    main()