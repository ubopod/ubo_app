"""Compatibility layer for different environments."""


def setup() -> None:
    """Set up for different environments."""
    from ubo_app.utils import IS_RPI

    if not IS_RPI:
        import sys

        from ubo_app.utils.fake import Fake

        sys.modules['alsaaudio'] = Fake()
        sys.modules['pulsectl'] = Fake()
        sys.modules['sdbus'] = Fake()
        sys.modules['sdbus_async'] = Fake()
        sys.modules['sdbus_async.networkmanager'] = Fake()
        sys.modules['sdbus_async.networkmanager.enums'] = Fake()
