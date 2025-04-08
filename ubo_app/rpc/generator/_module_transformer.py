"""Transform a Python module into a proto file objects."""

# ruff: noqa: N802, T201
from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, Any

import betterproto.casing

from ubo_app.rpc.generator._types import (
    _BasicType,
    _DictType,
    _ListType,
    _OptionalType,
    _SetType,
    _Type,
    _UnionType,
    global_enums,
    global_messages,
    global_types,
)
from ubo_app.rpc.message_to_object import (
    META_FIELD_PREFIX_PACKAGE_NAME,
    META_FIELD_PREFIX_PACKAGE_NAME_INDEX,
)

if TYPE_CHECKING:
    from types import ModuleType


class _ProtoGenerator(ast.NodeVisitor):
    def __init__(
        self: _ProtoGenerator,
        module: ModuleType,
        actions: list,
        events: list,
    ) -> None:
        self.messages: dict[str, list[tuple[str, _Type]]] = {}
        self.enums: dict[str, list[tuple[str, Any]]] = {}
        self.types: dict[str, _Type] = {}
        self.module = module
        self.actions = actions
        self.events = events
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
                        self.types[node.targets[0].id]
                    }"'''
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
            self.actions.append((message_name, self.package_name))
        if message_name.endswith('Event'):
            self.events.append((message_name, self.package_name))

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
                f'Enum "{enum_name}" is already defined in "{global_types[enum_name]}"'
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

                if value.value.id in ('Sequence', 'list'):
                    return _ListType(type=self.get_field_type(value=value.slice))

                if value.value.id == 'set':
                    return _SetType(type=self.get_field_type(value=value.slice))

                if value.value.id == 'tuple' and isinstance(value.slice, ast.Tuple):
                    if (
                        len(value.slice.elts) == 2  # noqa: PLR2004
                        and isinstance(value.slice.elts[1], ast.Constant)
                        and value.slice.elts[1].value is ...
                    ):
                        types = [self.get_field_type(value=value.slice.elts[0])]
                    else:
                        types = list(
                            {
                                self.get_field_type(value=elt)
                                for elt in value.slice.elts
                            },
                        )
                    return _ListType(
                        type=_UnionType.from_(
                            types=types,
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

                if value.value.id == 'IO':
                    return _BasicType(type='bytes')

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
                proto += f"""  {betterproto.casing.snake_case(enum_name).upper()}_{
                    self.package_name.replace('.', '_dot_').upper()
                }_UNSPECIFIED = 0;\n"""
                for i, (value_name, _) in enumerate(values, 0):
                    proto += f"""  {betterproto.casing.snake_case(enum_name).upper()}_{
                        value_name
                    } = {i + 1};\n"""
                proto += '}\n\n'
            for message_name, fields in self.messages.items():
                proto += f'message {message_name} {{\n'
                proto += f"""  option (package_info.v1.package_name) = "{
                    self.package_name
                }";\n"""
                proto += f'  optional string {META_FIELD_PREFIX_PACKAGE_NAME}'
                proto += f"""{self.package_name.replace('.', '_dot_')} = {
                    META_FIELD_PREFIX_PACKAGE_NAME_INDEX
                };\n"""
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
                        proto += f"""  {
                            field_type.get_proto(
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
