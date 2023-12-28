# ruff: noqa: D100, D101, D102, D103, D104, D105, D107
from __future__ import annotations

from types import ModuleType
from typing import Any, Generator, Iterator

from ubo_app.logging import logger


class Fake(ModuleType):
    def __init__(self: Fake) -> None:
        super().__init__('')

    def __getattr__(self: Fake, attr: str) -> Fake | str:
        logger.verbose(
            'Accessing fake attribute of a `Fake` instance',
            extra={'attr': attr},
        )
        if attr == '__file__':
            return ''
        return Fake()

    def __call__(self: Fake, *args: object, **kwargs: dict[str, Any]) -> Fake:
        logger.verbose(
            'Calling a `Fake` instance',
            extra={'args_': args, 'kwargs': kwargs},
        )
        return Fake()

    def __await__(self: Fake) -> Generator[Fake | None, Any, Any]:
        yield None
        return Fake()

    def __iter__(self: Fake) -> Iterator[Fake]:
        return iter([Fake()])
