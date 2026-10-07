"""What the Files tab's viewer shows: a zip's contents, Markdown, HTML.

The files here came off the air or off a BBS (`YAPP <name>`), so every one
is untrusted. The viewer only ever *reads* them, and this module is the
reading, kept apart from `ui/file_viewer.py` so it is tested without a
screen:

- **A zip is read in memory, never extracted.** A member's name never
  becomes a path on disk, so a hostile archive (`../../.bashrc`, an
  absolute name) cannot write anywhere; the listing shows the names as
  text. A member is read only up to `MAX_MEMBER` bytes and a listing
  stops at `MAX_MEMBERS` entries, so a zip bomb costs nothing; an
  encrypted member is refused with a message rather than asking for a
  password.
- **HTML is turned into Markdown here, with the standard library's
  `html.parser`**, and shown by Textual's Markdown widget. Scripts,
  styles and everything in `<head>` but the title are dropped, so nothing
  runs and no remote resource is fetched (the PKTNET forms load jQuery
  from code.jquery.com; it is never requested). Links keep their text,
  with the address after it, and the viewer never follows one. Form
  controls are drawn as what they are -- `[________]` for a text box,
  `[Routine v]` for a list, `[ Generate ]` for a button -- so a form's
  layout reads as it would in a browser; filling one in is the forms
  framework's job (`mail/forms.py`, `pktnet_form`).
  `html2text` was the obvious library and is GPL, which an MIT runtime
  cannot depend on; `markdownify` pulls in BeautifulSoup. A page this
  viewer gets wrong is shown readably anyway, since the fallback is text.
- **All text goes through `monitor.sanitize`** before it is parsed, as
  everything remote does (AGENTS.md, "Untrusted input").
"""

from __future__ import annotations

import io
import re
import zipfile
from html.parser import HTMLParser
from pathlib import PurePosixPath

from .monitor import sanitize

#: The most of one zip member the viewer reads.
MAX_MEMBER = 1024 * 1024
#: The most of a file on disk a viewer reads.
MAX_FILE = 16 * 1024 * 1024
#: The most text `describe` hands a remote client for one file.
MAX_SHOWN = 256 * 1024
#: The most entries a zip listing shows.
MAX_MEMBERS = 2000

_MARKDOWN = {".md", ".markdown", ".mdown"}
_HTML = {".html", ".htm", ".xhtml"}
_ZIP = {".zip"}


def kind_of(name: str, data: bytes = b"") -> str:
    """"zip", "markdown", "html", "text" or "binary", by name, then by
    content: a zip by its signature whatever it is called, binary when a
    NUL is in the first kilobyte."""
    suffix = PurePosixPath(name.lower()).suffix
    if suffix in _ZIP or data[:4] == b"PK\x03\x04":
        return "zip"
    if b"\x00" in data[:1024]:
        return "binary"
    if suffix in _MARKDOWN:
        return "markdown"
    if suffix in _HTML:
        return "html"
    return "text"


def zip_members(data: bytes) -> list[tuple[str, int]]:
    """The files in a zip (not its folders) as (name, size), in archive
    order, at most `MAX_MEMBERS`. ValueError if it is not a readable zip."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return [(info.filename, info.file_size) for info in archive.infolist()
                    if not info.is_dir()][:MAX_MEMBERS]
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise ValueError(f"not a readable zip: {exc}") from exc


def zip_read(data: bytes, name: str) -> bytes:
    """One member of a zip, at most `MAX_MEMBER` bytes. ValueError with a
    reason if it is encrypted, too large or unreadable."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo(name)
            if info.flag_bits & 0x1:
                raise ValueError(f"{name} is encrypted; the viewer does not ask for passwords")
            if info.file_size > MAX_MEMBER:
                raise ValueError(f"{name} is {info.file_size:,} bytes; the viewer reads up to "
                                 f"{MAX_MEMBER:,}")
            with archive.open(info) as stream:
                return stream.read(MAX_MEMBER + 1)[:MAX_MEMBER]
    except (zipfile.BadZipFile, KeyError, OSError, RuntimeError, NotImplementedError) as exc:
        raise ValueError(f"cannot read {name}: {exc}") from exc


#: The most of a text file the reader shows before "[preview ends here]".
PREVIEW_BYTES = 16 * 1024


def preview(path) -> tuple[str, str, bool]:
    """What a reader shows for one file before it is opened: (kind, text,
    cut short). A zip is its member list ("broken" with the reason when
    it cannot be read); a binary file one line saying so; anything else its first `PREVIEW_BYTES`, sanitized. The terminal's
    reader and the remote `mail_read` both show this."""
    with open(path, "rb") as handle:
        data = handle.read(PREVIEW_BYTES + 1)
    kind = kind_of(path.name, data)
    if kind == "zip":
        try:
            members = zip_members(path.read_bytes())
        except (OSError, ValueError) as exc:
            return "broken", f"{path.name}: {exc}", False
        listing = "\n".join(f"{size:>10,}  {name}" for name, size in members)
        return kind, sanitize(listing.encode()) or "(empty zip)", False
    if kind == "binary":
        return kind, f"{path.name}: not a text file ({path.stat().st_size:,} bytes).", False
    return kind, sanitize(data[:PREVIEW_BYTES]), len(data) > PREVIEW_BYTES


