# ruff: noqa: N802, T201
"""Generate proto files from actions, events and states defined in Python files."""

from __future__ import annotations

import ast
import functools
import importlib
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self, get_args

import betterproto.casing
from immutable import Immutable

from ubo_app.rpc.message_to_object import (
    META_FIELD_PREFIX_PACKAGE_NAME,
    META_FIELD_PREFIX_PACKAGE_NAME_INDEX,
)

if TYPE_CHECKING:
    from types import ModuleType

actions = []
events = []
states = {}

global_messages: dict[str, tuple[str, list[tuple[str, _Type]]]] = {}
global_enums: dict[str, str] = {}
global_types: dict[str, str] = {}


FieldType = Literal['string', 'int64', 'float', 'bool', 'bytes']


class _Type(Immutable):
    def get_proto(self: Self, name: str, *, current_package: str | None) -> str:
        _ = name, current_package
        raise NotImplementedError

    def get_embedded_proto(self: Self, name: str) -> str:
        return self.get_proto(name, current_package=self.package)

    @property
    def as_basic_type(self: Self) -> str | None:
        return None

    @property
    def local_name(self: Self) -> str:
        raise NotImplementedError

    def get_definitions(self: Self, name: str, *, current_package: str | None) -> str:
        _ = name, current_package
        raise NotImplementedError

    def get_embedded_definitions(
        self: Self,
        name: str,
        *,
        current_package: str | None,
    ) -> str:
        return self.get_definitions(name, current_package=current_package)

    @property
    def package(self: Self) -> str | None:
        return None


class _BasicType(_Type):
    type: FieldType | str

    def get_proto(
        self: Self,
        name: str | None = None,
        *,
        current_package: str | None,
    ) -> str:
        _ = name, current_package
        if self.type == 'UboAction':
            return 'Action'
        if self.type == 'UboEvent':
            return 'Event'
        if self.type == 'Color':  # Assuming it is kivy color
            return 'string'
        """ This version is for the case where we have a separate proto file for each
        package, it is currently not possible because proto files do not support import
        loops, and Action needs NotificationsAddAction which needs
        NotificationActionItem which needs Action

        if self.package is None or self.package == current_package:
            if self.type in global_messages:
                message = global_messages[self.type]
                return f'{message[0]}.v1.{self.type}'
            if self.type in global_enums:
                return f'{global_enums[self.type]}.v1.{self.type}'
            if self.type in global_types:
                return f'{global_types[self.type]}.v1.{self.type}'
            return self.type
        return f'{self.package}.v1.{self.type}'
        """
        return self.type

    @property
    def as_basic_type(self: Self) -> str:
        return self.type

    @property
    def local_name(self: Self) -> str:
        return self.type

    def get_definitions(self: Self, name: str, *, current_package: str | None) -> str:
        _ = name, current_package
        return ''

    @property
    def package(self: Self) -> str | None:
        if self.type not in get_args(FieldType):
            if self.type in global_messages:
                return global_messages[self.type][0]
            if self.type in global_enums:
                return global_enums[self.type]
            if self.type in global_types:
                return global_types[self.type]
            if self.type in ('Color', 'UboAction', 'UboEvent'):
                return None
            msg = f'Unknown type "{self.type}"'
            raise TypeError(msg)
        return None


class _OptionalType(_Type):
    type: _Type

    def get_proto(self: Self, name: str, *, current_package: str | None) -> str:
        _ = current_package
        return f"""optional {self.type.get_embedded_proto(
            betterproto.casing.pascal_case(name),
        )}"""

    def get_embedded_proto(self: Self, name: str) -> str:
        return betterproto.casing.pascal_case(name)

    @property
    def local_name(self: Self) -> str:
        return 'optional'

    def get_definitions(self: Self, name: str, *, current_package: str | None) -> str:
        return f"""{self.type.get_embedded_definitions(
            f'{betterproto.casing.pascal_case(name)}',
            current_package=current_package,
        )}"""

    def get_embedded_definitions(
        self: Self,
        name: str,
        *,
        current_package: str | None,
    ) -> str:
        return f"""{self.type.get_embedded_definitions(
            f'{betterproto.casing.pascal_case(name)}Optional',
            current_package=current_package,
        )}
message {betterproto.casing.pascal_case(name)} {{
  optional {self.type.get_embedded_proto(
        f'{betterproto.casing.pascal_case(name)}Optional',
    )} items = 1;
}}
"""


