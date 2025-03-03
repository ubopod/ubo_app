"""The types used in the proto generation."""

from __future__ import annotations

import functools
from typing import Literal, Self, get_args

import betterproto.casing
from immutable import Immutable

FieldType = Literal['string', 'int64', 'float', 'bool', 'bytes']


global_messages: dict[str, tuple[str, list[tuple[str, _Type]]]] = {}
global_enums: dict[str, str] = {}
global_types: dict[str, str] = {}


class _Type(Immutable):
    """Root class for all types."""

    def get_proto(self: Self, name: str, *, current_package: str | None) -> str:
        """Get the proto representation of the type."""
        _ = name, current_package
        raise NotImplementedError

    def get_embedded_proto(self: Self, name: str) -> str:
        """Get the proto representation of the type when embedded."""
        return self.get_proto(name, current_package=self.package)

    @property
    def as_basic_type(self: Self) -> str | None:
        """Get the basic type of the type."""
        return None

    @property
    def local_name(self: Self) -> str:
        """Get the local name of the type."""
        raise NotImplementedError

    def get_definitions(self: Self, name: str, *, current_package: str | None) -> str:
        """Get the definitions of the type."""
        _ = name, current_package
        raise NotImplementedError

    def get_embedded_definitions(
        self: Self,
        name: str,
        *,
        current_package: str | None,
    ) -> str:
        """Get the definitions of the type when embedded."""
        return self.get_definitions(name, current_package=current_package)

    @property
    def package(self: Self) -> str | None:
        """Get the package of the type."""
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
        if self.type in ('BaseAction', 'UboAction'):
            return 'Action'
        if self.type == 'UboEvent':
            return 'Event'
        if self.type == 'PageWidget':  # Not supported
            return 'string'
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
            if self.type in ('Color', 'UboAction', 'UboEvent', 'BaseAction'):
                return None
            msg = f'Unknown type "{self.type}"'
            raise TypeError(msg)
        return None


class _OptionalType(_Type):
    type: _Type

    def get_proto(self: Self, name: str, *, current_package: str | None) -> str:
        _ = current_package
        return f"""optional {
            self.type.get_embedded_proto(
                betterproto.casing.pascal_case(name),
            )
        }"""

    def get_embedded_proto(self: Self, name: str) -> str:
        return betterproto.casing.pascal_case(name)

    @property
    def local_name(self: Self) -> str:
        return 'optional'

    def get_definitions(self: Self, name: str, *, current_package: str | None) -> str:
        return f"""{
            self.type.get_embedded_definitions(
                f'{betterproto.casing.pascal_case(name)}',
                current_package=current_package,
            )
        }"""

    def get_embedded_definitions(
        self: Self,
        name: str,
        *,
        current_package: str | None,
    ) -> str:
        return f"""{
            self.type.get_embedded_definitions(
                f'{betterproto.casing.pascal_case(name)}Optional',
                current_package=current_package,
            )
        }
message {betterproto.casing.pascal_case(name)} {{
  optional {
            self.type.get_embedded_proto(
                f'{betterproto.casing.pascal_case(name)}Optional',
            )
        } items = 1;
}}
"""


class _ListType(_Type):
    type: _Type

    def get_proto(self: Self, name: str, *, current_package: str | None) -> str:
        _ = current_package
        return f"""repeated {
            self.type.get_embedded_proto(
                betterproto.casing.pascal_case(name),
            )
        }"""

    def get_embedded_proto(self: Self, name: str) -> str:
        return betterproto.casing.pascal_case(name)

    @property
    def local_name(self: Self) -> str:
        return 'list'

    def get_definitions(self: Self, name: str, *, current_package: str | None) -> str:
        return f"""{
            self.type.get_embedded_definitions(
                f'{betterproto.casing.pascal_case(name)}',
                current_package=current_package,
            )
        }"""

    def get_embedded_definitions(
        self: Self,
        name: str,
        *,
        current_package: str | None,
    ) -> str:
        return f"""{
            self.type.get_embedded_definitions(
                f'{betterproto.casing.pascal_case(name)}Item',
                current_package=current_package,
            )
        }
message {betterproto.casing.pascal_case(name)} {{
  repeated {
            self.type.get_embedded_proto(
                f'{betterproto.casing.pascal_case(name)}Item',
            )
        } items = 1;
}}
"""


class _SetType(_Type):
    type: _Type

    def get_proto(self: Self, name: str, *, current_package: str | None) -> str:
        _ = current_package
        return self.get_embedded_proto(name)

    def get_embedded_proto(self: Self, name: str) -> str:
        return betterproto.casing.pascal_case(name) + 'SetType'

    @property
    def local_name(self: Self) -> str:
        return 'set'

    def get_definitions(self: Self, name: str, *, current_package: str | None) -> str:
        return self.get_embedded_definitions(
            name,
            current_package=current_package,
        )

    def get_embedded_definitions(
        self: Self,
        name: str,
        *,
        current_package: str | None,
    ) -> str:
        return f"""{
            self.type.get_embedded_definitions(
                f'{betterproto.casing.pascal_case(name)}Item',
                current_package=current_package,
            )
        }
message {betterproto.casing.pascal_case(name)}SetType {{
  repeated {
            self.type.get_embedded_proto(
                f'{betterproto.casing.pascal_case(name)}Item',
            )
        } items = 1;
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
                    definitions += f"""  {item.get_embedded_proto(f'{name}_{index}')} {
                        betterproto.casing.snake_case(item.local_name)
                    } = {index};\n"""
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
        return f"""map<{
            self.key_type.get_proto(
                f'{name}_key',
                current_package=current_package,
            )
        }, {
            self.value_type.get_proto(
                f'{name}_value',
                current_package=current_package,
            )
        }>"""

    def get_embedded_proto(self: Self, name: str) -> str:
        return f'{betterproto.casing.pascal_case(name)}Dict'

    @property
    def local_name(self: Self) -> str:
        return 'dict'

    def get_definitions(self: Self, name: str, *, current_package: str | None) -> str:
        return f"""{
            self.key_type.get_definitions(
                f'{name}_key',
                current_package=current_package,
            )
        }\n\n{
            self.value_type.get_definitions(
                f'{name}_value',
                current_package=current_package,
            )
        }"""

    def get_embedded_definitions(
        self: Self,
        name: str,
        *,
        current_package: str | None,
    ) -> str:
        return f"""{
            self.key_type.get_embedded_definitions(
                f'{name}_key',
                current_package=current_package,
            )
        }

{
            self.value_type.get_embedded_definitions(
                f'{name}_value',
                current_package=current_package,
            )
        }
message {betterproto.casing.pascal_case(name)}Dict {{
  {self.get_proto(name, current_package=current_package)} items = 1;
}}"""


_ = [_BasicType, _OptionalType, _ListType, _SetType, _UnionType, _DictType]
