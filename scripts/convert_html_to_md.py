from __future__ import annotations

import sys
from pathlib import Path

from bs4 import BeautifulSoup
from markdownify import markdownify

SRC_ROOT = Path("external_docs/reference_html/doc.sagemath.org/html/en/reference")
DEST_ROOT = Path("docs/reference_md")


def clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find(id="furo-main-content")
    if main is not None:
        soup = BeautifulSoup(str(main), "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    return str(soup)


def convert_file(html_path: Path) -> None:
    relative = html_path.relative_to(SRC_ROOT)
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

    source_url = f"https://doc.sagemath.org/html/en/reference/{relative.as_posix()}"
    header = f"<!-- Source: {source_url} -->\n\n"
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
