"""Mail is the launch tab unless Settings > Open on says otherwise."""

from kissterm import _isolate

_isolate.isolate()

import kissterm.ui.app as ui_app  # noqa: E402
from kissterm.config import Config  # noqa: E402
from kissterm.ui.commands import TAB_ORDER  # noqa: E402


def test_the_product_default_is_mail():
    assert ui_app.DEFAULT_START_TAB == "mail"
    assert Config().start_tab == ""


def test_start_tab_resolves_and_ignores_unknown_names():
    app = ui_app.KissTermApp.__new__(ui_app.KissTermApp)
    for wanted, expected in (("", "mail"), ("terminal", "terminal"), ("nonsense", "mail")):
        app.config = Config(start_tab=wanted)
        assert app._start_tab() == expected
    assert TAB_ORDER[:4] == ("mail", "bulletins", "files", "terminal")
