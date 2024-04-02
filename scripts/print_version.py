"""Prints the version of the ubo_app package."""

import importlib.metadata

print(importlib.metadata.version('ubo_app'), sep='', end='')  # noqa: T201