_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)|!\[([^\]]*)\]\[[^\]]*\]")


def no_images(markdown: str) -> str:
    """Markdown with each image replaced by `[image: alt]`, as the HTML
    conversion does: a viewer that rendered one would fetch whatever address
    the file names, and nothing from the air may reach the network."""
    return _IMAGE.sub(lambda m: f"[image: {m.group(1) or m.group(2) or ''}]", markdown)


def describe(name: str, data: bytes) -> dict:
    """One file, or one zip member, as a remote client's viewer shows it
    (the terminal's `FileViewerScreen`): `kind`, a zip's `members` (name,
    size), `markdown` for Markdown and HTML (HTML converted, images
    never kept), `text` otherwise, `problem` when it cannot be shown, and
    `form`, the kissterm form a PKTNET page is. Everything is sanitized
    and size-capped; nothing is run, fetched or extracted."""
    kind = kind_of(name, data)
    out: dict = {"name": text_of(name.encode()), "size": len(data), "kind": kind,
                 "members": [], "markdown": "", "text": "", "problem": "", "form": ""}
    if kind == "zip":
        try:
            out["members"] = [[text_of(n.encode()), size] for n, size in zip_members(data)]
        except ValueError as exc:
            out["kind"], out["problem"] = "broken", str(exc)
    elif kind in ("markdown", "html"):
        source = text_of(data) if kind == "markdown" else html_to_markdown(data)
        out["markdown"] = no_images(source)[:MAX_SHOWN]
        if kind == "html":
            out["form"] = pktnet_form(data)
    elif kind == "text":
        out["text"] = text_of(data)[:MAX_SHOWN]
    else:
        out["problem"] = "Not a text file; the viewer does not open it."
    return out


def text_of(data: bytes) -> str:
    """Remote bytes as text a widget may show (`monitor.sanitize`)."""
    return sanitize(data)


def html_title(data: bytes) -> str:
    """A page's `<title>`, or ""."""
    parser = _HtmlToMarkdown()
    parser.feed(text_of(data))
    parser.close()
    return parser.title.strip()


#: The PKTNET forms (vden.org/pktnet, KN4LQN and N3MEL) by their page's
#: `<title>`, and the kissterm form that fills each: a forms-framework id
#: (`mail/data/forms/`), or "radiogram" for the NTS radiogram screen. The
#: page's script is never run; the kissterm form reproduces what its
#: "Generate" button writes, from the page's source (each data file says
#: which version). A title not here is shown and not offered.
PKTNET_FORMS = {
    "PACKET BULLETIN MESSAGE": "pktnet_bulletin",
    "PACKET CHECK-IN FORM": "pktnet_checkin",
    "PACKET RADIOGRAM": "radiogram",
    "ICS-213 GENERAL MESSAGE": "pktnet_ics213",
    "PACKET RADIO FIELD SITUATION REPORT": "pktnet_fsr",
    "PACKET RADIO SEVERE WEATHER REPORT": "pktnet_severe_wx",
    "PACKET COMMUNICATIONS LOG FORM 309": "pktnet_form309",
}


def pktnet_form(data: bytes) -> str:
    """The kissterm form for a PKTNET form page (`PKTNET_FORMS`), or ""."""
    return PKTNET_FORMS.get(" ".join(html_title(data).split()).upper(), "")


def html_to_markdown(data: bytes) -> str:
    """An HTML page as Markdown (module docstring)."""
    parser = _HtmlToMarkdown()
    parser.feed(text_of(data))
    parser.close()
    return parser.markdown()


#: Elements whose content is never shown.
_SKIP = {"script", "style", "noscript", "template", "iframe", "object", "embed", "svg"}
#: Elements that end a block of text.
_BLOCK = {"p", "div", "section", "article", "header", "footer", "main", "nav",
          "aside", "form", "fieldset", "blockquote", "center", "address", "dl", "dt", "dd"}
_MARKUP = re.compile(r"([\\`*_\[\]<>#|])")


def _escape(text: str) -> str:
    """Text taken literally by Markdown: a page cannot make a link or a
    heading out of its words."""
    return _MARKUP.sub(r"\\\1", text)


