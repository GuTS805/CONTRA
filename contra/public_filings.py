"""A real-company example: exact excerpts from Infosys's public SEC filings.

The synthetic scenarios show known expected outcomes. This example shows the same pipeline on
issuer text: each excerpt is a contiguous span of a filing on SEC EDGAR, stored with its form,
filing date and URL. Tone tags come from the same word-list heuristic as automatic uploads.

    SEC_USER_AGENT="Your Name you@example.com" python -m contra.public_filings

downloads every cited filing and checks that each excerpt still appears in it exactly.
SEC asks automated clients to identify themselves, hence the required user agent.
"""
from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

from .live import lexicon_tone

FIXTURE = Path(__file__).resolve().parent.parent / "data" / "fixtures" / "public_filings.json"
BLOCK_TAGS = {"p", "div", "tr", "br", "li", "h1", "h2", "h3"}
TONE_VALUES = {"POSITIVE": 1, "NEGATIVE": -1, "NEUTRAL_OR_MIXED": 0}


@lru_cache(maxsize=1)
def example() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _tone_fields(item: dict) -> dict:
    """The shipped model tone with its verified quote, or the word-list tone when none was classified."""
    if "tone_label" in item:
        return {"tone": TONE_VALUES[item["tone_label"]], "tone_source": "MODEL_VERIFIED",
                "tone_quote": item["tone_quote"], "tone_model": item["tone_model"]}
    return {"tone": lexicon_tone(item["excerpt"]), "tone_source": "LEXICON_HEURISTIC"}


def documents() -> list[dict]:
    """The excerpts as filing documents, in the same shape as user uploads."""
    spec = example()
    out = []
    for item in spec["excerpts"]:
        text = item["excerpt"]
        out.append({"id": item["id"], "document_id": "DOC-" + item["id"][2:], "ticker": spec["ticker"],
                    "title": item["title"], "published_at": item["published_at"], "excerpt": text,
                    "char_start": 0, "char_end": len(text),
                    **_tone_fields(item), "mode": "PUBLIC_FILING",
                    "source_type": "sec_filing_excerpt", "form": item["form"], "source_uri": item["source_uri"],
                    "source_hash": "sha256:" + sha256(text.encode()).hexdigest()})
    return out


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_text(markup: str) -> str:
    """Visible text with all whitespace collapsed to single spaces."""
    parser = _Text()
    parser.feed(markup)
    return re.sub(r"\s+", " ", "".join(parser.parts).replace("\xa0", " ")).strip()


def verify(user_agent: str, fetch=None) -> list[str]:
    """Return one problem per excerpt that no longer appears exactly in its cited filing."""
    def download(url):
        with urlopen(Request(url, headers={"User-Agent": user_agent}), timeout=60) as response:
            return response.read().decode("utf-8", errors="replace")
    fetch = fetch or download
    texts, problems = {}, []
    for item in example()["excerpts"]:
        url = item["source_uri"]
        if url not in texts:
            texts[url] = html_text(fetch(url))
        if item["excerpt"] not in texts[url]:
            problems.append(f"{item['id']}: not found in {url}")
    return problems


def classify(write: bool = True) -> list[str]:
    """Classify every excerpt's tone with the configured model and ship the verified result in the fixture."""
    from . import llm
    from .settings import load_env
    load_env()
    if not llm.configured():
        raise SystemExit("Set OPENAI_API_KEY and CONTRA_LLM=1 in .env first.")
    spec = json.loads(FIXTURE.read_text(encoding="utf-8"))
    lines = []
    for item in spec["excerpts"]:
        verdict = llm.classify_tone(item["excerpt"])
        item.update(tone_label=verdict["label"], tone_quote=verdict["quote"], tone_model=verdict["model_version"])
        lines.append(f"{item['id']}: {verdict['label']} | word list {lexicon_tone(item['excerpt']):+.1f} | {item['title']}")
    if write:
        FIXTURE.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return lines


def main() -> None:
    if "--tone" in sys.argv:
        for line in classify():
            print(line)
        return
    agent = os.environ.get("SEC_USER_AGENT", "").strip()
    if "@" not in agent:
        raise SystemExit('Set SEC_USER_AGENT to a name and contact email, e.g. "Jane Doe jane@example.com".')
    problems = verify(agent)
    for problem in problems:
        print(problem)
    count = len(example()["excerpts"])
    print(f"{count - len(problems)} of {count} excerpts match their SEC filings exactly.")
    if problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