class _ListType(_Type):
    type: _Type

    def get_proto(self: Self, name: str, *, current_package: str | None) -> str:
        _ = current_package
        return f"""repeated {self.type.get_embedded_proto(
            betterproto.casing.pascal_case(name),
        )}"""

    def get_embedded_proto(self: Self, name: str) -> str:
        return betterproto.casing.pascal_case(name)

    @property
    def local_name(self: Self) -> str:
        return 'list'

    def get_definitions(self: Self, name: str, *, current_package: str | None) -> str:
        return f"""{self.type.get_embedded_definitions(
            f'{betterproto.casing.pascal_case(name)}',
            current_package=current_package,
        )}"""

    def get_embedded_definitions(
        self: Self,
        name: str,
        *,
        current_package: str | None,
    ) -> str:
        return f"""{self.type.get_embedded_definitions(
            f'{betterproto.casing.pascal_case(name)}Item',
            current_package=current_package,
        )}
message {betterproto.casing.pascal_case(name)} {{
  repeated {self.type.get_embedded_proto(
        f'{betterproto.casing.pascal_case(name)}Item',
    )} items = 1;
}}
"""


class _UnionType(_Type):
    types: tuple[_Type, ...]

    @classmethod
    def from_(cls: type[Self], *, types: list[_Type]) -> _Type:
        types_ = functools.reduce(
            lambda x, y: (*x, *y),
            (item.types if isinstance(item, _UnionType) else (item,) for item in types),
            (),
        )

        if len(types_) == 1:
            return types_[0]

        return cls(types=types_)

    def get_proto(self: Self, name: str, *, current_package: str | None) -> str:
        _ = current_package
        return betterproto.casing.pascal_case(name)

    def get_embedded_proto(self: Self, name: str) -> str:
        return betterproto.casing.pascal_case(name)

    @property
    def local_name(self: Self) -> str:
        return 'union'

    def get_definitions(self: Self, name: str, *, current_package: str | None) -> str:
        return self.get_embedded_definitions(name, current_package=current_package)

    def get_embedded_definitions(
        self: Self,
        name: str,
        *,
        current_package: str | None,
    ) -> str:
        sub_definitions = ''
        definitions = f'message {betterproto.casing.pascal_case(name)} {{\n'
        if len(self.types) > 0:
            definitions += f'  oneof {betterproto.casing.snake_case(name)} {{\n'
            index = 1
            for item in sorted(self.types, key=lambda x: x.local_name):
                try:
                    definitions += f"""  {
                    item.get_embedded_proto(f"{name}_{index}")} {
                    betterproto.casing.snake_case(item.local_name)} = {index};\n"""
                    sub_definitions += item.get_embedded_definitions(
                        f'{name}_{index}',
                        current_package=current_package,
                    )
                except TypeError as exception:
                    if 'Unknown type' in str(exception) or 'Empty Union' in str(
                        exception,
                    ):
                        continue
                else:
                    index += 1
            definitions += '  }\n'
        definitions += '}\n'

        return f'{sub_definitions}\n{definitions}'


