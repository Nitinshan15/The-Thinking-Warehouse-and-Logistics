from gpiozero import Servo
from gpiozero.pins.pigpio import PiGPIOFactory
from time import sleep

# Use pigpio for smooth, jitter-free hardware PWM
factory = PiGPIOFactory()

# Initialize Servo 1 on GPIO 17 and Servo 2 on GPIO 27
# (Adjust min/max pulse widths if your specific servos don't reach full range)
servo1 = Servo(17, pin_factory=factory, min_pulse_width=0.0005, max_pulse_width=0.0025)
servo2 = Servo(27, pin_factory=factory, min_pulse_width=0.0005, max_pulse_width=0.0025)



try:
    if(deliver_product_left):
        servo2.max()
        sleep(2)
        servo1.max()
        sleep(2)

    if(deliver_product_right):
        servo2.min()
        sleep(2)
        servo1.min()
        sleep(2)



except KeyboardInterrupt:
    print("\nStopping program.")
    # Detach both servos so they stop drawing holding current
    servo1.value = None
    servo2.value = None