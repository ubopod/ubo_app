"""Update handler in system manager."""

import subprocess
from collections.abc import Generator, Iterator

from ubo_app.constants import UPDATE_ASSETS_PATH
from ubo_app.logger import get_logger

logger = get_logger('system-manager')


def update_handler(target_version: str) -> Iterator[bytes]:
    """Handle update requests."""
    logger.info('Update request received', extra={'target_version': target_version})

    def run_install_script() -> Generator[bytes]:
        process = subprocess.Popen(  # noqa: S603
            [
                (UPDATE_ASSETS_PATH / 'install.sh'),
                *(
                    [
                        f'--target-version={target_version}',
                    ]
                    if target_version is not None
                    else []
                ),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if process.stdout is None:
            msg = 'Failed to run install script'
            raise RuntimeError(msg)

        for line in process.stdout:
            logger.debug('Install script output', extra={'line': line})
            if not line:
                stderr = ''
                if process.stderr:
                    stderr = process.stderr.read().decode()

                logger.error(
                    'Failed to update (install script failed)',
                    extra={'stderr': stderr},
                )

                msg = 'Install script failed, no output received.'
                raise RuntimeError(msg)

            yield line

        if process.returncode is None or process.returncode != 0:
            stderr = ''
            if process.stderr:
                stderr = process.stderr.read().decode()

            logger.error(
                'Failed to update (install script failed)',
                extra={'stderr': stderr},
            )

            msg = 'Install script failed, process return code is not 0.'
            raise RuntimeError(msg)

    return run_install_script()