class _DictType(_Type):
    key_type: _Type
    value_type: _Type

    def get_proto(self: Self, name: str, *, current_package: str | None) -> str:
        return f"""map<{self.key_type.get_proto(
            f'{name}_key',
            current_package=current_package,
        )}, {self.value_type.get_proto(
            f'{name}_value',
            current_package=current_package,
        )}>"""

    def get_embedded_proto(self: Self, name: str) -> str:
        return f'{betterproto.casing.pascal_case(name)}Dict'

    @property
    def local_name(self: Self) -> str:
        return 'dict'

    def get_definitions(self: Self, name: str, *, current_package: str | None) -> str:
        return f"""{self.key_type.get_definitions(
            f'{name}_key',
            current_package=current_package,
        )}\n\n{
        self.value_type.get_definitions(
            f'{name}_value',
            current_package=current_package,
        )}"""

    def get_embedded_definitions(
        self: Self,
        name: str,
        *,
        current_package: str | None,
    ) -> str:
        return f"""{self.key_type.get_embedded_definitions(
            f'{name}_key',
            current_package=current_package,
        )}

{self.value_type.get_embedded_definitions(
            f'{name}_value',
            current_package=current_package,
        )}
message {betterproto.casing.pascal_case(name)}Dict {{
  {self.get_proto(name, current_package=current_package)} items = 1;
}}"""


