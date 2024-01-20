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
            'Accessing fake attribute of a `Fake` insta',
            extra={'attr': attr},
        )
        if attr == '__file__':
            return ''
        return self

    def __getitem__(self: Fake, key: str) -> Fake:
        logger.verbose(
            'Accessing fake item of a `Fake` instance',
            extra={'key': key},
        )
        return self

    def __call__(self: Fake, *args: object, **kwargs: dict[str, Any]) -> Fake:
        logger.verbose(
            'Calling a `Fake` instance',
            extra={'args_': args, 'kwargs': kwargs},
        )
        return self

    def __await__(self: Fake) -> Generator[Fake | None, Any, Any]:
        yield None
        return self

    def __iter__(self: Fake) -> Iterator[Fake]:
        return iter([self])

    def __enter__(self: Fake) -> Fake:  # noqa: PYI034
        return self

    def __exit__(self: Fake, *_: object) -> None:
        pass
