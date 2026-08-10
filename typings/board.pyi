"""Stub for Blinka's `board` module.

`board` has no statically visible contents. It builds its pin set at *import*
time, looking the running board up in `board_imports.json` and injecting the
matching pin module into its own globals:

    for board_key, board_module in board_imports.items():
        ...
        import_mod(globals(), board_module)

Nothing about that is analysable, so every `board.CE0` reads as an unknown
attribute off-device. Blinka 9.1.0 and earlier resolved by accident — the same
lookup was written as a chain of `from ... import *` statements, which a type
checker can follow; 9.2.0 replaced it with the JSON-driven loop above.

The pins listed here are the ones the real module exposes on the device
(Raspberry Pi 5 / bcm2712, 44 pins), read off `dir(board)` there rather than
guessed. They are typed as `microcontroller.Pin` — the type every CircuitPython
driver declares its pin parameters as — so `board.CE0.id` and the `digitalio`,
`neopixel` and `Pi5Pixelbuf` call sites stay checked instead of decaying to
`Any`.

Regenerate by reading `dir(board)` on a device rather than editing by hand; the
set is per-board, and this file describes the Pi 5.
"""

from busio import I2C as _I2C
from busio import SPI as _SPI
from microcontroller import Pin

# Chip selects
CE0: Pin
CE1: Pin

# GPIO by BCM number
D0: Pin
D1: Pin
D2: Pin
D3: Pin
D4: Pin
D5: Pin
D6: Pin
D7: Pin
D8: Pin
D9: Pin
D10: Pin
D11: Pin
D12: Pin
D13: Pin
D14: Pin
D15: Pin
D16: Pin
D17: Pin
D18: Pin
D19: Pin
D20: Pin
D21: Pin
D22: Pin
D23: Pin
D24: Pin
D25: Pin
D26: Pin
D27: Pin

# SPI
MISO: Pin
MISO_1: Pin
MOSI: Pin
MOSI_1: Pin
SCK: Pin
SCK_1: Pin
SCLK: Pin
SCLK_1: Pin

# I2C
SCL: Pin
SDA: Pin

# UART
RX: Pin
RXD: Pin
TX: Pin
TXD: Pin

# Defined only when the corresponding pins exist, which they do on the Pi.
def I2C() -> _I2C: ...
def SPI() -> _SPI: ...
