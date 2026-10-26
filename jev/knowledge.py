"""The knowledge library: game facts the planner looked up on the Factorio wiki, and notes it wrote about the concepts
it kept needing (<library>/knowledge/, version controlled with the lessons). Every lookup is counted per wiki page;
from the 4th lookup of one page the planner is asked to write a note (save_note), and after that a lookup gives the
note first. The wiki's text is CC BY-NC-SA and this repo is MIT, so the notes are its own words with a link back,
and the pages themselves are cached outside the repo (~/.cache/jev/wiki). The user: "I would love if the serf started
building a knowledge library, writing to some files (version controlled) when it requests info on a specific game
concept more than 3 times"."""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path

from .library import lib_dir

API = "https://wiki.factorio.com/api.php"
PAGE = "https://wiki.factorio.com/"
AGENT = "factorio-serf (github.com/stirby/factorio-serf)"
CACHE = Path.home() / ".cache" / "jev" / "wiki"
CACHE_SECS = 7 * 24 * 3600
NOTE_AFTER = 3  # a note is due once a page has been looked up more than this many times
TEXT_MAX = 5000
STOP = {"how", "do", "does", "what", "whats", "what's", "is", "are", "the", "a", "an", "why", "when", "where", "work",
        "works", "working", "on", "in", "of", "to", "for", "with", "can", "i", "you", "it", "use", "using", "much",
        "many", "about"}
TRANSLATION = re.compile(r"/[a-z]{2}(?:-[a-z]+)?$")  # Roboport/de, Roboport/pt-br


def knowledge_dir() -> Path:
    return lib_dir() / "knowledge"


def _get(**params) -> dict:
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def resolve(query: str) -> tuple[str | None, list[str]]:
    """The wiki page for a concept: the page of that title (redirects followed), else the best search hit; with the
    other hits, English pages only."""
    q = " ".join(str(query).split())[:120]
    if not q:
        return None, []
    d = _get(action="query", titles=q, redirects=1)
    for p in (d.get("query", {}).get("pages") or {}).values():
        if "missing" not in p and "invalid" not in p:
            return p["title"], []
    q = " ".join(w for w in q.split() if w.lower().strip("?,.") not in STOP) or q  # "how do fluid wagons work"
    hits = _get(action="query", list="search", srsearch=q, srlimit=10).get("query", {}).get("search") or []
    titles = [h["title"] for h in hits if not TRANSLATION.search(h["title"])]
    if titles:
        return titles[0], titles[1:5]
    # the search wants every word: try the phrases in it ("electric mining drill on vulcanus": Electric mining
    # drill, then Vulcanus), longest first
    words = q.split()[:8]
    phrases = sorted({" ".join(words[i:j]) for i in range(len(words)) for j in range(i + 1, len(words) + 1)},
                     key=lambda x: (-len(x.split()), q.find(x)))
    phrases = [x for ph in phrases for x in ([ph, ph[:-1]] if ph.endswith("s") else [ph])]  # wagons: Fluid wagon
    d = _get(action="query", titles="|".join(phrases[:50]), redirects=1)
    found = {p["title"] for p in (d.get("query", {}).get("pages") or {}).values() if "missing" not in p
             and "invalid" not in p}
    norm = {n["from"]: n["to"] for n in d.get("query", {}).get("normalized") or []}
    redir = {n["from"]: n["to"] for n in d.get("query", {}).get("redirects") or []}
    ordered = []
    for ph in phrases:
        t = norm.get(ph, ph)
        t = redir.get(t, t)
        if t in found and t not in ordered:
            ordered.append(t)
    return (ordered[0], ordered[1:5]) if ordered else (None, [])


SKIP_CLASSES = ("navbox", "mw-editsection", "languages", "infobox-edit-link", "mw-references-wrap", "reference")
VOID = {"img", "br", "hr", "meta", "link", "input", "wbr", "source", "area", "col"}
ICON = re.compile(r"/images/(?:thumb/)?([^/]+?)\.(?:png|gif|jpg)")


class _Text(HTMLParser):
    """A wiki page's HTML as plain text: a table row on one line ("Construction area | 110×110 tiles"), item icons
    by name (recipes are icons with counts), headings as "## ", no navigation boxes or edit links."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.stack, self.rows = [], 0, [], []

    def sink(self) -> list:
        return self.rows[-1][-1] if self.rows and self.rows[-1] else self.out

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if tag in VOID:
            if self.skip:
                return
            if tag == "img" and any("factorio-icon" in c for _, cs, _ in self.stack for c in cs):
                m = ICON.search(a.get("src") or "")
                if m:
                    self.sink().append(" " + urllib.parse.unquote(m.group(1)).replace("_", " ") + " ")
            elif tag == "br":
                self.sink().append(" ")
            return
        skip = tag in ("script", "style", "sup") or any(c in SKIP_CLASSES for c in cls)
        self.stack.append((tag, cls, skip))
        if skip:
            self.skip += 1
        if self.skip:
            return
        if tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th") and self.rows:
            self.rows[-1].append([])
        elif tag in ("h2", "h3", "h4"):
            self.sink().append("\n\n## ")
        elif tag in ("p", "div", "ul", "ol", "table"):
            self.sink().append("\n")
        elif tag == "li":
            self.sink().append("\n- ")

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        while self.stack:
            t, _, skip = self.stack.pop()
            if skip:
                self.skip -= 1
            elif t == "tr" and self.rows:
                cells = [c for c in (re.sub(r"\s+", " ", "".join(c)).strip() for c in self.rows.pop()) if c]
                if cells:
                    self.sink().append("\n" + " | ".join(cells) + "\n")
            if t == tag:
                break
        if not self.skip and tag in ("p", "h2", "h3", "h4"):
            self.sink().append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.sink().append(data)


def html_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    t = re.sub(r"[ \t ]+", " ", "".join(p.out))
    t = re.sub(r" *\n *", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80] or "page"


def page(title: str, section: str | None = None) -> tuple[str, list[str]]:
    """A page's text (its top part with the infobox, or one section by name) and its section names; cached a week."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{_slug(title)}.json"
    try:
        d = json.loads(f.read_text())
        if time.time() - d.get("t", 0) > CACHE_SECS:
            d = None
    except (OSError, ValueError):
        d = None
    if not d:
        p = _get(action="parse", page=title, prop="text|sections", redirects=1, disabletoc=1).get("parse") or {}
        d = {"t": time.time(), "html": (p.get("text") or {}).get("*", ""),
             "sections": [(s["index"], s["line"]) for s in p.get("sections") or []]}
        f.write_text(json.dumps(d))
    names = [html_text(n) for _, n in d["sections"]]
    text = html_text(d["html"])
    want = (section or "").strip().lower()
    hit = next((n for n in names if want and want in n.lower()), None)
    parts = re.split(r"\n## ", "\n" + text)
    if hit:
        text = next((p for p in parts if p.strip().lower().startswith(hit.lower())), text)
        text = "## " + text.strip()
    else:
        text = parts[0].strip() or text
        if want:
            text = f"(no section named {section!r}: the page's top part)\n\n" + text
    return text, names


