"""No kissterm widget replaces a private Textual method by accident.

`FilePickerScreen` had a helper named `_render`, which is also
`Widget._render`, the method Textual calls to draw a widget; it returned
None and Browse files crashed the app (operator, 2026-10-03). A private
override that is meant has to be named here, with why.
"""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import importlib  # noqa: E402
import inspect  # noqa: E402
import pkgutil  # noqa: E402

from textual.dom import DOMNode  # noqa: E402

import kissterm.ui as ui  # noqa: E402

#: Deliberate overrides of a private Textual method, each with its reason
#: in the overriding method's docstring.
MEANT = {
    ("KissTermApp", "_fatal_error"),  # crash report without locals
    ("_SendInput", "_on_paste"),  # paste sanitized (AGENTS.md section 7)
    ("WrapLog", "_render_line"),  # wrapping in a resizable column
    ("_AddressBookTable", "_on_click"),
    ("_AddressBookTable", "_post_selected_message"),
    ("MessageList", "_on_click"),
    ("KissTermHeader", "_on_click"),
}

#: Set on every class by Textual's own metaclass machinery, not by us.
_GENERATED = {
    "_decorated_handlers", "_reactives", "_inherit_css", "_inherit_bindings",
    "_inherit_component_classes", "_css_type_name", "_merged_bindings",
    "_css_type_names", "_computes",
}


def _overrides():
    for info in pkgutil.iter_modules(ui.__path__):
        module = importlib.import_module(f"kissterm.ui.{info.name}")
        for name, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ != module.__name__ or not issubclass(cls, DOMNode):
                continue
            for attr in vars(cls):
                if not attr.startswith("_") or attr.startswith("__") or attr in _GENERATED:
                    continue
                if any(base.__module__.startswith("textual") and attr in vars(base)
                       for base in cls.__mro__[1:]):
                    yield name, attr


def test_every_private_textual_override_is_meant():
    assert set(_overrides()) - MEANT == set()
