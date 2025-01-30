"""Utility functions for copying template files to the system and restoring them."""

from __future__ import annotations

import pathlib


def copy_templates(
    templates_path: pathlib.Path,
    *,
    variables: dict[str, str],
) -> None:
    """Copy template files to the system and replace variables."""
    for template_path in templates_path.rglob('*'):
        if template_path.is_file() and template_path.name.endswith('.tmpl'):
            relative_path = template_path.relative_to(templates_path)
            system_path = pathlib.Path('/') / relative_path.with_suffix('')
            backup_path = system_path.with_name(system_path.name + '.bak')
            if system_path.exists() and not backup_path.exists():
                system_path.rename(backup_path)
            with template_path.open('r') as template_file:
                template = template_file.read()
                for key, value in variables.items():
                    template = template.replace(f'{{{{{key}}}}}', value)
                with system_path.open('w') as system_file:
                    system_file.write(template)


def restore_backups(templates_path: pathlib.Path) -> None:
    """Restore backup files created by copy_templates."""
    for template_path in templates_path.rglob('*'):
        if template_path.is_file() and template_path.name.endswith('.tmpl'):
            relative_path = template_path.relative_to(templates_path)
            system_path = pathlib.Path('/') / relative_path.with_suffix('')
            backup_path = system_path.with_name(system_path.name + '.bak')
            if backup_path.exists():
                backup_path.rename(system_path)
