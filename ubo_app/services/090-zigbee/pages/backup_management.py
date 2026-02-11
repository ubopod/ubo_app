"""Backup management page for the Zigbee service.

Shows network backups and allows restore/delete operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from constants import ICON_BACKUP, ICON_DELETE, ICON_LOADING, ICON_REFRESH, ICON_ZIGBEE
from ubo_gui.menu.types import ActionItem, HeadedMenu, HeadlessMenu

from ubo_app.colors import DANGER_COLOR, WARNING_COLOR
from ubo_app.store.core.types import CloseApplicationAction
from ubo_app.store.main import store
from ubo_app.store.services.zigbee import (
    ZigbeeBackup,
    ZigbeeCreateBackupAction,
    ZigbeeDeleteBackupAction,
    ZigbeeRefreshDevicesAction,
    ZigbeeRestoreBackupAction,
)
from ubo_app.store.ubo_actions import UboApplicationItem, register_application
from ubo_app.utils.gui import UboPromptWidget

if TYPE_CHECKING:
    from collections.abc import Sequence


class _RestoreBackupConfirmPage(UboPromptWidget):
    """Confirmation page for backup restore."""

    def __init__(
        self,
        backup_index: int,
        backup_time: str,
        device_count: int,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.backup_index = backup_index
        self.title = 'Restore Backup?'
        self.prompt = f'Restore backup from {backup_time}?\n({device_count} devices)'
        self.icon = ICON_BACKUP
        self.first_option_label = 'Restore'
        self.first_option_icon = ICON_BACKUP
        self.first_option_is_short = False
        self.first_option_background_color = WARNING_COLOR
        self.second_option_label = 'Cancel'
        self.second_option_icon = '󰜺'
        self.second_option_is_short = False

    def first_option_callback(self) -> None:
        """Confirm restore."""
        store.dispatch(
            ZigbeeRestoreBackupAction(backup_index=self.backup_index),
            CloseApplicationAction(application_instance_id=self.id),
        )

    def second_option_callback(self) -> None:
        """Cancel restore."""
        store.dispatch(CloseApplicationAction(application_instance_id=self.id))


register_application(
    application=_RestoreBackupConfirmPage,
    application_id='zigbee:restore-backup-confirm',
)


class _DeleteBackupConfirmPage(UboPromptWidget):
    """Confirmation page for backup deletion."""

    def __init__(
        self,
        backup_index: int,
        backup_time: str,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.backup_index = backup_index
        self.title = 'Delete Backup?'
        self.prompt = f'Permanently delete backup from {backup_time}?'
        self.icon = ICON_DELETE
        self.first_option_label = 'Delete'
        self.first_option_icon = ICON_DELETE
        self.first_option_is_short = False
        self.first_option_background_color = DANGER_COLOR
        self.second_option_label = 'Cancel'
        self.second_option_icon = '󰜺'
        self.second_option_is_short = False

    def first_option_callback(self) -> None:
        """Confirm deletion."""
        store.dispatch(
            ZigbeeDeleteBackupAction(backup_index=self.backup_index),
            CloseApplicationAction(application_instance_id=self.id),
        )

    def second_option_callback(self) -> None:
        """Cancel deletion."""
        store.dispatch(CloseApplicationAction(application_instance_id=self.id))


register_application(
    application=_DeleteBackupConfirmPage,
    application_id='zigbee:delete-backup-confirm',
)


class _BackupOptionsPage(UboPromptWidget):
    """Page for selecting backup action (restore or delete)."""

    def __init__(
        self,
        backup_index: int,
        backup_time: str,
        device_count: int,
        *,
        is_complete: bool,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.backup_index = backup_index
        self.backup_time = backup_time
        self.device_count = device_count
        self.is_complete = is_complete

        status = '(complete)' if is_complete else '(partial)'
        self.title = f'Backup {backup_time}'
        self.prompt = f'{device_count} devices {status}'
        self.icon = ICON_BACKUP
        self.first_option_label = 'Restore'
        self.first_option_icon = ICON_BACKUP
        self.first_option_is_short = False
        self.second_option_label = 'Delete'
        self.second_option_icon = ICON_DELETE
        self.second_option_is_short = False
        self.second_option_background_color = DANGER_COLOR

    def first_option_callback(self) -> None:
        """Go to restore confirmation."""
        from ubo_app.store.core.types import OpenApplicationAction

        store.dispatch(
            CloseApplicationAction(application_instance_id=self.id),
            OpenApplicationAction(
                application_id='zigbee:restore-backup-confirm',
                initialization_kwargs={
                    'backup_index': self.backup_index,
                    'backup_time': self.backup_time,
                    'device_count': self.device_count,
                },
            ),
        )

    def second_option_callback(self) -> None:
        """Go to delete confirmation."""
        from ubo_app.store.core.types import OpenApplicationAction

        store.dispatch(
            CloseApplicationAction(application_instance_id=self.id),
            OpenApplicationAction(
                application_id='zigbee:delete-backup-confirm',
                initialization_kwargs={
                    'backup_index': self.backup_index,
                    'backup_time': self.backup_time,
                },
            ),
        )


register_application(
    application=_BackupOptionsPage,
    application_id='zigbee:backup-options',
)


@store.autorun(lambda state: state.zigbee.backups)
def backup_menu(backups: Sequence[ZigbeeBackup] | None) -> HeadedMenu | HeadlessMenu:
    """Generate the backup management menu."""
    if backups is None:
        return HeadedMenu(
            title=f'{ICON_ZIGBEE} Backups',
            heading='Loading...',
            sub_heading='Fetching backup list',
            items=[],
            placeholder=ICON_LOADING,
        )

    items: list[ActionItem | UboApplicationItem] = []

    if backups:
        for backup in backups:
            status = '✓' if backup.is_complete else '~'
            label = f'{backup.backup_time} ({backup.device_count}) {status}'
            items.append(
                UboApplicationItem(
                    key=f'backup-{backup.index}',
                    label=label,
                    icon=ICON_BACKUP,
                    application_id='zigbee:backup-options',
                    initialization_kwargs={
                        'backup_index': backup.index,
                        'backup_time': backup.backup_time,
                        'device_count': backup.device_count,
                        'is_complete': backup.is_complete,
                    },
                ),
            )

    # Add create backup option
    items.append(
        ActionItem(
            key='create',
            label='Create new backup',
            icon=ICON_BACKUP,
            action=lambda: store.dispatch(ZigbeeCreateBackupAction()),
        ),
    )

    # Add refresh option
    items.append(
        ActionItem(
            key='refresh',
            label='Refresh list',
            icon=ICON_REFRESH,
            action=lambda: store.dispatch(ZigbeeRefreshDevicesAction()),
        ),
    )

    return HeadlessMenu(
        title='Backups',
        items=items,
        placeholder='No backups found',
    )
