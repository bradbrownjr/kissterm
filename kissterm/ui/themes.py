"""The theme catalog: what `Config.theme` and the Settings dropdown can name.

kissterm's colors were already CSS variables (`$primary`, `$accent`,
`$background`, ...) throughout `styles.py` before theming existed as a
feature -- that is what made this module possible to add without touching a
single style rule. Every `$name` in this app resolves through Textual's own
`Theme` object, so switching the active theme re-paints the whole app at once;
nothing here duplicates Textual's theme machinery, it only curates and
validates what `Config.theme` is allowed to name.

**No color values are invented here.** Every preset is one of Textual's own
`BUILTIN_THEMES`, verified against `textual.theme.BUILTIN_THEMES` at import
time (`test_every_catalog_entry_is_a_real_textual_theme`) rather than typed in
by hand from memory -- a theme name that silently resolves to the wrong colors
because a hex code was mistyped is worse than one that fails loudly.

**Not every family has a light variant, and this catalog does not pretend
otherwise.** Tokyo Night, Nord, Dracula, Monokai and Gruvbox ship from their
original authors (and from Textual) as dark-only palettes; there is no
official light counterpart to point at, so none is listed. Inventing a
"Tokyo Night Light" by guessing which hexes to flip would be presenting a
fabricated palette as if it were the real, recognized theme, which is exactly
the kind of thing this project's house rules say not to do (see AGENTS.md's
`# UNVERIFIED:` convention). Where a request wants a light mode and the
family does not have one, `ansi-light` or `textual-light` are the honest
alternatives -- see `SUGGESTED_LIGHT_ALTERNATIVES`.

**`ansi-dark`/`ansi-light` are the truest "sync with my terminal" option.**
They do not carry their own palette at all -- they render using the
*terminal's own* 16 ANSI colors, whatever the operator's terminal emulator or
color-scheme switcher already has configured. Picking one of these means
kissterm's colors change automatically whenever the terminal's theme does,
with nothing to keep in sync by hand.

**`"custom"` is the escape hatch for an exact hex match.** `Config.custom_theme`
holds one hex value per Textual `Theme` field, loaded from a `[custom_theme]`
table in `config.toml` (see `config.toml.example`), which is the point: an
external theme-sync tool, or a value copied by hand from a terminal emulator's
own color-scheme file, needs nowhere else to go. It is not yet editable field-
by-field in the Settings UI -- see docs/ROADMAP.md P6 -- so for now it is a
config-file-only feature, deliberately, rather than eleven hex-input widgets
shipped half-finished.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.theme import BUILTIN_THEMES, Theme

#: What ships if `Config.theme` is empty, unset, or names something that no
#: longer resolves. Requested by name directly: this is not an arbitrary
#: pick, it's the operator's own stated preference.
DEFAULT_THEME = "tokyo-night"

#: Field names copied out of a `Theme` object when building one from config.
#: Kept as one tuple so `themes.py` and `config.py` agree on the exact set
#: without importing from each other.
CUSTOM_THEME_FIELDS = (
    "primary",
    "secondary",
    "warning",
    "error",
    "success",
    "accent",
    "foreground",
    "background",
    "surface",
    "panel",
)


@dataclass(frozen=True, slots=True)
class ThemeVariant:
    id: str  # the exact Textual theme name, e.g. "catppuccin-mocha"
    label: str  # shown in the Settings dropdown, e.g. "Mocha (dark)"
    dark: bool


@dataclass(frozen=True, slots=True)
class ThemeFamily:
    name: str  # e.g. "Catppuccin"
    variants: tuple[ThemeVariant, ...]
    note: str = ""


#: The curated catalog. Order is display order in the Settings dropdown.
#: Every `ThemeVariant.id` must be a real key in `textual.theme.BUILTIN_THEMES`
#: -- enforced by a test, not by convention.
THEME_CATALOG: tuple[ThemeFamily, ...] = (
    ThemeFamily(
        "Tokyo Night",
        (ThemeVariant("tokyo-night", "Tokyo Night (dark)", True),),
        note="Dark-only upstream; no official light variant exists.",
    ),
    ThemeFamily(
        "Catppuccin",
        (
            ThemeVariant("catppuccin-latte", "Latte (light)", False),
            ThemeVariant("catppuccin-frappe", "Frappe (dark)", True),
            ThemeVariant("catppuccin-macchiato", "Macchiato (dark)", True),
            ThemeVariant("catppuccin-mocha", "Mocha (dark)", True),
        ),
        note="Mocha is Catppuccin's own darkest, highest-contrast flavor -- "
        "not a separate theme family from Catppuccin.",
    ),
    ThemeFamily(
        "Nord",
        (ThemeVariant("nord", "Nord (dark)", True),),
        note="Dark-only upstream.",
    ),
    ThemeFamily(
        "Gruvbox",
        (ThemeVariant("gruvbox", "Gruvbox (dark)", True),),
        note="Dark-only as shipped by Textual.",
    ),
    ThemeFamily(
        "Dracula",
        (ThemeVariant("dracula", "Dracula (dark)", True),),
        note="Dark-only upstream.",
    ),
    ThemeFamily(
        "Monokai",
        (ThemeVariant("monokai", "Monokai (dark)", True),),
        note="Dark-only upstream.",
    ),
    ThemeFamily(
        "Solarized",
        (
            ThemeVariant("solarized-dark", "Solarized (dark)", True),
            ThemeVariant("solarized-light", "Solarized (light)", False),
        ),
    ),
    ThemeFamily(
        "Rose Pine",
        (
            ThemeVariant("rose-pine", "Rose Pine (dark)", True),
            ThemeVariant("rose-pine-moon", "Rose Pine Moon (dark, lower contrast)", True),
            ThemeVariant("rose-pine-dawn", "Rose Pine Dawn (light)", False),
        ),
    ),
    ThemeFamily(
        "Atom One",
        (
            ThemeVariant("atom-one-dark", "Atom One (dark)", True),
            ThemeVariant("atom-one-light", "Atom One (light)", False),
        ),
    ),
    ThemeFamily(
        "Textual",
        (
            ThemeVariant("textual-dark", "Textual Dark", True),
            ThemeVariant("textual-light", "Textual Light", False),
        ),
        note="kissterm's own original default, before theming existed.",
    ),
    ThemeFamily(
        "Terminal (ANSI passthrough)",
        (
            ThemeVariant("ansi-dark", "Terminal ANSI (dark)", True),
            ThemeVariant("ansi-light", "Terminal ANSI (light)", False),
        ),
        note="Uses your terminal's own 16-color palette directly -- the "
        "truest way to sync with a terminal color scheme, since there is no "
        "separate palette to keep in sync.",
    ),
    ThemeFamily(
        "Custom",
        (ThemeVariant("custom", "Custom (config.toml [custom_theme])", True),),
        note="Exact hex values from config.toml. Not yet editable in the "
        "Settings UI -- see docs/ROADMAP.md P6.",
    ),
)

#: When a family has no light member, the nearest honest substitute -- never
#: a fabricated light palette for that family.
SUGGESTED_LIGHT_ALTERNATIVES = ("ansi-light", "textual-light", "catppuccin-latte")


def all_theme_ids() -> tuple[str, ...]:
    """Every id this catalog exposes, in catalog order."""
    return tuple(v.id for family in THEME_CATALOG for v in family.variants)


def choices() -> tuple[tuple[str, str], ...]:
    """`(label, id)` pairs for a Settings dropdown, grouped visually by family."""
    out: list[tuple[str, str]] = []
    for family in THEME_CATALOG:
        for variant in family.variants:
            prefix = family.name if len(family.variants) == 1 else f"{family.name} -- "
            label = variant.label if len(family.variants) == 1 else f"{family.name} -- {variant.label}"
            out.append((label, variant.id))
    return tuple(out)


def find_variant(theme_id: str) -> ThemeVariant | None:
    for family in THEME_CATALOG:
        for variant in family.variants:
            if variant.id == theme_id:
                return variant
    return None


def resolve_theme_id(requested: str) -> tuple[str, str]:
    """Validate a configured theme id.

    Returns `(id_to_use, warning)`; `warning` is empty on success. Never
    raises -- an unrecognised or empty theme name falls back to
    `DEFAULT_THEME` rather than leaving the app unstyled or crashing on
    startup, matching `config.py`'s "never let a config problem stop the app"
    rule.
    """
    requested = (requested or "").strip()
    if not requested:
        return DEFAULT_THEME, ""
    if requested == "custom" or requested in BUILTIN_THEMES:
        return requested, ""
    return (
        DEFAULT_THEME,
        f"theme {requested!r} is not recognised; using {DEFAULT_THEME!r}. "
        f"See config.toml.example for the full list.",
    )


def build_custom_theme(colors: dict[str, str], dark: bool = True) -> Theme:
    """Build a Textual `Theme` named "custom" from `Config.custom_theme`.

    `colors` is expected to already be validated hex strings (see
    `config._load_hex_color`) -- this function trusts its input rather than
    re-validating, because `Config` is the one place that decides what a bad
    value degrades to.
    """
    return Theme(
        name="custom",
        dark=dark,
        **{field: colors[field] for field in CUSTOM_THEME_FIELDS if field in colors},
    )