class _ProtoGenerator(ast.NodeVisitor):
    def __init__(self: _ProtoGenerator, module: ModuleType) -> None:
        self.messages: dict[str, list[tuple[str, _Type]]] = {}
        self.enums: dict[str, list[tuple[str, Any]]] = {}
        self.types: dict[str, _Type] = {}
        self.module = module
        self.package_name = module.__name__

    def visit_ClassDef(self: _ProtoGenerator, node: ast.ClassDef) -> None:
        if any(
            base.id in ('Enum', 'StrEnum', 'IntEnum', 'Flag', 'IntFlag')
            for base in node.bases
            if isinstance(base, ast.Name)
        ):
            self.process_enum(node)
        else:
            self.process_class(node)
        self.generic_visit(node)

    def visit_AnnAssign(self: _ProtoGenerator, node: ast.AnnAssign) -> None:
        if (
            isinstance(node.target, ast.Name)
            and isinstance(node.annotation, ast.Name)
            and node.annotation.id == 'TypeAlias'
            and node.value
        ):
            field_name = node.target.id
            try:
                field_type = self.get_field_type(value=node.value)
            except TypeError as e:
                if 'Callable types are not supported' in str(e):
                    return
                raise
            self.types[field_name] = field_type
            if field_name in global_types:
                msg = (
                    f'Type "{field_name}" is already defined in '
                    f'"{global_types[field_name]}"'
                )
                raise SyntaxError(msg)
            global_types[field_name] = self.package_name
        self.generic_visit(node)

    def visit_Assign(self: _ProtoGenerator, node: ast.Assign) -> None:
        if (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == 'TypeVar'
            and isinstance(node.targets[0], ast.Name)
        ):
            field_name = node.targets[0].id
            bound = next(
                (
                    constraint
                    for constraint in node.value.keywords
                    if constraint.arg == 'bound'
                ),
                None,
            )
            if bound:
                bound_type = self.get_field_type(value=bound.value)
                if self.types.get(node.targets[0].id):
                    msg = f'''Type "{field_name}" is already defined as "{
                        self.types[node.targets[0].id]}"'''
                    raise SyntaxError(msg)
                if not isinstance(bound_type, _UnionType):
                    bound_type = _UnionType.from_(types=[bound_type])
                self.types[field_name] = bound_type
                if field_name in global_types:
                    msg = (
                        f'Type "{field_name}" is already defined in '
                        f'"{global_types[field_name]}"'
                    )
                    raise SyntaxError(msg)
                global_types[field_name] = self.package_name
        self.generic_visit(node)

    def process_class(self: _ProtoGenerator, node: ast.ClassDef) -> None:  # noqa: C901
        message_name = node.name
        fields: list[tuple[str, _Type]] = []
        for n in node.body:
            if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                field_name = n.target.id
                try:
                    field_type = self.get_field_type(value=n.annotation)
                    if n.value is not None:
                        field_type = _OptionalType(type=field_type)
                except TypeError as e:
                    if 'Callable types are not supported' in str(e):
                        continue
                    raise

                fields.append((field_name, field_type))
        if node.bases:
            for base in node.bases:
                if not isinstance(base, ast.Name):
                    continue
                base_name = base.id
                if base_name in global_messages:
                    fields.extend(
                        [
                            field
                            for field in global_messages[base_name][1]
                            if not any(field[0] == field_[0] for field_ in fields)
                        ],
                    )
        self.messages[message_name] = fields
        global_messages[message_name] = (self.package_name, fields)
        if message_name.endswith('Action'):
            actions.append((message_name, self.package_name))
        if message_name.endswith('Event'):
            events.append((message_name, self.package_name))

    def process_enum(self: _ProtoGenerator, node: ast.ClassDef) -> None:
        enum_name = node.name
        values: list[tuple[str, Any]] = []
        for n in node.body:
            if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
                value_name = n.targets[0].id
                value = n.value.value if isinstance(n.value, ast.Constant) else None
                values.append((value_name, value))
        self.enums[enum_name] = values
        if enum_name in global_types:
            msg = (
                f'Enum "{enum_name}" is already defined in '
                f'"{global_types[enum_name]}"'
            )
            raise SyntaxError(msg)
        global_enums[enum_name] = self.package_name

    def get_field_type(  # noqa: C901, PLR0912
        self: _ProtoGenerator,
        *,
        value: ast.AST,
    ) -> _Type:
        if isinstance(value, ast.Name):
            if value.id == 'str':
                return _BasicType(type='string')
            if value.id == 'int':
                return _BasicType(type='int64')
            if value.id == 'float':
                return _BasicType(type='float')
            if value.id == 'bool':
                return _BasicType(type='bool')
            if value.id == 'bytes':
                return _BasicType(type='bytes')
            if value.id == 'datetime':
                return _BasicType(type='int64')
            return _BasicType(type=value.id)
        if isinstance(value, ast.Subscript):
            if isinstance(value.value, ast.Name):
                if value.value.id == 'dict' and isinstance(value.slice, ast.Tuple):
                    key_type = self.get_field_type(value=value.slice.elts[0])
                    value_type = self.get_field_type(value=value.slice.elts[1])
                    return _DictType(key_type=key_type, value_type=value_type)

                if value.value.id in ('Sequence', 'list', 'set'):
                    return _ListType(type=self.get_field_type(value=value.slice))

                if value.value.id == 'tuple' and isinstance(value.slice, ast.Tuple):
                    return _ListType(
                        type=_UnionType.from_(
                            types=list(
                                {
                                    self.get_field_type(value=elt)
                                    for elt in value.slice.elts
                                },
                            ),
                        ),
                    )

                if value.value.id in self.types or value.value.id in self.messages:
                    msg = 'Generic types are not supported {value.value.id}'
                    raise TypeError(msg)

                if value.value.id == 'type':
                    return _BasicType(type='string')

                if value.value.id == 'Callable':
                    msg = 'Callable types are not supported'
                    raise TypeError(msg)

                msg = (
                    f'Unsupported subscript type: {value.value.id} '
                    f'- file: {self.module} - line: {value.lineno}'
                )
                raise TypeError(msg)

            msg = (
                f'Unsupported subscript type: {value.value} {value.slice} '
                f'- file: {self.module} - line: {value.lineno}'
            )
            raise TypeError(msg)

        if isinstance(value, ast.BinOp) and isinstance(value.op, ast.BitOr):
            types: list[_Type] = []
            try:
                type = self.get_field_type(value=value.left)
                if type not in types:
                    types.append(type)
            except TypeError as e:
                if 'Callable types are not supported' not in str(e):
                    raise
            try:
                type = self.get_field_type(value=value.right)
                if type not in types:
                    types.append(type)
            except TypeError as e:
                if 'Callable types are not supported' not in str(e):
                    raise
            return _UnionType.from_(types=list(types))

        if isinstance(value, ast.Constant) and value.value is None:
            return _UnionType(types=())
        msg = f'Unsupported field type: {value}'
        raise TypeError(msg)

    def generate_proto(self: _ProtoGenerator) -> str:  # noqa: C901
        try:
            proto = ''
            for enum_name, values in self.enums.items():
                proto += f'enum {enum_name} {{\n'
                proto += f"""  {betterproto.casing.snake_case(enum_name).upper()
                }_{self.package_name.replace('.', '_dot_').upper()
                }_UNSPECIFIED = 0;\n"""
                for i, (value_name, _) in enumerate(values, 0):
                    proto += f"""  {
                    betterproto.casing.snake_case(enum_name).upper()}_{
                    value_name} = {i + 1};\n"""
                proto += '}\n\n'
            for message_name, fields in self.messages.items():
                proto += f'message {message_name} {{\n'
                proto += f"""  option (package_info.v1.package_name) = "{
                self.package_name}";\n"""
                proto += f'  optional string {META_FIELD_PREFIX_PACKAGE_NAME}'
                proto += f"""{self.package_name.replace(".", "_dot_")} = {
                META_FIELD_PREFIX_PACKAGE_NAME_INDEX};\n"""
                for field_name, field_type in fields:
                    proto += re.sub(
                        r'\n(?=.)',
                        '\n',
                        field_type.get_definitions(
                            field_name,
                            current_package=self.package_name,
                        ),
                    )
                for i, (field_name, field_type) in enumerate(fields, 2):
                    try:
                        proto += f"""  {field_type.get_proto(
                            field_name,
                            current_package=self.package_name,
                        )
                        } {field_name} = {i};\n"""
                    except TypeError as exception:
                        if 'Empty Union' in str(exception):
                            continue
                        if 'Unknown type' in str(exception):
                            continue
                        raise
                proto += '}\n\n'
            for name, field_type in self.types.items():
                proto += field_type.get_embedded_definitions(
                    name,
                    current_package=self.package_name,
                )
        except TypeError as e:
            msg = f'Error in {self.package_name}'
            raise TypeError(msg) from e
        else:
            return proto


