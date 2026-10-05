"""The settings schema, as the terminal UI draws it: the core's
(`kissterm/core/settings_schema.py`, where every rule lives) with the
theme list registered, since Textual's themes are this client's."""

from ..core import settings_schema as _core
from .themes import choices as _theme_choices

_core.register_choices("theme", _theme_choices())

from ..core.settings_schema import (  # noqa: E402 - after the theme list is in
    SETTINGS_SCHEMA,
    Field,
    Section,
    ValidationError,
    coerce,
    cross_check,
    format_value,
    get_value,
    set_value,
)

__all__ = [
    "SETTINGS_SCHEMA",
    "Field",
    "Section",
    "ValidationError",
    "coerce",
    "cross_check",
    "format_value",
    "get_value",
    "set_value",
]
