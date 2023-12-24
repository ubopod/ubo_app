# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from asyncio import Task
from typing import Awaitable


def create_task(task: Awaitable) -> Task:
    msg = 'Current thread is not an ubo service thread'
    raise NotImplementedError(msg)
