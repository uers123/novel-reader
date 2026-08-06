from __future__ import annotations

import math
import re
import shutil
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from storage_utils import read_json, write_json
from text_utils import split_sentences

def _read_file_with_fallback_encoding(path: str) -> str:
    """Read a text file trying multiple encodings (UTF-8 → GBK → GB2312 → ascii)."""
    encodings = ["utf-8", "gbk", "gb2312", "utf-16", "ascii"]
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    # Last resort: read with errors='replace'
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


class NovelManager:
    def __init__(self, storage_dir: Path, crawler_dir: Path | None = None):
        self.storage_dir = storage_dir
        self.crawler_dir = crawler_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.storage_dir / "_index.json"
        self._index: dict[str, dict[str, Any]] = read_json(self.index_file, {})
        self._lock = threading.RLock()

    def _save_index(self) -> None:
        write_json(self.index_file, self._index)

    def _novel_path(self, novel_id: str) -> Path:
        return self.storage_dir / novel_id

    def _chapters_file(self, novel_id: str) -> Path:
        return self._novel_path(novel_id) / "chapters.json"

    def _crawl_file(self, novel_id: str) -> Path:
        return self._novel_path(novel_id) / "crawl_status.json"

    def _read_chapters(self, novel_id: str) -> list[dict[str, Any]]:
        return read_json(self._chapters_file(novel_id), [])

    def _write_chapters(self, novel_id: str, chapters: list[dict[str, Any]]) -> None:
        write_json(self._chapters_file(novel_id), chapters)

    def _read_crawl_status(self, novel_id: str) -> dict[str, Any]:
        chapters = self._read_chapters(novel_id)
        return read_json(
            self._crawl_file(novel_id),
            {
                "novelId": novel_id,
                "total": len(chapters),
                "cached": 0,
                "prefetchTarget": 0,
                "prefetched": 0,
                "inProgress": False,
                "failed": [],
                "updatedAt": None,
            },
        )

    def _write_crawl_status(self, novel_id: str, status: dict[str, Any]) -> None:
        status["updatedAt"] = datetime.now().isoformat()
        write_json(self._crawl_file(novel_id), status)

    @staticmethod
    def _progress_percent(progress: Any, total: Any) -> int:
        """Convert chapter-index progress (0-based) into a 0-100 percentage.

        progress is the index of the chapter the reader is on. For a book with
        total chapters, the percentage is progress / (total - 1); for a single-
        chapter book any nonzero progress means "finished".
        """
        try:
            progress = int(progress)
            total = int(total)
        except (TypeError, ValueError):
            return 0
        if total <= 1:
            return 100 if progress > 0 else 0
        return max(0, min(100, round(progress / (total - 1) * 100)))

    def list_all(self) -> list[dict[str, Any]]:
        with self._lock:
            novels = []
            for novel_id, info in self._index.items():
                total = info.get("chapterCount", 0)
                progress = info.get("progress", 0)
                novels.append(
                    {
                        "id": novel_id,
                        "title": info.get("title", "Untitled"),
                        "author": info.get("author", ""),
                        "chapterCount": total,
                        "progress": progress,
                        "progress_percent": self._progress_percent(progress, total),
                        "coverColor": info.get("coverColor", "#5A7A9A"),
                        "importedAt": info.get("importedAt", ""),
                        "source": info.get("source", ""),
                        "sourceType": info.get("sourceType", "txt"),
                    }
                )
            novels.sort(key=lambda item: item["importedAt"], reverse=True)
            return novels

    def get(self, novel_id: str) -> dict[str, Any] | None:
        with self._lock:
            info = self._index.get(novel_id)
            if not info:
                return None
            chapters = self._read_chapters(novel_id)
            total = len(chapters)
            progress = info.get("progress", 0)
            return {
                "id": novel_id,
                "title": info.get("title", "Untitled"),
                "author": info.get("author", ""),
                "description": info.get("description", ""),
                "chapterCount": total,
                "progress": progress,
                "progress_percent": self._progress_percent(progress, total),
                "coverColor": info.get("coverColor", "#5A7A9A"),
                "source": info.get("source", ""),
                "sourceType": info.get("sourceType", "txt"),
                "importedAt": info.get("importedAt", ""),
                "chapters": chapters,
            }

    def _chapter_path(self, novel_id: str, chapter_index: int) -> Path:
        return self._novel_path(novel_id) / f"chapter_{chapter_index}.txt"

    def get_chapter(self, novel_id: str, chapter_index: int) -> dict[str, Any] | None:
        if novel_id not in self._index:
            return None

        chapter_path = self._chapter_path(novel_id, chapter_index)
        if not chapter_path.exists():
            if not self._crawl_chapter(novel_id, chapter_index):
                return None

        chapters = self._read_chapters(novel_id)
        title = f"第{chapter_index + 1}章"
        if 0 <= chapter_index < len(chapters):
            title = chapters[chapter_index].get("title", title)

        with open(chapter_path, "r", encoding="utf-8") as f:
            content = f.read()

        return {
            "novelId": novel_id,
            "chapterIndex": chapter_index,
            "title": title,
            "content": content,
            "sentences": split_sentences(content),
        }

    def import_from_txt(self, file_path: str, title: str | None = None, author: str = "", source: str = "") -> dict[str, Any]:
        novel_id = str(uuid.uuid4())[:8]
        novel_path = self._novel_path(novel_id)
        novel_path.mkdir(parents=True, exist_ok=True)

        text = _read_file_with_fallback_encoding(file_path)

        if not title:
            title = Path(file_path).stem.replace("_", " ").replace("-", " ")

        # Chapter headers may be indented with ASCII spaces/tabs or full-width
        # spaces (U+3000), e.g. "\u3000\u3000第001章 迷茫 一". The standalone
        # marker alternative matches explicit words (序章/楔子/终章/尾声/后记/…)
        # rather than any line starting with a single marker character, which
        # previously produced bogus splits on body lines like "终于。".
        chapter_rx = re.compile(
            r"^[ \t\u3000]*(第[一二三四五六七八九十百千万零〇0-9]+[章节卷部集篇回](?:[ \t:：、-][^\n]*)?|"
            r"(?:序章|楔子|终章|尾声|后记|番外|前言|序言|引子)[^\n]{0,20})\s*$",
            re.MULTILINE,
        )
        matches = list(chapter_rx.finditer(text))
        chapter_titles: list[str] = []
        chapter_texts: list[str] = []

        if matches:
            if matches[0].start() > 0:
                lead = text[: matches[0].start()].strip()
                if lead:
                    chapter_titles.append("前言")
                    chapter_texts.append(lead)
            for i, match in enumerate(matches):
                start = match.end()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                chapter_titles.append(match.group(1).strip())
                chapter_texts.append(text[start:end].strip())
        else:
            paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
            if not paragraphs:
                chapter_titles.append("正文")
                chapter_texts.append(text.strip())
            else:
                chunk_size = max(1, min(50, math.ceil(len(paragraphs) / 5)))
                for start in range(0, len(paragraphs), chunk_size):
                    chunk = "\n\n".join(paragraphs[start : start + chunk_size]).strip()
                    if chunk:
                        chapter_titles.append(f"第{len(chapter_titles) + 1}章")
                        chapter_texts.append(chunk)

        chapters = []
        for index, chapter_title in enumerate(chapter_titles):
            content = chapter_texts[index] if index < len(chapter_texts) else ""
            with open(self._chapter_path(novel_id, index), "w", encoding="utf-8") as f:
                f.write(content)
            chapters.append({"index": index, "title": chapter_title, "cached": True})

        meta = {
            "title": title.strip() if title else "Untitled",
            "author": author.strip(),
            "source": source,
            "sourceType": "txt",
            "chapterCount": len(chapters),
            "progress": 0,
            "importedAt": datetime.now().isoformat(),
        }
        write_json(novel_path / "meta.json", meta)
        self._write_chapters(novel_id, chapters)
        self._write_crawl_status(
            novel_id,
            {
                "novelId": novel_id,
                "total": len(chapters),
                "cached": len(chapters),
                "prefetchTarget": 0,
                "prefetched": len(chapters),
                "inProgress": False,
                "failed": [],
                "updatedAt": datetime.now().isoformat(),
            },
        )
        with self._lock:
            self._index[novel_id] = meta
            self._save_index()
        return {"id": novel_id, **meta}

    def import_from_crawl(
        self,
        url: str,
        title: str | None = None,
        prefetch_chapters: int = 100,
        source_type: str = "auto",
    ) -> dict[str, Any]:
        try:
            crawler = self._new_crawler(source_type)
        except TypeError:
            crawler = self._new_crawler()
        if not crawler.fetch_novel_info(url):
            raise ValueError("Unable to parse the catalog URL.")

        novel_id = str(uuid.uuid4())[:8]
        novel_path = self._novel_path(novel_id)
        novel_path.mkdir(parents=True, exist_ok=True)

        chapters = [
            {"index": ch.index, "title": ch.title, "url": ch.url, "cached": False}
            for ch in crawler.chapters
        ]
        meta = {
            "title": (title or crawler.novel_title or "Untitled").strip(),
            "author": getattr(crawler, "novel_author", ""),
            "source": url,
            "sourceType": "url",
            "chapterCount": len(chapters),
            "progress": 0,
            "importedAt": datetime.now().isoformat(),
        }
        write_json(novel_path / "meta.json", meta)
        self._write_chapters(novel_id, chapters)
        self._write_crawl_status(
            novel_id,
            {
                "novelId": novel_id,
                "total": len(chapters),
                "cached": 0,
                "prefetchTarget": min(max(prefetch_chapters, 0), len(chapters)),
                "prefetched": 0,
                "inProgress": False,
                "failed": [],
                "updatedAt": datetime.now().isoformat(),
            },
        )
        with self._lock:
            self._index[novel_id] = meta
            self._save_index()

        if prefetch_chapters > 0:
            self.prefetch_chapters(novel_id, 0, prefetch_chapters)

        return {"id": novel_id, **meta}

    def _new_crawler(self, source_type: str = "auto"):
        crawler_path = str(self.crawler_dir or self.storage_dir.parent.parent / "ASD")
        if crawler_path not in sys.path:
            sys.path.insert(0, crawler_path)
        from novel_crawler import NovelCrawler

        try:
            return NovelCrawler(preferred_source=source_type)
        except TypeError:
            crawler = NovelCrawler()
            if hasattr(crawler, "set_preferred_source"):
                crawler.set_preferred_source(source_type)
            return crawler

    def _crawl_chapter(self, novel_id: str, chapter_index: int) -> bool:
        chapters = self._read_chapters(novel_id)
        if chapter_index < 0 or chapter_index >= len(chapters):
            return False
        chapter = chapters[chapter_index]
        if not chapter.get("url"):
            return False

        try:
            crawler = self._new_crawler()
            chapter_obj = type(
                "ChapterRef",
                (),
                {"title": chapter.get("title", ""), "url": chapter.get("url", ""), "index": chapter_index},
            )()
            content = crawler.download_chapter(chapter_obj)
            if not content:
                raise ValueError("empty chapter content")

            with open(self._chapter_path(novel_id, chapter_index), "w", encoding="utf-8") as f:
                f.write(content)
            chapter["cached"] = True
            chapter["cachedAt"] = datetime.now().isoformat()
            self._write_chapters(novel_id, chapters)
            self._refresh_crawl_counts(novel_id)
            return True
        except Exception as exc:
            import traceback
            print(f"PREFETCH ERROR ch{chapter_index}: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            self._mark_crawl_failed(novel_id, chapter_index, str(exc))
            return False

    def _refresh_crawl_counts(self, novel_id: str) -> dict[str, Any]:
        chapters = self._read_chapters(novel_id)
        status = self._read_crawl_status(novel_id)
        status["total"] = len(chapters)
        status["cached"] = sum(1 for ch in chapters if ch.get("cached"))
        status["prefetched"] = status["cached"]
        self._write_crawl_status(novel_id, status)
        return status

    def _mark_crawl_failed(self, novel_id: str, chapter_index: int, error: str) -> None:
        status = self._read_crawl_status(novel_id)
        failed = [item for item in status.get("failed", []) if item.get("index") != chapter_index]
        failed.append({"index": chapter_index, "error": error, "time": datetime.now().isoformat()})
        status["failed"] = failed
        self._write_crawl_status(novel_id, status)

    def prefetch_chapters(self, novel_id: str, start: int, limit: int) -> None:
        def worker() -> None:
            status = self._read_crawl_status(novel_id)
            status["inProgress"] = True
            status["prefetchTarget"] = min(limit, status.get("total", limit))
            self._write_crawl_status(novel_id, status)
            try:
                chapters = self._read_chapters(novel_id)
                end = min(len(chapters), start + max(0, limit))
                for index in range(max(0, start), end):
                    if chapters[index].get("cached"):
                        continue
                    self._crawl_chapter(novel_id, index)
                    time.sleep(0.2)
            finally:
                status = self._refresh_crawl_counts(novel_id)
                status["inProgress"] = False
                self._write_crawl_status(novel_id, status)

        thread = threading.Thread(target=worker, name=f"prefetch-{novel_id}", daemon=True)
        thread.start()

    def crawl_status(self, novel_id: str) -> dict[str, Any] | None:
        if novel_id not in self._index:
            return None
        return self._refresh_crawl_counts(novel_id)

    def delete(self, novel_id: str) -> bool:
        with self._lock:
            if novel_id not in self._index:
                return False
            novel_path = self._novel_path(novel_id)
            if novel_path.exists():
                shutil.rmtree(novel_path)
            del self._index[novel_id]
            self._save_index()
            return True

    def _sync_meta_file(self, novel_id: str) -> None:
        """Mirror the in-memory index entry into the novel's meta.json so that
        _index.json and meta.json never drift apart (survives restarts even if
        only one of the two files is read by some tooling)."""
        meta_path = self._novel_path(novel_id) / "meta.json"
        write_json(meta_path, self._index[novel_id])

    def update_meta(self, novel_id: str, updates: dict[str, Any]) -> bool:
        with self._lock:
            if novel_id not in self._index:
                return False
            allowed = {"title", "author", "description", "coverColor"}
            for key in allowed:
                if key in updates:
                    self._index[novel_id][key] = updates[key]
            self._save_index()
            self._sync_meta_file(novel_id)
            return True

    def update_progress(self, novel_id: str, chapter_index: int) -> bool:
        with self._lock:
            if novel_id not in self._index:
                return False
            self._index[novel_id]["progress"] = int(chapter_index)
            self._save_index()
            self._sync_meta_file(novel_id)
            return True
