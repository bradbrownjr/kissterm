"""Every built-in guide renders, and every key it names is a real binding.

`kissterm/guides.py` names keys only through `{key:action}` placeholders, so
a command that is renamed or loses its key fails here instead of leaving a
guide telling a newcomer to press something that does nothing.
"""

from kissterm._isolate import isolate

isolate()

import re  # noqa: E402

import pytest  # noqa: E402

from kissterm import guides  # noqa: E402


@pytest.mark.parametrize("guide", guides.GUIDES, ids=lambda g: g.title)
def test_every_guide_renders_with_no_placeholder_left(guide):
    text = guides.render(guide)
    assert "{key:" not in text
    assert guide.summary and text.strip()


def test_an_unknown_action_fails_loudly():
    bad = guides.Guide("Bad", "x", "Press {key:no_such_action}.")
    with pytest.raises(KeyError):
        guides.render(bad)


def test_guides_name_keys_through_the_registry_not_by_hand():
    """A literal 'Ctrl+N' typed into prose goes stale on the next key change;
    the placeholder cannot."""
    for guide in guides.GUIDES:
        assert not re.search(r"\bCtrl\+[A-Z]\b", guide.body), guide.title
        assert not re.search(r"\bF(?:[1-9]|10)\b", guide.body), guide.title