class _HtmlToMarkdown(HTMLParser):
    """A small, forgiving HTML-to-Markdown converter (module docstring).
    It tolerates the unclosed tags real pages have: an end tag it does not
    expect is ignored."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._out: list[str] = []
        self._skip = 0
        self._in_head = False
        self._in_title = False
        self._pre = 0
        self._lists: list[list] = []  # [kind, counter]
        self._href: list[str] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._select: dict | None = None
        self._option: list[str] | None = None
        self._textarea: list[str] | None = None

    # -- output ---------------------------------------------------------

    def _emit(self, text: str) -> None:
        if self._cell is not None:
            self._cell.append(text)
        else:
            self._out.append(text)

    def _block(self) -> None:
        if self._pre or self._cell is not None:
            return
        self._out.append("\n\n")

    def markdown(self) -> str:
        if self._table is not None:
            self._end_table()
        text = "".join(self._out)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip() + "\n"

    # -- parsing --------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: (v or "") for k, v in attrs}
        if tag in _SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "head":
            self._in_head = True
        elif tag == "title":
            self._in_title = True
        elif self._in_head:
            return
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._block()
            self._emit("#" * int(tag[1]) + " ")
        elif tag in _BLOCK:
            self._block()
        elif tag == "br":
            self._emit("\n" if self._pre else "  \n")
        elif tag == "hr":
            self._block()
            self._emit("---")
            self._block()
        elif tag in ("b", "strong") and not self._pre:
            self._emit("**")
        elif tag in ("i", "em") and not self._pre:
            self._emit("*")
        elif tag == "pre":
            self._block()
            self._out.append("```text\n")
            self._pre += 1
        elif tag in ("ul", "ol"):
            self._block()
            self._lists.append([tag, 0])
        elif tag == "li":
            self._out.append("\n" + "  " * max(0, len(self._lists) - 1))
            if self._lists and self._lists[-1][0] == "ol":
                self._lists[-1][1] += 1
                self._emit(f"{self._lists[-1][1]}. ")
            else:
                self._emit("- ")
        elif tag == "a":
            self._href.append(attr.get("href", ""))
        elif tag == "img":
            alt = attr.get("alt", "").strip()
            if alt:
                self._emit(f"[image: {_escape(alt)}]")
        elif tag == "table":
            self._block()
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "input":
            self._emit(self._control(attr))
        elif tag == "select":
            self._select = {"options": [], "selected": None}
        elif tag == "option" and self._select is not None:
            self._option = []
            if "selected" in attr:
                self._select["selected"] = len(self._select["options"])
        elif tag == "textarea":
            self._textarea = []

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag == "head":
            self._in_head = False
        elif tag == "title":
            self._in_title = False
        elif self._in_head:
            return
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6") or tag in _BLOCK:
            self._block()
        elif tag in ("b", "strong") and not self._pre:
            self._emit("**")
        elif tag in ("i", "em") and not self._pre:
            self._emit("*")
        elif tag == "pre" and self._pre:
            self._pre -= 1
            self._out.append("\n```")
            self._block()
        elif tag in ("ul", "ol") and self._lists:
            self._lists.pop()
            self._block()
        elif tag == "a" and self._href:
            href = self._href.pop()
            if href and not href.startswith(("#", "javascript:")):
                self._emit(f" ({_escape(href)})" if not self._pre else f" ({href})")
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self._end_table()
        elif tag == "option" and self._option is not None and self._select is not None:
            self._select["options"].append(" ".join("".join(self._option).split()))
            self._option = None
        elif tag == "select" and self._select is not None:
            options, chosen = self._select["options"], self._select["selected"]
            shown = options[chosen if chosen is not None else 0] if options else ""
            self._select = None
            self._emit(f"[{shown if self._pre else _escape(shown)} v]")
        elif tag == "textarea" and self._textarea is not None:
            body = "".join(self._textarea).strip()
            self._textarea = None
            self._emit(f"[{body or '________'}]" if self._pre else f"[{_escape(body) or '________'}]")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_title:
            self.title += data
            return
        if self._in_head:
            return
        if self._option is not None:
            self._option.append(data)
            return
        if self._textarea is not None:
            self._textarea.append(data)
            return
        if self._pre:
            self._out.append(data)
            return
        text = re.sub(r"\s+", " ", data)
        if not text.strip() and (not self._out or self._out[-1].endswith(("\n", " "))):
            return
        self._emit(_escape(text))

    # -- pieces ---------------------------------------------------------

    def _control(self, attr: dict[str, str]) -> str:
        kind = attr.get("type", "text").lower()
        value = attr.get("value", "")
        if kind in ("hidden", "file", "image"):
            return ""
        if kind in ("button", "submit", "reset"):
            return f"[ {value or kind} ]"
        if kind == "checkbox":
            return "[x]" if "checked" in attr else "[ ]"
        if kind == "radio":
            return "(*)" if "checked" in attr else "( )"
        shown = value or "_" * 8
        return f"[{shown}]" if self._pre else f"[{_escape(shown)}]"

    def _end_table(self) -> None:
        rows, self._table = self._table or [], None
        if not rows:
            return
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        cells = [[cell.replace("|", "\\|") for cell in row] for row in rows]
        lines = ["| " + " | ".join(cells[0]) + " |", "|" + " --- |" * width]
        lines += ["| " + " | ".join(row) + " |" for row in cells[1:]]
        self._out.append("\n\n" + "\n".join(lines) + "\n\n")