def _ledger_path() -> Path:
    return knowledge_dir() / "lookups.json"


def _ledger() -> dict:
    try:
        return json.loads(_ledger_path().read_text())
    except (OSError, ValueError):
        return {}


def _note_path(title: str) -> Path:
    return knowledge_dir() / f"{_slug(title)}.md"


def note(title: str) -> str | None:
    p = _note_path(title)
    return p.read_text() if p.exists() else None


def lookup(query: str, section: str | None = None, fresh: bool = False) -> str:
    """The planner's wiki tool: counts the lookup, gives its note when there is one (fresh: the page anyway), else
    the page; asks for a note once the page has been looked up more than NOTE_AFTER times."""
    try:
        title, others = resolve(query)
    except Exception as e:  # noqa: BLE001
        return f"the wiki isn't reachable ({e!r}); go on from what you know"
    if not title:
        return f"no wiki page for {query!r}; try the item's or building's own name"
    led = _ledger()
    r = led.setdefault(title, {"count": 0, "queries": []})
    r["count"] += 1
    r["last"] = time.strftime("%Y-%m-%d")
    if query not in r["queries"]:
        r["queries"] = (r["queries"] + [query])[-5:]
    knowledge_dir().mkdir(parents=True, exist_ok=True)
    _ledger_path().write_text(json.dumps(led, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    url = PAGE + urllib.parse.quote(title.replace(" ", "_"))
    head = f"{title} ({url}; lookup #{r['count']})"
    mine = note(title)
    if mine and not fresh:
        return f"{head}\nYour note (fresh=true for the wiki page itself):\n\n{mine}"
    try:
        text, names = page(title, section)
    except Exception as e:  # noqa: BLE001
        return f"{head}\nthe page didn't load ({e!r})"
    if len(text) > TEXT_MAX:
        text = text[:TEXT_MAX] + " [...]"
    out = [head, text]
    if names:
        out.append("Sections (ask with section=...): " + ", ".join(names))
    if others:
        out.append("Other pages: " + ", ".join(others))
    if r["count"] > NOTE_AFTER and not mine:
        out.append(f"You've looked up {title} {r['count']} times. When you've used it, save what you needed as a note "
                   f"with save_note(title=\"{title}\", text=...): the facts that mattered for this game (Factorio 2.0 "
                   "with Space Age) in your own words, short, not copied from the page.")
    return "\n\n".join(out)


def save_note(title: str, text: str) -> str:
    """A note about a wiki page the planner keeps looking up, in its own words: <library>/knowledge/<page>.md."""
    led = _ledger()
    title = str(title).strip()
    if title not in led:
        try:
            title = resolve(title)[0] or title
        except Exception:  # noqa: BLE001
            pass
    n = led.get(title, {}).get("count", 0)
    if n <= NOTE_AFTER:
        return (f"not saved: notes are for pages you keep needing (more than {NOTE_AFTER} lookups); {title!r} has "
                f"{n}")
    text = str(text).strip()
    if not 40 <= len(text) <= 4000:
        return "not saved: a note is 40 to 4000 characters"
    try:
        src, _ = page(title)
        m = SequenceMatcher(None, src, text, autojunk=False).find_longest_match(0, len(src), 0, len(text))
        if m.size > 160:
            return "not saved: it copies the page (the wiki's text isn't ours to put in the repo); write it in your own words"
    except Exception:  # noqa: BLE001
        pass
    url = PAGE + urllib.parse.quote(title.replace(" ", "_"))
    p = _note_path(title)
    p.write_text(f"# {title}\n\nSource: {url} (looked up {n} times; note written {time.strftime('%Y-%m-%d')}, "
                 f"Factorio 2.0 with Space Age)\n\n{text}\n")
    return f"saved {p.relative_to(lib_dir())}; later lookups give it first"


def notes_index() -> list[str]:
    """The pages the planner has notes on, for its prompt."""
    d = knowledge_dir()
    out = []
    for p in sorted(d.glob("*.md")) if d.exists() else []:
        first = p.read_text().splitlines()[0] if p.stat().st_size else ""
        out.append(first.lstrip("# ").strip() or p.stem)
    return out
