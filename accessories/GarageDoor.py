"""
Garage Door Opener for my old Genie ScrewDrive 2500

Sensor: SM-226L-3Q Seco-Larm Overhead Door Mount
Relay : 
"""
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


class GarageDoorSensor(object):
    '''GarageDoorSensor'''
    SENSOR_STATE_OPEN = 1
    SENSOR_STATE_CLOSED = 0

    def __init__(self, gpio, debounce, **kwargs):
        self.gpio_pin = gpio["pin"]
        self.gpio_pud = gpio["pull_up_down"]
        self.debounce = debounce
        self.kwargs = kwargs
        self.state = GarageDoorSensor.SENSOR_STATE_OPEN

        if self.gpio_pud == "pullup":
            self.gpio_pud = GPIO.PUD_UP
        elif self.gpio_pud == "pulldown":
            self.gpio_pud = GPIO.PUD_DOWN
        else:
            raise ValueError("invalid pull_up_down: {0}".format(self.gpio_pud))

        GPIO.setup(self.gpio_pin, GPIO.IN, pull_up_down=self.gpio_pud)

    def read(self):
        '''read'''
        states = []
        # take a number of reads with a 10 millisecond sleep between each read
        for _ in range(self.debounce["reads"]):
            states.append(GPIO.input(self.gpio_pin))
            time.sleep(self.debounce["interval"])

        if states.count(GarageDoorSensor.SENSOR_STATE_OPEN) >= self.debounce["open_threshold"]:
            # if we read all zeroes, then we are most definitely closed
            self.state = GarageDoorSensor.SENSOR_STATE_OPEN
        elif states.count(GarageDoorSensor.SENSOR_STATE_CLOSED) >= self.debounce["close_threshold"]:
            # three or more reads with a 1, assume door is closed
            self.state = GarageDoorSensor.SENSOR_STATE_CLOSED
        else:
            # not quite enough info to declare state, keep state unchanged
            pass

        logger.info("sensor read: %s", states)
        return GARAGE_DOOR_CLOSED if (self.state == GarageDoorSensor.SENSOR_STATE_CLOSED) else GARAGE_DOOR_OPEN

class GarageDoorButton(object):
    '''GarageDoorButton'''
    def __init__(self, gpio, *args, **kwargs):
        self.gpio_pin = gpio["pin"]
        self.gpio_active = GPIO.HIGH
        if gpio["active"] == "low":
            self.gpio_active = GPIO.LOW
            self.gpio_inactive = GPIO.HIGH
        elif gpio["active"] == "high":
            self.gpio_active = GPIO.HIGH
            self.gpio_inactive = GPIO.LOW
        GPIO.setup(self.gpio_pin, GPIO.OUT, initial=self.gpio_active)

    def push(self):
        '''push'''
        GPIO.output(self.gpio_pin, self.gpio_active)
        time.sleep(.5)
        GPIO.output(self.gpio_pin, self.gpio_inactive)


class GarageDoor(Accessory):
    """Raspberry Pi Garage Door Opener"""

    category = CATEGORY_GARAGE_DOOR_OPENER
    gpio_mode = None

    def __init__(self, driver, display_name, aid=None, **kwargs):
        super().__init__(driver, display_name, aid)
        self.kwargs = kwargs
        
        self.set_info_service(**kwargs["info"])

        service_garage = self.add_preload_service('GarageDoorOpener',
                chars=['CurrentDoorState', 'TargetDoorState', 'ObstructionDetected'])

        self.char_target_door_state = service_garage.configure_char('TargetDoorState',
                setter_callback=self.set_target_state)
        self.char_current_door_state = service_garage.configure_char('CurrentDoorState',
                getter_callback=self.get_door_state)
        self.char_obstruction_detected  = service_garage.configure_char('ObstructionDetected',
                getter_callback=self.get_obstruction)

        self.sensor = GarageDoorSensor(**kwargs["sensor"])
        self.button = GarageDoorButton(**kwargs["relay"])

        self.current_door_state = self.sensor.read()
        self.target_door_update = False
        self.moving = 0

        self.char_current_door_state.value = self.current_door_state

    @classmethod
    def setup(cls, mode):
        '''setup'''
        if cls.gpio_mode is not None:
            if mode != cls.gpio_mode:
                raise ValueError("new mode: {0} conflicts with previous mode: {1}".format(
                    mode, cls.gpio_mode))
        else:
            atexit.register(cls.cleanup)
            GPIO.setwarnings(False)

            if mode == "board":
                GPIO.setmode(GPIO.BOARD)
            elif mode == "bcm":
                GPIO.setmode(GPIO.BCM)
            else:
                raise ValueError("invalid mode {0}: expected 'bcm' or 'board'".format(mode))

            cls.gpio_mode = mode

    @classmethod
    def cleanup(cls):
        '''cleanup'''
        GPIO.cleanup()

    def set_target_state(self, _value):
        '''set_target_state'''
        self.target_door_update = True

    def get_door_state(self):
        '''get_door_state'''
        return self.current_door_state

    def get_obstruction(self):
        '''get_obstruction'''
        # There is no good way to detect obstructions, so we assume it is
        # alway false
        return False

    def _probe_door_state(self):
        state = self.sensor.read()

        # this should not be possible, moving should only be a positive integer
        # reset the value to not moving and log a error.
        if self.moving < 0:
            logger.error("invalid moving value: %d", self.moving)
            self.moving = 0

        # our update time fires every 1 second, which allows us to countdown
        # the time until the door stops moving
        if self.moving > 0:
            logger.debug("still moving: %d", self.moving)
            self.moving -= 1
        else:
            # only set our door state after the moving time is expired
            self.current_door_state = state

        return self.current_door_state

    def _toggle_door_state(self):
        # we are in our target door state, nothing to do
        if self.char_target_door_state.value == self.current_door_state:
            self.target_door_update = False
            return

        if self.current_door_state not in (GARAGE_DOOR_CLOSING, GARAGE_DOOR_OPENING):
            self.button.push()
            self.moving = GARAGE_MOVING_DELAY
            self.target_door_update = False
            if self.current_door_state == GARAGE_DOOR_CLOSED:
                self.current_door_state = GARAGE_DOOR_OPENING
            else:
                self.current_door_state = GARAGE_DOOR_CLOSING
        else:
            # we think the door is moving, don't do anything and wait for
            # the moving time to expire.  After the door has stopped moving
            # then we can check the target_door_state with current_door_state
            # and take appropriate action.
            pass

    @Accessory.run_at_interval(1)
    def run(self):
        '''run'''
        state = self._probe_door_state()

        if self.char_current_door_state.value != state:
            self.char_current_door_state.value = state
            self.char_current_door_state.notify()

        if self.target_door_update:
            self._toggle_door_state()
