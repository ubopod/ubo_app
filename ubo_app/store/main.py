# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import field
from typing import TYPE_CHECKING, Sequence

from redux import BaseAction, BaseEvent, FinishAction, Immutable, InitAction

from ubo_app.store.services.keypad import KeypadAction
from ubo_app.store.status_icons import IconAction
from ubo_app.store.update_manager_types import VersionStatus

if TYPE_CHECKING:
    from typing_extensions import TypeAlias
    from ubo_gui.menu.types import Item, Menu


class RegisterAppAction(BaseAction):
    menu_item: Item


class RegisterRegularAppAction(RegisterAppAction):
    ...


class RegisterSettingAppAction(RegisterAppAction):
    ...


class PowerOffAction(BaseAction):
    ...


class PowerOffEvent(BaseEvent):
    ...


class MainState(Immutable):
    menu: Menu | None = None
    path: Sequence[int] = field(default_factory=list)
    version: VersionStatus = field(default_factory=VersionStatus)


class InitEvent(BaseEvent):
    ...


class SetMenuPathAction(BaseAction):
    path: Sequence[str]


MainAction: TypeAlias = (
    InitAction
    | FinishAction
    | PowerOffAction
    | IconAction
    | KeypadAction
    | RegisterAppAction
    | SetMenuPathAction
)
