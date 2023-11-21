# ruff: noqa: D100, D101, D102, D103, D104, D107
import logging
import sys

logger = logging.getLogger('ubo-app')
logger.setLevel(logging.INFO)
logger.propagate = False


def add_stdout_handler() -> None:
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.setFormatter(
        logging.Formatter(
            '%(created)f [%(levelname)s] %(message)s',
            '%Y-%m-%d %H:%M:%S',
        ),
    )
    logger.addHandler(stdout_handler)


def add_file_handler() -> None:
    file_handler = logging.FileHandler('ubo-app.log')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            '%(created)f [%(levelname)s] %(message)s',
            '%Y-%m-%d %H:%M:%S',
        ),
    )
    logger.addHandler(file_handler)


__all__ = ('logger', 'add_stdout_handler', 'add_file_handler')
