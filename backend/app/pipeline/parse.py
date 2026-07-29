"""Parsing layer: raw upload (.txt / .epub) -> ordered list of chapters.

A ``Chapter`` is just a title + body text. Chapter detection for plain text uses
common Chinese and English heading patterns; if none are found the whole text is
treated as a single chapter. EPUB parsing uses ebooklib + BeautifulSoup and maps
each spine document to a chapter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Chapter:
    index: int
    title: str
    text: str

    @property
    def id(self) -> str:
        return f"ch{self.index:04d}"


@dataclass
class ParsedNovel:
    title: str
    chapters: list[Chapter] = field(default_factory=list)

    @property
    def total_chars(self) -> int:
        return sum(len(c.text) for c in self.chapters)

    @property
    def chapter_titles(self) -> dict[str, str]:
        """Map chapter id (e.g. 'ch0001') -> human title (e.g. '第一回')."""
        return {c.id: c.title for c in self.chapters}


class ParseError(Exception):
    """Raised when an upload cannot be parsed into text."""


# Chinese: 第一章 / 第1章 / 第一回 / 第 100 节 ; English: Chapter 1 / CHAPTER I
_CHAPTER_PATTERNS = [
    re.compile(r"^\s*第\s*[0-9零一二三四五六七八九十百千两]+\s*[章回节卷部篇].*$"),
    re.compile(r"^\s*(?:chapter|CHAPTER|Chapter)\s+[0-9IVXLCivxlc]+.*$"),
    re.compile(r"^\s*(?:序章|楔子|尾声|后记|前言|引子|终章)\s*$"),
]


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 40:
        return False
    return any(p.match(stripped) for p in _CHAPTER_PATTERNS)


def parse_txt(text: str, fallback_title: str) -> ParsedNovel:
    """Split plain text into chapters by heading heuristics."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    chapters: list[Chapter] = []
    cur_title: str | None = None
    cur_lines: list[str] = []
    idx = 0

    def flush() -> None:
        nonlocal idx, cur_title, cur_lines
        body = "\n".join(cur_lines).strip()
        if body or cur_title:
            idx += 1
            chapters.append(
                Chapter(index=idx, title=(cur_title or f"第{idx}章").strip(), text=body)
            )
        cur_lines = []

    for line in lines:
        if _looks_like_heading(line):
            flush()
            cur_title = line.strip()
        else:
            cur_lines.append(line)
    flush()

    # No headings found -> single chapter with all content.
    if not chapters or (len(chapters) == 1 and not chapters[0].text and cur_title is None):
        body = text.strip()
        if not body:
            raise ParseError("文件内容为空，无法解析。")
        return ParsedNovel(title=fallback_title, chapters=[Chapter(1, fallback_title, body)])

    # Drop leading empty chapter that can appear before the first heading.
    chapters = [c for c in chapters if c.text.strip()]
    if not chapters:
        raise ParseError("未能从文本中提取到任何正文内容。")
    # Re-index sequentially.
    for i, c in enumerate(chapters, start=1):
        c.index = i
    return ParsedNovel(title=fallback_title, chapters=chapters)


def parse_epub(path: Path, fallback_title: str) -> ParsedNovel:
    """Parse an EPUB file into chapters using ebooklib."""
    try:
        import ebooklib  # type: ignore
        from ebooklib import epub  # type: ignore
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise ParseError(f"缺少 EPUB 解析依赖: {exc}") from exc

    try:
        book = epub.read_epub(str(path))
    except Exception as exc:  # noqa: BLE001 - surface a clean error
        raise ParseError(f"EPUB 解析失败: {exc}") from exc

    title = fallback_title
    meta_title = book.get_metadata("DC", "title")
    if meta_title:
        title = str(meta_title[0][0]) or fallback_title

    chapters: list[Chapter] = []
    idx = 0
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        html = item.get_content()
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n").strip()
        if not text:
            continue
        # Prefer a heading tag for the chapter title.
        heading = soup.find(["h1", "h2", "h3", "title"])
        ch_title = heading.get_text().strip() if heading else ""
        idx += 1
        if not ch_title:
            ch_title = f"第{idx}章"
        chapters.append(Chapter(index=idx, title=ch_title, text=text))

    if not chapters:
        raise ParseError("EPUB 中未找到任何正文文档。")
    return ParsedNovel(title=title, chapters=chapters)


def parse_upload(path: Path, original_filename: str) -> ParsedNovel:
    """Dispatch to the right parser based on file extension."""
    ext = Path(original_filename).suffix.lower()
    fallback_title = Path(original_filename).stem or "未命名作品"
    if ext == ".txt":
        raw = path.read_bytes()
        text = _decode_text(raw)
        return parse_txt(text, fallback_title)
    if ext == ".epub":
        return parse_epub(path, fallback_title)
    raise ParseError(f"不支持的文件类型: {ext}")


def _decode_text(raw: bytes) -> str:
    """Best-effort decode of a text file (utf-8 / utf-8-sig / gb18030)."""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    # Last resort: replace undecodable bytes.
    return raw.decode("utf-8", errors="replace")
