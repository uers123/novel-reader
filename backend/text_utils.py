from __future__ import annotations

import re


def split_sentences(text: str) -> list[str]:
    pieces = re.split(r"(?<=[。！？!?；;])\s*|\n+", text or "")
    sentences = [p.strip() for p in pieces if len(p.strip()) > 0]
    if not sentences and text:
        sentences = [text.strip()]
    return sentences


def chunk_text(text: str, max_chars: int = 2200) -> list[str]:
    paragraphs = [p for p in re.split(r"\n{2,}", text or "") if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 <= max_chars:
            current = f"{current}\n\n{paragraph}".strip()
        else:
            if current:
                chunks.append(current)
            if len(paragraph) <= max_chars:
                current = paragraph
            else:
                for i in range(0, len(paragraph), max_chars):
                    chunks.append(paragraph[i : i + max_chars])
                current = ""
    if current:
        chunks.append(current)
    return chunks or ([text] if text else [])
