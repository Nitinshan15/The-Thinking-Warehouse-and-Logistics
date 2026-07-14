"""
calibrate_sensors.py

Watch LIVE light and sound sensor readings so you can work out correct
values for sensor_configs.json (the current ones are placeholders).

Usage:
    python3 calibrate_sensors.py

What it does:
  1. Samples the light sensor for a few seconds while the room is in
     its normal state, and reports min/max/avg + a suggested
     calibration baseline.
  2. Samples the sound sensor in a quiet 50-sample burst (the same
     burst size production code uses) to find a quiet baseline.
  3. Prompts you to make a loud noise, then runs another 50-sample
     burst so you can see the MAX value during an actual loud event --
     that's the number that matters, since a single reading could
     easily miss a brief spike.
  4. Prints suggested values to drop into sensor_configs.json.
"""

import time
import statistics

try:
    import grovepi
    HARDWARE_AVAILABLE = True
except Exception:
    HARDWARE_AVAILABLE = False

LIGHT_PORT = 1
SOUND_PORT = 0


def analog_read(port):
    if not HARDWARE_AVAILABLE:
        raise RuntimeError("grovepi library not available; run this on the Raspberry Pi with GrovePi installed")
    return grovepi.analogRead(port)


def calibrate_light(duration_s=5, delay=0.1):
    print(f"\n--- LIGHT sensor: sampling for {duration_s}s (keep room in its normal state) ---")
    readings = []
    start = time.time()
    while time.time() - start < duration_s:
        raw = analog_read(LIGHT_PORT)
        readings.append(raw)
        print(f"  light raw = {raw}")
        time.sleep(delay)

    _print_stats("light", readings)
    return readings


def calibrate_sound_burst(label, samples=50, delay=0.01):
    """
    Mirrors the production read_sound_high() approach exactly: a rapid
    burst of samples, reporting the MAX (the value production code
    actually reacts to) alongside the average baseline.
    """
    print(f"\n--- SOUND sensor burst ({label}): {samples} samples ---")
    readings = []
    for _ in range(samples):
        raw = analog_read(SOUND_PORT)
        readings.append(raw)
        time.sleep(delay)

    _print_stats("sound", readings)
    print(f"  -> MAX during this burst: {max(readings)}  "
          f"(this is what production code compares against the threshold)")
    return readings


def _print_stats(label, readings):
    print(f"\n{label} stats over {len(readings)} samples:")
    print(f"  min = {min(readings)}")
    print(f"  max = {max(readings)}")
    print(f"  avg = {statistics.mean(readings):.1f}")
    print(f"  suggested calibration (baseline) = {round(statistics.mean(readings))}")


if __name__ == "__main__":

    calibrate_light()

    print("\nStay quiet for the next burst (baseline)...")
    quiet_readings = calibrate_sound_burst("quiet baseline")

    input("\nPress Enter, then make a loud noise (clap / speak loudly) "
          "and keep it up for about a second...")
    loud_readings = calibrate_sound_burst("loud event")

    quiet_avg = statistics.mean(quiet_readings)
    loud_max = max(loud_readings)
    suggested_threshold = round(loud_max - quiet_avg)

    print("\n================ SUGGESTED sensor_configs.json VALUES ================")
    print(f'  "sound_sensor_calibration": {round(quiet_avg)}   (from quiet baseline avg)')
    print(f'  "soundhigh_threshold": {suggested_threshold}   '
          f"(loud MAX {loud_max:.0f} - quiet baseline {quiet_avg:.0f}, add a little margin)")
    print("  For light: use the light 'avg' printed above as light_sensor_calibration,")
    print("  and pick lighton_threshold as a negative offset below that baseline")
    print("  (test by dimming the room and re-running this script).")
    print("========================================================================")