def _generate_operations_proto(output_directory: Path) -> None:
    proto = '\n'
    if actions:
        proto += 'message Action {\n'
        proto += '  oneof action {\n'
        for i, (action, _) in enumerate(sorted(actions), 1):
            # proto += f"""    {package_name}.v1.{action} {
            proto += f"""    {action} {
            betterproto.casing.snake_case(action)} = {i};\n"""
        proto += '  }\n'
        proto += '}\n\n'
    if events:
        proto += 'message Event {\n'
        proto += '  oneof event {\n'
        for i, (event, _) in enumerate(sorted(events), 1):
            # proto += f"""    {package_name}.v1.{event} {
            proto += f"""    {event} {
            betterproto.casing.snake_case(event)} = {i};\n"""
        proto += '  }\n'
        proto += '}\n\n'
    operations_proto_path = output_directory / 'ubo' / 'v1' / 'ubo.proto'
    with operations_proto_path.open('a') as file:
        file.write(proto)


def parse(input_module: ModuleType) -> _ProtoGenerator:
    """Generate proto files from actions, events and states defined in Python files."""
    if not input_module.__file__:
        msg = 'Module must be a file'
        raise ValueError(msg)
    with Path(input_module.__file__).open() as file:
        tree = ast.parse(file.read())

    generator = _ProtoGenerator(module=input_module)
    generator.visit(tree)

    return generator


if __name__ == '__main__':
    print('🚀 Generating proto files...')
    output_directory = Path('ubo_app/rpc/proto/')

    import ubo_gui.menu.types

    import ubo_app.store.dispatch_action
    import ubo_app.store.operations

    generators: list[_ProtoGenerator] = []

    generators.append(parse(ubo_gui.menu.types))
    generators.append(parse(ubo_app.store.operations))
    generators.append(
        parse(ubo_app.store.dispatch_action),
    )
    generators.extend(
        parse(importlib.import_module(f'ubo_app.store.services.{file.stem}'))
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

    _generate_operations_proto(output_directory)

    print('🎉 Proto files generated successfully!')
