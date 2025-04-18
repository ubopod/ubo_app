"""Network utilities for the Raspberry Pi."""

import asyncio
import subprocess

from ubo_app.logger import logger
from ubo_app.utils import IS_RPI


async def has_gateway() -> bool:
    """Check if any network is connected."""
    try:
        # macOS uses 'route -n get default', Linux uses 'ip route'
        process = await asyncio.create_subprocess_exec(
            'which',
            'ip',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.wait()
        if process.returncode == 0:
            # For Linux
            process = await asyncio.create_subprocess_exec(
                'ip',
                'route',
                'show',
                'default',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.wait()
            if process.returncode == 0 and process.stdout:
                for line in (await process.stdout.read()).splitlines():
                    if (
                        line.startswith(b'default')
                        and b'scope link' not in line
                        and b'127.' not in line
                        and b'169.254.' not in line
                        and b'::1' not in line
                        and b'fe80::' not in line
                    ):
                        return True
        else:
            # For macOS
            process = await asyncio.create_subprocess_exec(
                'route',
                '-n',
                'get',
                'default',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.wait()
            if process.returncode == 0 and process.stdout:
                for line in (await process.stdout.read()).splitlines():
                    if b'gateway:' in line:
                        return True
    finally:
        pass
    return False


async def get_saved_wifi_ssids() -> list[str]:
    """Get a list of saved Wi-Fi SSIDs using nmcli.

    Returns:
        list: List of saved Wi-Fi SSIDs or an empty list if none are found.

    """
    if not IS_RPI:
        return []
    try:
        process = await asyncio.create_subprocess_exec(
            'nmcli',
            '-t',
            '-f',
            'NAME,TYPE',
            'connection',
            'show',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.wait()
        if process.returncode == 0 and process.stdout:
            return [
                line.split(b':')[0].decode()
                for line in (await process.stdout.read()).split(b'\n')
                if b'wifi' in line
            ]
    except subprocess.CalledProcessError as e:
        logger.exception('Error executing nmcli', extra={'output': e.stderr})
    except Exception as e:
        logger.exception('Unexpected error', extra={'error': e})

    return []
