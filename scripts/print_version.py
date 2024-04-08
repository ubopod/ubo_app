"""Prints the version of the ubo_app package."""

import importlib.metadata
from sys import stdout

stdout.write(importlib.metadata.version('ubo_app'))
