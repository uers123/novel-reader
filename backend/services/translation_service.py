from __future__ import annotations

import threading
from typing import Any

class TranslationService:
    """Real-time text translation using deep-translator (free Google Translate API)."""

    def __init__(self):
        self._cache: dict[str, str] = {}
        self._lock = threading.Lock()

    def translate(self, text: str, target: str = "zh-CN", source: str = "auto") -> dict[str, Any]:
        if not text or not text.strip():
            return {"text": "", "source": source, "target": target}

        cache_key = f"{source}|{target}|{text}"
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached:
                return {"text": cached, "source": source, "target": target, "cached": True}

        try:
            from deep_translator import GoogleTranslator
            translator = GoogleTranslator(source=source, target=target)
            result = translator.translate(text)
            translated = result or ""
            with self._lock:
                self._cache[cache_key] = translated
            return {"text": translated, "source": source, "target": target, "cached": False}
        except Exception as exc:
            raise RuntimeError(f"Translation failed: {exc}")

    def translate_batch(self, texts: list[str], target: str = "zh-CN", source: str = "auto") -> list[dict[str, Any]]:
        results = []
        for text in texts:
            try:
                results.append(self.translate(text, target, source))
            except Exception:
                results.append({"text": "", "source": source, "target": target, "error": True})
        return results
