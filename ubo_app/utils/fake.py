# ruff: noqa: D100, D101, D102, D103, D104, D105, D107
from __future__ import annotations

from types import ModuleType
from typing import TYPE_CHECKING, Any, Self, cast

from ubo_app.logging import logger

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator


class Fake(ModuleType):
    def __init__(
        self: Fake,
        *args: object,
        __return_value: object | None = None,
        __await_value: object | None = None,
        __props: dict[str, object] | None = None,
        **kwargs: object,
    ) -> None:
        logger.verbose(
            'Initializing `Fake`',
            extra={
                'args_': args,
                'kwargs': kwargs,
                '__return_value': __return_value,
                '__await_value': __await_value,
                '__props': __props,
            },
        )
        if __props is not None:
            for key, value in __props.items():
                super().__setattr__(key, value)
        self.__return_value = __return_value
        self.__await_value = __await_value
        self.iterated = False
        super().__init__('')

    def __init_subclass__(cls: type[Fake], **kwargs: dict[str, Any]) -> None:
        logger.verbose('Subclassing `Fake`', extra={'cls': cls, 'kwargs': kwargs})

    def __getattr__(self: Fake, attr: str) -> Fake:
        logger.verbose(
            'Accessing fake attribute of a `Fake` insta',
            extra={'attr': attr},
        )
        if attr == '__file__':
            return cast(Fake, 'fake')
        return self

    def __setattr__(self: Fake, attr: str, value: object) -> None:
        logger.verbose(
            'Accessing fake attribute of a `Fake` insta',
            extra={'attr': attr},
        )
        super().__setattr__(attr, value)

    def __getitem__(self: Fake, key: object) -> Fake:
        logger.verbose(
            'Accessing fake item of a `Fake` instance',
            extra={'key': key},
        )
        return self

    def __call__(self: Fake, *args: object, **kwargs: dict[str, Any]) -> object:
        logger.verbose(
            'Calling a `Fake` instance',
            extra={
                'args_': args,
                'kwargs': kwargs,
                '__return_value': self.__return_value,
            },
        )
        return self.__return_value if self.__return_value is not None else self

    def __await__(self: Fake) -> Generator[Any, Any, object]:
        yield
        return self.__await_value or Fake()

    def __next__(self: Fake) -> Fake:
        if self.iterated:
            raise StopIteration
        self.iterated = True
        return self

    def __anext__(self: Fake) -> Fake:
        if self.iterated:
            raise StopAsyncIteration
        self.iterated = True
        return self

    def __iter__(self: Fake) -> Iterator[Fake]:
        return Fake()

    def __aiter__(self: Fake) -> Iterator[Fake]:
        return Fake()

    def __enter__(self: Fake) -> Fake:  # noqa: PYI034
        return self

    def __exit__(self: Fake, *_: object) -> None:
        pass

    async def __aenter__(self: Self) -> Self:
        return self

    async def __aexit__(self: Fake, *_: object) -> None:
        pass

    def __mro_entries__(self: Fake, bases: tuple[type[Fake]]) -> tuple[type[Fake]]:
        logger.verbose(
            'Getting MRO entries of a `Fake` instance',
            extra={'bases': bases},
        )
        return (cast(type, self),)

    def __len__(self: Fake) -> int:
        return 1

    def __index__(self: Fake) -> int:
        return 1

    def __contains__(self: Fake, _: object) -> bool:
        return True

    def __eq__(self: Fake, _: object) -> bool:
        return True

    def __ne__(self: Fake, _: object) -> bool:
        return False

    def __str__(self: Fake) -> str:
        return 'Fake'

    def __repr__(self: Fake) -> str:
        return 'Fake'
