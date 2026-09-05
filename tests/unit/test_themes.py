"""The theme catalog: every entry real, every fallback safe.

The one invariant that matters most here is that `Config.theme` can NEVER
leave the app unstyled or crash it -- an operator hand-editing config.toml
will eventually typo a theme name, and that must degrade exactly like every
other bad value in this project: fall back, warn, keep running.
"""

from __future__ import annotations

from textual.theme import BUILTIN_THEMES

from kissterm.ui import themes


def test_every_catalog_entry_is_a_real_textual_theme():
    """No hand-typed hex values pretending to be an upstream theme."""
    for family in themes.THEME_CATALOG:
        for variant in family.variants:
            if variant.id == "custom":
                continue
            assert variant.id in BUILTIN_THEMES, (
                f"{family.name} -- {variant.label} ({variant.id}) is not a "
                f"real textual.theme.BUILTIN_THEMES entry"
            )


def test_dark_flag_matches_the_real_theme():
    for family in themes.THEME_CATALOG:
        for variant in family.variants:
            if variant.id == "custom":
                continue
            real = BUILTIN_THEMES[variant.id]
            assert variant.dark == real.dark, (
                f"{variant.id} claims dark={variant.dark} but Textual says {real.dark}"
            )


def test_default_theme_is_a_real_choice():
    assert themes.DEFAULT_THEME in themes.all_theme_ids()
    assert themes.DEFAULT_THEME in BUILTIN_THEMES


def test_default_theme_is_tokyo_night():
    """The operator's own stated preference, not an arbitrary pick."""
    assert themes.DEFAULT_THEME == "tokyo-night"


def test_catppuccin_mocha_is_grouped_under_catppuccin_not_standalone():
    """Mocha is one of Catppuccin's own flavors, not a separate family."""
    names = {f.name for f in themes.THEME_CATALOG}
    assert "Mocha" not in names
    catppuccin = next(f for f in themes.THEME_CATALOG if f.name == "Catppuccin")
    assert "catppuccin-mocha" in {v.id for v in catppuccin.variants}


def test_no_ids_repeat_across_the_catalog():
    ids = themes.all_theme_ids()
    assert len(ids) == len(set(ids))


def test_choices_returns_a_label_id_pair_per_variant():
    total_variants = sum(len(f.variants) for f in themes.THEME_CATALOG)
    assert len(themes.choices()) == total_variants
    for label, theme_id in themes.choices():
        assert isinstance(label, str) and label
        assert isinstance(theme_id, str) and theme_id


def test_find_variant_round_trips():
    variant = themes.find_variant("tokyo-night")
    assert variant is not None and variant.dark is True
    assert themes.find_variant("does-not-exist") is None


# ---------------------------------------------------------------------------
# resolve_theme_id -- must never leave the app unstyled or crash it
# ---------------------------------------------------------------------------


def test_resolve_accepts_every_catalog_id():
    for theme_id in themes.all_theme_ids():
        resolved, warning = themes.resolve_theme_id(theme_id)
        assert resolved == theme_id
        assert warning == ""


def test_resolve_accepts_any_textual_builtin_not_just_the_curated_subset():
    """A name outside our curated list but still real to Textual should work
    (e.g. ansi-dark is curated, but this guards the general case)."""
    resolved, warning = themes.resolve_theme_id("dracula")
    assert resolved == "dracula" and warning == ""


def test_resolve_falls_back_on_garbage():
    resolved, warning = themes.resolve_theme_id("not-a-real-theme")
    assert resolved == themes.DEFAULT_THEME
    assert "not-a-real-theme" in warning


def test_resolve_falls_back_on_empty_or_none():
    for bad in ("", "   ", None):
        resolved, warning = themes.resolve_theme_id(bad)  # type: ignore[arg-type]
        assert resolved == themes.DEFAULT_THEME


# ---------------------------------------------------------------------------
# Custom theme construction
# ---------------------------------------------------------------------------


def test_build_custom_theme_uses_the_given_colors():
    colors = {f: "#123456" for f in themes.CUSTOM_THEME_FIELDS}
    theme = themes.build_custom_theme(colors, dark=False)
    assert theme.name == "custom"
    assert theme.dark is False
    assert theme.primary == "#123456"


def test_build_custom_theme_defaults_dark_true():
    theme = themes.build_custom_theme({f: "#000000" for f in themes.CUSTOM_THEME_FIELDS})
    assert theme.dark is True
