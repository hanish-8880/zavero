"""Learn a new app or goal from its official help pages and save it as a skill (skills.py).

Read-only: plain HTTP GETs of public help pages (no logins, no forms, no clicking), text only,
size-capped. Muse Spark suggests the official pages, then turns what was read into a skill file.
"""
import re
import urllib.request
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlparse

from zavero import config, skills
from zavero.reminders import extract_json

MAX_BYTES = 1_500_000
MAX_TEXT = 6000  # characters kept per page
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Zavero/0.9 (read-only help reader)"

SOURCES_SYSTEM = (
    "The user wants help with: {goal}. Open window title: {title}. List 2-4 OFFICIAL help / documentation "
    "pages (the maker's own help centre, docs or support site, or an official government page) that a "
    "beginner should read for this. Only https URLs you are confident exist. Reply with ONLY JSON: "
    '{"name": "short skill name", "triggers": ["2-6 lowercase words/phrases people say"], '
    '"apps": ["words from the app\'s window title, or empty"], "urls": ["https://..."]}'
)
WRITE_SYSTEM = (
    "Write a skill file body (markdown, English) that helps guide a complete beginner with: {goal}. Use ONLY "
    "the help-page text below plus well-known facts; prefer the current screen and button names from the "
    "pages. Sections, each 3-8 short bullet points: '## Screen names' (main areas, menus, buttons as labelled "
    "now), '## Shortcuts', '## Good beginner choices' (which option to pick and why), '## Common mistakes' "
    "(and the fix), '## Steps that need approval' (paying, publishing, submitting, sharing personal data). "
    "Max 1800 characters. No preamble."
)


class _Text(HTMLParser):
    """Visible text of an HTML page, without scripts, styles and navigation."""

    SKIP = {"script", "style", "noscript", "nav", "footer", "header", "svg"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs) -> None:
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data) -> None:
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    return re.sub(r"\s+", " ", " ".join(p.parts)).strip()


def fetch(url: str, timeout: float = 12) -> str:
    """Read-only GET of a public https page; returns its visible text (capped), or '' on any problem."""
    if urlparse(url).scheme != "https":
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if "html" not in r.headers.get("Content-Type", "html"):
                return ""
            raw = r.read(MAX_BYTES)
        return html_to_text(raw.decode("utf-8", "replace"))[:MAX_TEXT]
    except Exception as e:  # noqa: BLE001 - a missing page just isn't used
        print(f"[research] {url}: {type(e).__name__}: {e}")
        return ""


def _spark(system: str, text: str) -> str:
    resp = config.client().responses.create(model=config.MODEL_SPARK, reasoning=config.REASONING,
                                            instructions=system, input=text)
    return resp.output_text or ""


def learn(goal: str, window_title: str = "") -> skills.Skill | None:
    """Research the goal and save a new skill file. None if nothing useful could be read."""
    plan = extract_json(_spark(SOURCES_SYSTEM.replace("{goal}", goal).replace("{title}", window_title or "-"),
                               goal))
    urls = [u for u in plan.get("urls", []) if isinstance(u, str)][:4]
    pages = [(u, fetch(u)) for u in urls]
    pages = [(u, t) for u, t in pages if len(t) > 300]
    if not pages:
        return None
    reading = "\n\n".join(f"SOURCE {u}\n{t}" for u, t in pages)
    body = _spark(WRITE_SYSTEM.replace("{goal}", goal), reading).strip()
    if len(body) < 80:
        return None
    name = str(plan.get("name") or goal)[:60]
    skill = skills.Skill(slug=skills.slugify(name), name=name,
                         triggers=[str(t).lower() for t in plan.get("triggers", [])][:6],
                         apps=[str(a).lower() for a in plan.get("apps", [])][:3],
                         updated=date.today(), sources=[u for u, _ in pages],
                         body=body + "\n\n## Sources\n" + "\n".join(f"- {u}" for u, _ in pages))
    old = skills.DIR / f"{skill.slug}.md"
    if old.exists():  # refreshing: keep what users taught it ("## Learned ..." sections)
        learned = re.findall(r"(## Learned .*?)(?=\n## (?!Learned)|\Z)", old.read_text(encoding="utf-8"), re.S)
        if learned:
            skill.body += "\n\n" + "\n\n".join(x.strip() for x in learned)
    skills.save(skill)
    return skill
