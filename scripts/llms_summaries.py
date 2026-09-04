"""Check that every docs page has an ``html_meta`` description, and that it
was written for the page's current content.

The descriptions end up in ``llms.txt`` (see ``get_page_description`` in
sphinx-llm), where they tell an LLM which pages are worth fetching. Without
them, sphinx-llm falls back to truncating the first paragraph.

Usage:
    python scripts/llms_summaries.py            # check (used in CI)
    python scripts/llms_summaries.py --update   # accept the current content
"""

import hashlib
import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
LOCK = DOCS / "llms-summaries.lock"

MYST_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n\s*", re.DOTALL)
MYST_DESCRIPTION = re.compile(
    r"^[ \t]*html_meta:\n(?:[ \t]+.*\n)*?[ \t]+description:", re.MULTILINE
)
RST_META = re.compile(r"\A\.\. meta::\n(?:[ \t]+.*\n)*\s*")
RST_DESCRIPTION = re.compile(r"^[ \t]+:description:", re.MULTILINE)


def pages():
    for path in sorted(DOCS.rglob("*")):
        if path.suffix in (".md", ".rst") and not {
            "_build",
            "adr",
            "internal",
        } & set(path.parts):
            yield path


def split(path):
    """Return (metadata_block, body) for a docs page."""
    text = path.read_text(encoding="utf-8")
    pattern = RST_META if path.suffix == ".rst" else MYST_FRONTMATTER
    match = pattern.match(text)
    return (match.group(), text[match.end() :]) if match else ("", text)


def digest(body):
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def read_lock():
    if not LOCK.exists():
        return {}
    return dict(
        reversed(line.split("  ", 1))
        for line in LOCK.read_text(encoding="utf-8").splitlines()
        if line
    )


def main(update):
    locked, current, missing = read_lock(), {}, []
    for path in pages():
        meta, body = split(path)
        name = path.relative_to(DOCS).as_posix()
        pattern = (
            RST_DESCRIPTION if path.suffix == ".rst" else MYST_DESCRIPTION
        )
        if not pattern.search(meta):
            missing.append(name)
        current[name] = digest(body)

    if update:
        LOCK.write_text(
            "".join(f"{h}  {n}\n" for n, h in sorted(current.items())),
            encoding="utf-8",
        )
        print(f"Wrote {LOCK.relative_to(DOCS.parent)} ({len(current)} pages).")
        return 0

    stale = sorted(
        n for n, h in current.items() if n in locked and locked[n] != h
    )
    unlocked = sorted(current.keys() - locked.keys() - set(missing))
    removed = sorted(locked.keys() - current.keys())

    for label, names in (
        ("have no html_meta description", missing),
        ("changed since their description was written", stale),
        ("are not in the lockfile", unlocked),
        ("are in the lockfile but no longer exist", removed),
    ):
        if names:
            print(f"\nThese pages {label}:", file=sys.stderr)
            for name in names:
                print(f"  docs/{name}", file=sys.stderr)

    if missing or stale or unlocked or removed:
        print(
            "\nReview the 'description:' of each page listed above, then run\n"
            "'make sync-llms-summaries' to record the current content.",
            file=sys.stderr,
        )
        return 1

    print(f"All {len(current)} docs pages have an up-to-date description.")
    return 0


if __name__ == "__main__":
    sys.exit(main(update="--update" in sys.argv[1:]))
