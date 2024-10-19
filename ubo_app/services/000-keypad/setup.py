# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import logging
import math
import time
from typing import TYPE_CHECKING, Literal, cast

import board

from ubo_app.store.services.audio import AudioDevice, AudioSetMuteStatusAction
from ubo_app.store.services.keypad import (
    Key,
    KeypadKeyPressAction,
    KeypadKeyReleaseAction,
)
from ubo_app.utils import IS_RPI

if TYPE_CHECKING:
    from adafruit_aw9523 import AW9523
    from adafruit_bus_device import i2c_device
    from adafruit_register.i2c_struct import UnaryStruct

INT_EXPANDER = 5  # GPIO PIN index that receives interrupt from AW9523

ButtonStatus = Literal['pressed', 'released']


class KeypadError(Exception): ...


KEY_INDEX = {
    0: Key.L1,
    1: Key.L2,
    2: Key.L3,
    3: Key.UP,
    4: Key.DOWN,
    5: Key.BACK,
    6: Key.HOME,
}
MIC_INDEX = 7


class Keypad:
    """Class to handle keypad events."""

    previous_inputs: int
    aw: AW9523 | None
    inputs: UnaryStruct

    def __init__(self: Keypad) -> None:
        """Initialize a Keypad.

        Initializes various parameters including
        loggers and button names.
        """
        self.logger = logging.getLogger('keypad')
        self.logger.setLevel(logging.WARNING)
        self.logger.info('Initialising keypad...')
        self.previous_inputs = 0
        self.aw = None
        self.bus_address = 0x58
        self.model = 'aw9523'
        self.enabled = True
        self.init_i2c()

    @staticmethod
    def clear_interrupt_flags(i2c: i2c_device.I2CDevice) -> None:
        # Write to both registers to reset the interrupt flag
        buffer = bytearray(2)
        buffer[0] = 0x00
        buffer[1] = 0x00
        i2c.write(buffer)
        i2c.write_then_readinto(buffer, buffer, out_end=1, in_start=1)

        time.sleep(0.1)
        buffer[0] = 0x01
        buffer[1] = 0x00
        i2c.write(buffer)
        i2c.write_then_readinto(buffer, buffer, out_end=1, in_start=1)
        time.sleep(0.1)

    @staticmethod
    def disable_interrupt_for_higher_bits(i2c: i2c_device.I2CDevice) -> None:
        # disable interrupt for higher bits
        buffer = bytearray(2)
        buffer[0] = 0x06
        buffer[1] = 0x00
        i2c.write(buffer)
        i2c.write_then_readinto(buffer, buffer, out_end=1, in_start=1)

        buffer[0] = 0x07
        buffer[1] = 0xFF
        i2c.write(buffer)
        i2c.write_then_readinto(buffer, buffer, out_end=1, in_start=1)

    def init_i2c(self: Keypad) -> None:
        if not IS_RPI:
            return
        # Use GPIO to receive interrupt from the GPIO expander
        from gpiozero import Button

        i2c = board.I2C()
        # Set this to the GPIO of the interrupt:
        btn = Button(INT_EXPANDER)
        try:
            import adafruit_aw9523

            # Search for the GPIO expander address on the I2C bus
            self.aw = adafruit_aw9523.AW9523(i2c, self.bus_address)
            new_i2c = self.aw.i2c_device
        except Exception:
            self.bus_address = False
            self.logger.exception('Failed to initialize I2C Bus on address 0x58')
            raise

        # Perform soft reset of the expander
        self.aw.reset()
        # Set first 8 low significant bits (register 1) to input
        self.aw.directions = 0xFF00
        time.sleep(1)

        # The code below, accessing the GPIO expander registers directly via i2c
        # was created as a workaround of the reset the interrupt flag.
        self.clear_interrupt_flags(new_i2c)
        self.disable_interrupt_for_higher_bits(new_i2c)
        # reset interrupts again
        self.clear_interrupt_flags(new_i2c)

        # read register values
        inputs = cast(int, self.aw.inputs)
        self.logger.debug(
            'Initializing inputs',
            extra={'inputs': f'{inputs:016b}'},
        )
        self.previous_inputs = inputs
        time.sleep(0.5)

        # Interrupt callback when any button is pressed
        btn.when_pressed = self.key_press_cb

        is_mic_active = inputs & 1 << MIC_INDEX != 0
        self.on_button_event(
            index=MIC_INDEX,
            status='released' if is_mic_active else 'pressed',
            pressed_buttons=[],
        )

        # This should always be the last line of this method
        self.clear_interrupt_flags(new_i2c)

    def key_press_cb(self: Keypad, _: object) -> None:
        """Handle key press dispatched by GPIO interrupt.

            This is callback function that gets triggers
         if any change is detected on keypad buttons
         states.

         In this callback, we look at the state
         change to see which button was pressed or leased.

        Parameters
        ----------
        _channel: int
            GPIO channel that triggered the callback
            NOT USED currently

        """
        if self.aw is None:
            return
        # read register values
        inputs = cast(int, self.aw.inputs)
        # append the event to the queue. The queue has a depth of 2 and
        # keeps the current and last event.
        self.logger.debug('Current Inputs', extra={'inputs': f'{inputs:016b}'})
        self.logger.debug(
            'Previous Inputs',
            extra={'inputs': f'{self.previous_inputs:016b}'},
        )
        # XOR the last recorded input values with the current input values
        # to see which bits have changed. Technically there can only be one
        # bit change in every callback
        change_mask = self.previous_inputs ^ inputs
        self.logger.debug('Change', extra={'change_mask': f'{change_mask:016b}'})
        if change_mask == 0:
            return
        # use the change mask to see if the button was the change was
        # falling (1->0) indicating a pressed action
        # or risign (0->1) indicating a release action
        index = (int)(math.log2(change_mask))
        self.logger.info('button index', extra={'button_index': index})

        # Check for multiple button presses
        pressed_buttons = [
            i for i in range(8) if i in KEY_INDEX and inputs & 1 << i == 0
        ]

        # Check for rising edge or falling edge action (press or release)
        if (self.previous_inputs & change_mask) == 0:
            self.logger.info(
                'Button pressed',
                extra={
                    'button': str(index),
                    'pressed_buttons': pressed_buttons,
                },
            )
            self.on_button_event(
                index=index,
                status='released',
                pressed_buttons=pressed_buttons,
            )
        else:
            self.logger.info(
                'Button released',
                extra={
                    'button': str(index),
                    'pressed_buttons': pressed_buttons,
                },
            )
            self.on_button_event(
                index=index,
                status='pressed',
                pressed_buttons=pressed_buttons,
            )

        self.previous_inputs = inputs

    @staticmethod
    def on_button_event(
        *,
        index: int,
        status: ButtonStatus,
        pressed_buttons: list[int],
    ) -> None:
        from ubo_app.store.main import store

        if index in KEY_INDEX:
            if status == 'pressed':
                store.dispatch(
                    KeypadKeyPressAction(
                        key=KEY_INDEX[index],
                        pressed_keys={KEY_INDEX[i] for i in pressed_buttons},
                    ),
                )
            elif status == 'released':
                store.dispatch(
                    KeypadKeyReleaseAction(
                        key=KEY_INDEX[index],
                        pressed_keys={KEY_INDEX[i] for i in pressed_buttons},
                    ),
                )
        if index == MIC_INDEX:
            store.dispatch(
                AudioSetMuteStatusAction(
                    device=AudioDevice.INPUT,
                    is_mute=status == 'pressed',
                ),
            )


def init_service() -> None:
    if not IS_RPI:
        return
    Keypad()
