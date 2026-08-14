from __future__ import annotations

import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup
from markdownify import markdownify

SRC_ROOT = Path("external_docs/reference_html/doc.sagemath.org/html/en/reference")
DEST_ROOT = Path("docs/reference_md")

ALLOWED_PAGES = {
    "index.html",
    "search.html",
    "plotting/index.html",
    "plot3d/index.html",
    "calculus/index.html",
    "rings/index.html",
    "stats/index.html",
}


def clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find(id="furo-main-content")
    if main is not None:
        soup = BeautifulSoup(str(main), "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    return str(soup)


DOC_BASE = "https://doc.sagemath.org/html/en/reference"


def _absolutize_links(markdown: str, section: str) -> str:
    """Rewrite relative links to the upstream documentation they came from."""

    def fix(match: re.Match[str]) -> str:
        label, target = match.group(1), match.group(2)
        if target.startswith(("http://", "https://", "#", "mailto:")):
            return match.group(0)
        path, _, fragment = target.partition("#")
        if not path:
            return match.group(0)
        prefix = f"{section}/" if section not in {"", "."} else ""
        url = f"{DOC_BASE}/{prefix}{path}"
        return f"[{label}]({url}#{fragment})" if fragment else f"[{label}]({url})"

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", fix, markdown)


def convert_file(html_path: Path) -> None:
    relative = html_path.relative_to(SRC_ROOT)
    if str(relative).replace("\\", "/") not in ALLOWED_PAGES:
        return
    dest_path = DEST_ROOT / relative.with_suffix(".md")
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    html = html_path.read_text(encoding="utf-8", errors="ignore")
    cleaned = clean_html(html)
    markdown = markdownify(cleaned, heading_style="ATX")
    lines = [line.rstrip() for line in markdown.splitlines()]
    trimmed = []
    blank_streak = 0
    for line in lines:
        if line:
            blank_streak = 0
            trimmed.append(line)
        else:
            blank_streak += 1
            if blank_streak <= 1:
                trimmed.append(line)
    markdown = "\n".join(trimmed).strip() + "\n"

    # Point every link at doc.sagemath.org. Left relative, they resolve against
    # this repository and 404 -- 210 of them did, in files nothing links to, so a
    # reader who found the page could not follow a single reference out of it.
    markdown = _absolutize_links(markdown, relative.parent.as_posix())

    source_url = f"https://doc.sagemath.org/html/en/reference/{relative.as_posix()}"
    header = (
        f"<!-- Source: {source_url} -->\n"
        "<!-- Snapshot of the SageMath reference manual. Links point upstream; "
        "the live page is authoritative. -->\n\n"
    )
    dest_path.write_text(header + markdown, encoding="utf-8")


def main() -> int:
    if not SRC_ROOT.exists():
        print(f"Source directory {SRC_ROOT} not found", file=sys.stderr)
        return 1
    for html_file in SRC_ROOT.rglob("*.html"):
        convert_file(html_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
