"""Skills: what Zavero knows about apps and goals, as plain markdown files in skills/*.md.

Nothing in the code is about one app or one field; all of that lives in these files. Format:

    ---
    name: Example App basics
    triggers: [example app, exampleapp]       # words in the user's goal
    apps: [Example App]                       # words in the window title
    updated: 2026-10-29
    sources: [https://help.example.com/start]
    ---
    ## Shortcuts
    ...

Zavero writes new skill files itself after reading official help pages (research.py), refreshes them
after 60 days, and appends what worked when a goal finishes.
"""
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from zavero import config

DIR = config.ROOT / "skills"
STALE_DAYS = 60
MAX_SKILLS, MAX_CHARS = 2, 2000  # per request: at most 2 skills, 2k characters each


@dataclass
class Skill:
    slug: str
    name: str
    triggers: list[str] = field(default_factory=list)
    apps: list[str] = field(default_factory=list)
    updated: date | None = None
    sources: list[str] = field(default_factory=list)
    body: str = ""

    @property
    def stale(self) -> bool:
        return self.updated is None or (date.today() - self.updated).days > STALE_DAYS


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:48] or "skill"


def _list(value: str) -> list[str]:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [v.strip().strip("'\"") for v in value.split(",") if v.strip()]


def parse(slug: str, text: str) -> Skill:
    """Read one skill file (simple 'key: value' frontmatter, no YAML library needed)."""
    meta, body = {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.split(" #")[0].strip()
        body = m.group(2)
    try:
        updated = date.fromisoformat(meta.get("updated", ""))
    except ValueError:
        updated = None
    return Skill(slug=slug, name=meta.get("name", slug), triggers=[t.lower() for t in _list(meta.get("triggers", ""))],
                 apps=[a.lower() for a in _list(meta.get("apps", ""))], updated=updated,
                 sources=_list(meta.get("sources", "")), body=body.strip())


def render(s: Skill) -> str:
    return (f"---\nname: {s.name}\ntriggers: [{', '.join(s.triggers)}]\napps: [{', '.join(s.apps)}]\n"
            f"updated: {(s.updated or date.today()).isoformat()}\nsources: [{', '.join(s.sources)}]\n---\n"
            f"{s.body.strip()}\n")


def load_all(folder: Path | None = None) -> list[Skill]:
    folder = folder or DIR
    if not folder.exists():
        return []
    return [parse(p.stem, p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.md"))]


def _score(s: Skill, text: str, title: str) -> int:
    t, w = text.lower(), title.lower()
    score = sum(3 for a in s.apps if a and a in w)  # the app that is open counts most
    score += sum(2 for k in s.triggers if k and re.search(rf"(?<!\w){re.escape(k)}(?!\w)", t))
    return score


def match(text: str, window_title: str = "", folder: Path | None = None) -> list[Skill]:
    """Skills for this goal / open window, best first (at most MAX_SKILLS)."""
    scored = [(_score(s, text, window_title), s) for s in load_all(folder)]
    return [s for sc, s in sorted(scored, key=lambda x: -x[0]) if sc > 0][:MAX_SKILLS]


def as_context(found: list[Skill]) -> str:
    """Skill text to send with a request (capped)."""
    return "\n\n".join(f"# Skill: {s.name}\n{s.body[:MAX_CHARS]}" for s in found)


def save(s: Skill, folder: Path | None = None) -> Path:
    folder = folder or DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{s.slug}.md"
    path.write_text(render(s), encoding="utf-8")
    return path


def append_learned(slug: str, lines: list[str], folder: Path | None = None) -> None:
    """After a goal: add what worked and fixes for mistakes, so the next user gets it right sooner."""
    lines = [ln.strip() for ln in lines if ln and ln.strip()]
    path = (folder or DIR) / f"{slug}.md"
    if not lines or not path.exists():
        return
    s = parse(slug, path.read_text(encoding="utf-8"))
    s.body = s.body.rstrip() + f"\n\n## Learned {date.today().isoformat()}\n" + "\n".join(f"- {ln}" for ln in lines)
    save(s, folder)
