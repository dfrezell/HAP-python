"""A fake fan that does nothing but to demonstrate optional characteristics."""
import logging

from pyhap.accessory import Accessory
from pyhap.const import CATEGORY_GARAGE_DOOR_OPENER

import RPi.GPIO as GPIO
import atexit
import time

logger = logging.getLogger(__name__)


GARAGE_DOOR_OPEN = 0
GARAGE_DOOR_CLOSED = 1
GARAGE_DOOR_OPENING = 2
GARAGE_DOOR_CLOSING = 3
GARAGE_DOOR_STOPPED = 4

# number of seconds for garage to open/close
GARAGE_MOVING_DELAY = 15

# how many read samples to take from door sensor
DEBOUNCE_READS = 7
# how many 1 values to read before declaring door is open
DEBOUNCE_CLOSE_THRESHOLD = 3

# board pin location
GPIO_DOOR_SENSOR_1 = 32
GPIO_DOOR_SENSOR_2 = 36
GPIO_RELAY_IN_1 = 31
GPIO_RELAY_IN_2 = 35


# setup global GPIO stuff
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BOARD)

'''just stick the GPIO cleanup callback somewhere obnoxious'''
def gpio_cleanup():
    GPIO.cleanup()

atexit.register(gpio_cleanup)



class GarageDoorSensor(object):
    def __init__(self, pin, *args, **kwargs):
        self.gpio_pin = pin
        self.state = 1
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def read(self):
        states = []
        # take a number of reads with a 10 millisecond sleep between each read
        for x in range(DEBOUNCE_READS):
            states.append(GPIO.input(self.gpio_pin))
            time.sleep(.01)

        if 1 not in states:
            # if we read all zeroes, then we are most definitely closed
            self.state = 0
        elif states.count(1) > DEBOUNCE_CLOSE_THRESHOLD:
            # three or more reads with a 1, assume door is closed
            self.state = 1
        else:
            # not quite enough info to declare state, keep state unchanged
            pass

        logger.info("sensor read: %s", states)
        return GARAGE_DOOR_CLOSED if self.state == 0 else GARAGE_DOOR_OPEN

class GarageDoorButton(object):
    def __init__(self, pin, *args, **kwargs):
        self.gpio_pin = pin
        GPIO.setup(self.gpio_pin, GPIO.OUT, initial = GPIO.HIGH)

    def push(self):
        GPIO.output(self.gpio_pin, GPIO.LOW)
        time.sleep(.5)
        GPIO.output(self.gpio_pin, GPIO.HIGH)


class GarageDoor(Accessory):
    """Raspberry Pi Garage Door Opener"""

    category = CATEGORY_GARAGE_DOOR_OPENER


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.set_info_service("1.0", "Genie", "SD2500", "12345-678")

        service_garage = self.add_preload_service('GarageDoorOpener',
                chars=['CurrentDoorState', 'TargetDoorState', 'ObstructionDetected'])

        self.char_target_door_state = service_garage.configure_char('TargetDoorState')

        self.char_current_door_state = service_garage.configure_char('CurrentDoorState',
                getter_callback=self.get_door_state)
        self.char_obstruction_detected  = service_garage.configure_char('ObstructionDetected',
                getter_callback=self.get_obstruction)

        self.sensor = GarageDoorSensor(GPIO_DOOR_SENSOR_1)
        self.button = GarageDoorButton(GPIO_RELAY_IN_2)

        self.current_door_state = self.sensor.read()
        self.moving = 0

        self.char_target_door_state.value = self.current_door_state
        self.char_current_door_state.value = self.current_door_state


    def get_door_state(self):
        return self.current_door_state

    def get_obstruction(self):
        return False

    def _probe_door_state(self):
        state = self.sensor.read()

        if self.moving == 0:
            self.current_door_state = state
        elif self.moving > GARAGE_MOVING_DELAY:
            self.current_door_state = state
            self.moving = 0
        else:
            self.moving += 1

        return self.current_door_state

    def _toggle_door_state(self):
        if self.current_door_state not in (GARAGE_DOOR_CLOSING, GARAGE_DOOR_OPENING):
            self.button.push()
            self.moving = 1
            if self.current_door_state == GARAGE_DOOR_CLOSED:
                self.current_door_state = GARAGE_DOOR_OPENING
            else:
                self.current_door_state = GARAGE_DOOR_CLOSING

    @Accessory.run_at_interval(1)
    def run(self):
        state = self._probe_door_state()

        if self.char_target_door_state.value != state:
            self._toggle_door_state()

        if self.char_current_door_state.value != state:
            self.char_current_door_state.value = state
            self.char_current_door_state.notify()

