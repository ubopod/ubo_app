"""Compatibility layer for different environments."""


def setup() -> None:
    """Set up for different environments."""
    from ubo_app.utils import IS_RPI

    if not IS_RPI:
        import asyncio
        import subprocess
        import sys

        from ubo_app.utils.fake import Fake

        sys.modules['alsaaudio'] = Fake()
        sys.modules['pulsectl'] = Fake()
        sys.modules['sdbus'] = Fake()
        sys.modules['sdbus_async'] = Fake()
        sys.modules['sdbus_async.networkmanager'] = Fake()
        sys.modules['sdbus_async.networkmanager.enums'] = Fake()
        original_run = subprocess.run
        subprocess.run = (
            lambda command, *args, **kwargs: Fake()
            if any(i in command[0] for i in ('reboot', 'poweroff'))
            else original_run(command, *args, **kwargs)
        )
        asyncio.create_subprocess_exec = Fake(
            _Fake__return_value=Fake(
                _Fake__await_value=Fake(
                    _Fake__props={
                        'communicate': Fake(
                            _Fake__return_value=Fake(_Fake__await_value=['', '']),
                        ),
                    },
                ),
            ),
        )
