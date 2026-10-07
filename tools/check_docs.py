"""Check active documentation links, anchors and source-backed snippets."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
FENCES = re.compile(r"^\x60{3}[^\n]*\n.*?^\x60{3}[ \t]*$", re.M | re.S)
LINKS = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SNIPPETS = re.compile(r"<!-- source: ([^\n]+?) -->\s*\n\x60{3}[^\n]*\n(.*?)\n\x60{3}", re.S)


def anchors(text):
    counts = Counter()
    result = set()
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", FENCES.sub("", text), re.M):
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        result.add(slug if not counts[slug] else f"{slug}-{counts[slug]}")
        counts[slug] += 1
    return result


def main():
    documents = [ROOT / "README.md", ROOT / "AGENTS.md", ROOT / "examples/quickstart/README.md",
                 *sorted((ROOT / "docs").glob("*.md")), ROOT / "docs/archive/README.md"]
    errors = []
    links = snippets = 0
    for document in documents:
        text = document.read_text(encoding="utf-8")
        for relative, snippet in SNIPPETS.findall(text):
            source = document.parent / relative
            if not source.is_file() or source.read_text(encoding="utf-8").strip() != snippet.strip():
                errors.append(f"{document.relative_to(ROOT)}: stale source snippet {relative}")
            snippets += 1
        for target in LINKS.findall(FENCES.sub("", text)):
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc:
                continue
            path = (document.parent / unquote(parsed.path)).resolve() if parsed.path else document
            if not path.exists():
                errors.append(f"{document.relative_to(ROOT)}: missing link {target}")
            elif parsed.fragment and path.suffix == ".md":
                if unquote(parsed.fragment) not in anchors(path.read_text(encoding="utf-8")):
                    errors.append(f"{document.relative_to(ROOT)}: missing heading {target}")
            links += 1
    if not links or not snippets:
        errors.append("No links or executable snippets found")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Documentation PASS: {len(documents)} documents, {links} local links, {snippets} snippets")


if __name__ == "__main__":
    main()
