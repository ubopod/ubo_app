# ruff: noqa: N802, T201
"""Generate proto files from actions, events and states defined in Python files."""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import betterproto.casing

from ubo_app.rpc.generator._module_transformer import _ProtoGenerator

if TYPE_CHECKING:
    from types import ModuleType


def _generate_operations_proto(
    output_directory: Path,
    actions: list,
    events: list,
) -> None:
    proto = '\n'
    if actions:
        proto += 'message Action {\n'
        proto += '  oneof action {\n'
        for i, (action, _) in enumerate(sorted(generator.actions), 1):
            # proto += f"""    {package_name}.v1.{action} {
            proto += (
                f"""    {action} {betterproto.casing.snake_case(action)} = {i};\n"""
            )
        proto += '  }\n'
        proto += '}\n\n'
    if events:
        proto += 'message Event {\n'
        proto += '  oneof event {\n'
        for i, (event, _) in enumerate(sorted(generator.events), 1):
            # proto += f"""    {package_name}.v1.{event} {
            proto += f"""    {event} {betterproto.casing.snake_case(event)} = {i};\n"""
        proto += '  }\n'
        proto += '}\n\n'
    operations_proto_path = output_directory / 'ubo' / 'v1' / 'ubo.proto'
    with operations_proto_path.open('a') as file:
        file.write(proto)


def parse(input_module: ModuleType, actions: list, events: list) -> _ProtoGenerator:
    """Generate proto files from actions, events and states defined in Python files."""
    if not input_module.__file__:
        msg = 'Module must be a file'
        raise ValueError(msg)
    with Path(input_module.__file__).open() as file:
        tree = ast.parse(file.read())

    generator = _ProtoGenerator(module=input_module, actions=actions, events=events)
    generator.visit(tree)

    return generator


if __name__ == '__main__':
    print('🚀 Generating proto files...')
    output_directory = Path('ubo_app/rpc/proto/')

    import ubo_gui.menu.types

    import ubo_app.store.core.types
    import ubo_app.store.input.types
    import ubo_app.store.settings.types
    import ubo_app.store.status_icons.types
    import ubo_app.store.ubo_actions
    import ubo_app.store.update_manager.types

    generators: list[_ProtoGenerator] = []

    actions = []
    events = []

    generators.append(parse(ubo_gui.menu.types, actions, events))
    generators.append(parse(ubo_app.store.core.types, actions, events))
    generators.append(
        parse(ubo_app.store.ubo_actions, actions, events),
    )
    generators.append(parse(ubo_app.store.input.types, actions, events))
    generators.append(parse(ubo_app.store.settings.types, actions, events))
    generators.append(parse(ubo_app.store.status_icons.types, actions, events))
    generators.append(parse(ubo_app.store.update_manager.types, actions, events))
    generators.extend(
        parse(
            importlib.import_module(f'ubo_app.store.services.{file.stem}'),
            actions,
            events,
        )
        for file in sorted(Path('ubo_app/store/services/').glob('*.py'))
    )

    (output_directory / 'ubo' / 'v1').mkdir(
        exist_ok=True,
        parents=True,
    )
    with (output_directory / 'ubo' / 'v1' / 'ubo.proto').open('w') as file:
        file.write('syntax = "proto3";\n\n')
        file.write('package ubo.v1;\n\n')
        file.write('import "package_info/v1/package_info.proto";\n\n')
        for generator in generators:
            sys.stdout.write(f'⚡ Generating proto for {generator.package_name} .')

            file.write(generator.generate_proto())

            print(' Done')

    """ This version is for the case where we have a separate proto file for each
    package, it is currently not possible because proto files do not support import
    loops, and Action needs NotificationsAddAction which needs NotificationActionItem
    which needs Action

    for generator in generators:
        proto_definitions, dependencies = generator.generate_proto()

        (output_directory / generator.package_name / 'v1').mkdir(
            exist_ok=True,
            parents=True,
        )
        with (
            output_directory
            / generator.package_name
            / 'v1'
            / f'{generator.package_name}.proto'
        ).open('w') as file:
            file.write('syntax = "proto3";\n\n')
            file.write(f'package {generator.package_name}.v1;\n\n')
            if dependencies:
                for dependency in dependencies:
                    file.write(f'import "{dependency}/v1/{dependency}.proto";\n')
                file.write('\n')
            file.write(proto_definitions)
    """

    _generate_operations_proto(output_directory, actions, events)

    print('🎉 Proto files generated successfully!')
