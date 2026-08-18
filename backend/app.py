"""
Flask backend for the novel reader.

Features:
- TXT import and URL catalog import.
- Lazy chapter crawling with background prefetch.
- Chapter progress and reader settings persistence.
- Local TTS service adapter, designed for ChatTTS.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory
from services.novel_service import NovelManager
from services.translation_service import TranslationService
from services.tts_service import TTSService
from storage_utils import read_json, write_json
from text_utils import chunk_text, split_sentences

try:
    from flask_cors import CORS
except ImportError:  # Keep the app importable before dependencies are installed.
    def CORS(_app: Flask) -> None:
        return None


if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
NOVELS_DIR = BASE_DIR / "novels"
SETTINGS_FILE = BASE_DIR / "settings.json"
TTS_CACHE_DIR = BASE_DIR / "tts_cache"
UPLOADS_DIR = BASE_DIR / "uploads"
CHUNK_SIZE = 2 * 1024 * 1024
DEFAULT_SETTINGS = {
    "theme": "day",
    "fontSize": 20,
    "lineHeight": 2.0,
    "bgColor": "#F6F3EC",
    "pageEffect": "updown",
    "brightness": 100,
    "voiceId": "qinglang_male",
    "emotion": "auto",
}

app = Flask(__name__, static_folder=str(PROJECT_DIR), static_url_path="")
CORS(app)

novel_manager = NovelManager(NOVELS_DIR, PROJECT_DIR / "ASD")
tts_service = TTSService(TTS_CACHE_DIR)
translation_service = TranslationService()


@app.route("/")
def index():
    return send_from_directory(str(PROJECT_DIR), "index.html")


@app.route("/api/novels", methods=["GET"])
def api_list_novels():
    return jsonify({"novels": novel_manager.list_all()})


@app.route("/api/novels/<novel_id>", methods=["GET"])
def api_get_novel(novel_id: str):
    novel = novel_manager.get(novel_id)
    if not novel:
        return jsonify({"error": "novel not found"}), 404
    return jsonify(novel)


@app.route("/api/novels/<novel_id>/chapters/<int:chapter_index>", methods=["GET"])
def api_get_chapter(novel_id: str, chapter_index: int):
    chapter = novel_manager.get_chapter(novel_id, chapter_index)
    if not chapter:
        return jsonify({"error": "chapter not found"}), 404
    return jsonify(chapter)


@app.route("/api/novels/import", methods=["POST"])
def api_import_novel():
    if "file" not in request.files:
        return jsonify({"error": "TXT file is required"}), 400

    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"error": "file name is empty"}), 400

    temp_path = NOVELS_DIR / f"_upload_{uuid.uuid4().hex}.txt"
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    uploaded.save(str(temp_path))
    try:
        result = novel_manager.import_from_txt(
            str(temp_path),
            title=request.form.get("title") or Path(uploaded.filename).stem,
            author=request.form.get("author", ""),
        )
        return jsonify({"success": True, "novel": result}), 201
    finally:
        if temp_path.exists():
            temp_path.unlink()


@app.route("/api/novels/import/start", methods=["POST"])
def api_import_start():
    data = request.get_json(silent=True) or {}
    filename = Path(data.get("filename") or "upload.txt").name
    if not filename.lower().endswith(".txt"):
        return jsonify({"error": "TXT file is required"}), 400

    upload_id = uuid.uuid4().hex
    upload_dir = UPLOADS_DIR / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "uploadId": upload_id,
        "filename": filename,
        "title": data.get("title") or Path(filename).stem,
        "author": data.get("author", ""),
        "totalSize": int(data.get("totalSize", 0) or 0),
        "chunkSize": int(data.get("chunkSize", CHUNK_SIZE) or CHUNK_SIZE),
        "createdAt": datetime.now().isoformat(),
        "chunks": [],
    }
    write_json(upload_dir / "upload.json", meta)
    return jsonify({"uploadId": upload_id, "chunkSize": meta["chunkSize"]}), 201


@app.route("/api/novels/import/chunk", methods=["POST"])
def api_import_chunk():
    upload_id = request.form.get("uploadId", "")
    chunk_index = request.form.get("chunkIndex", "")
    if not upload_id or not chunk_index.isdigit() or "chunk" not in request.files:
        return jsonify({"error": "uploadId, chunkIndex and chunk are required"}), 400

    upload_dir = UPLOADS_DIR / upload_id
    meta_path = upload_dir / "upload.json"
    if not meta_path.exists():
        return jsonify({"error": "upload not found"}), 404

    index = int(chunk_index)
    chunk_file = upload_dir / f"chunk_{index:08d}.part"
    request.files["chunk"].save(str(chunk_file))

    meta = read_json(meta_path, {})
    chunks = set(int(item) for item in meta.get("chunks", []))
    chunks.add(index)
    meta["chunks"] = sorted(chunks)
    write_json(meta_path, meta)
    return jsonify({"success": True, "received": index})


@app.route("/api/novels/import/complete", methods=["POST"])
def api_import_complete():
    data = request.get_json(silent=True) or {}
    upload_id = data.get("uploadId", "")
    upload_dir = UPLOADS_DIR / upload_id
    meta_path = upload_dir / "upload.json"
    if not meta_path.exists():
        return jsonify({"error": "upload not found"}), 404

    meta = read_json(meta_path, {})
    chunk_files = sorted(upload_dir.glob("chunk_*.part"))
    if not chunk_files:
        return jsonify({"error": "no chunks uploaded"}), 400

    assembled = upload_dir / meta.get("filename", "upload.txt")
    with open(assembled, "wb") as out:
        for expected, chunk_file in enumerate(chunk_files):
            if chunk_file.name != f"chunk_{expected:08d}.part":
                return jsonify({"error": f"missing chunk {expected}"}), 400
            with open(chunk_file, "rb") as src:
                shutil.copyfileobj(src, out)

    try:
        result = novel_manager.import_from_txt(
            str(assembled),
            title=data.get("title") or meta.get("title"),
            author=data.get("author", meta.get("author", "")),
        )
        return jsonify({"success": True, "novel": result}), 201
    finally:
        shutil.rmtree(upload_dir, ignore_errors=True)


@app.route("/api/novels/import/<upload_id>", methods=["DELETE"])
def api_import_cancel(upload_id: str):
    upload_dir = UPLOADS_DIR / upload_id
    if not upload_dir.exists():
        return jsonify({"error": "upload not found"}), 404
    shutil.rmtree(upload_dir, ignore_errors=True)
    return jsonify({"success": True})


@app.route("/api/novels/import-url", methods=["POST"])
def api_import_from_url():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "url is required"}), 400
    prefetch = int(data.get("prefetchChapters", 100))
    try:
        source_type = data.get("sourceType") or data.get("source") or "auto"
        result = novel_manager.import_from_crawl(
            url,
            title=data.get("title") or None,
            prefetch_chapters=prefetch,
            source_type=source_type,
        )
        status = novel_manager.crawl_status(result["id"])
        return jsonify({"success": True, "novel": result, "crawlStatus": status}), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"crawl import failed: {exc}"}), 500


@app.route("/api/novels/<novel_id>/crawl-status", methods=["GET"])
def api_crawl_status(novel_id: str):
    status = novel_manager.crawl_status(novel_id)
    if not status:
        return jsonify({"error": "novel not found"}), 404
    return jsonify(status)


@app.route("/api/novels/<novel_id>", methods=["DELETE"])
def api_delete_novel(novel_id: str):
    if novel_manager.delete(novel_id):
        return jsonify({"success": True})
    return jsonify({"error": "novel not found"}), 404


@app.route("/api/novels/<novel_id>/meta", methods=["PUT"])
def api_update_novel_meta(novel_id: str):
    data = request.get_json(silent=True) or {}
    if novel_manager.update_meta(novel_id, data):
        return jsonify({"success": True, "novel": novel_manager.get(novel_id)})
    return jsonify({"error": "novel not found"}), 404


@app.route("/api/novels/<novel_id>/progress", methods=["PUT"])
def api_update_progress(novel_id: str):
    data = request.get_json(silent=True) or {}
    if novel_manager.update_progress(novel_id, int(data.get("chapterIndex", 0))):
        return jsonify({"success": True})
    return jsonify({"error": "novel not found"}), 404


@app.route("/api/tts/voices", methods=["GET"])
def api_tts_voices():
    return jsonify({"voices": tts_service.list_voices()})


@app.route("/api/tts/emotions", methods=["GET"])
def api_tts_emotions():
    return jsonify({"emotions": tts_service.list_emotions()})


@app.route("/api/tts/synthesize", methods=["POST"])
def api_tts_synthesize():
    data = request.get_json(silent=True) or {}
    try:
        text = data.get("text")
        if not text and data.get("novelId") and data.get("chapterIndex") is not None:
            chapter = novel_manager.get_chapter(data["novelId"], int(data["chapterIndex"]))
            if not chapter:
                return jsonify({"error": "chapter not found"}), 404
            sentences = chapter.get("sentences") or split_sentences(chapter["content"])
            sentence_index = data.get("sentenceIndex")
            text = sentences[int(sentence_index)] if sentence_index is not None else chapter["content"]
        result = tts_service.synthesize(
                text or "",
                data.get("voiceId") or DEFAULT_SETTINGS["voiceId"],
                float(data.get("rate", 1.0)),
                data.get("emotion"),
            )
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"error": str(exc), "installed": False}), 503
    except Exception as exc:
        return jsonify({"error": f"TTS failed: {exc}"}), 500


@app.route("/api/tts/synthesize_batch", methods=["POST"])
def api_tts_synthesize_batch():
    """Batch TTS: generate audio for multiple texts in one GPU call."""
    data = request.get_json(silent=True) or {}
    try:
        texts = data.get("texts", [])
        if not texts:
            return jsonify({"error": "texts list is required"}), 400
        results = tts_service.synthesize_batch(
            texts,
            data.get("voiceId") or DEFAULT_SETTINGS["voiceId"],
            float(data.get("rate", 1.0)),
            data.get("emotion"),
        )
        return jsonify({"results": results, "count": len(results)})
    except RuntimeError as exc:
        return jsonify({"error": str(exc), "installed": False}), 503
    except Exception as exc:
        return jsonify({"error": f"batch TTS failed: {exc}"}), 500


@app.route("/api/tts/audio/<path:filename>", methods=["GET"])
def api_tts_audio(filename: str):
    return send_from_directory(str(TTS_CACHE_DIR), filename)


@app.route("/api/tts/gpu-settings", methods=["GET"])
def api_tts_gpu_settings():
    return jsonify({"gpu": tts_service.gpu, "cudaAvailable": tts_service._cuda_available()})


@app.route("/api/tts/gpu-settings", methods=["PUT"])
def api_tts_update_gpu_settings():
    data = request.get_json(silent=True) or {}
    settings = tts_service.update_gpu_settings(data)
    return jsonify({"success": True, "gpu": settings})


@app.route("/api/translate", methods=["POST"])
def api_translate():
    """Translate text with auto-detect source language."""
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    target = data.get("target", "zh-CN")
    source = data.get("source", "auto")
    try:
        if data.get("batch"):
            texts = data.get("texts", [text])
            results = translation_service.translate_batch(texts, target, source)
            return jsonify({"results": results, "count": len(results)})
        result = translation_service.translate(text, target, source)
        return jsonify(result)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        return jsonify({"error": f"Translation failed: {exc}"}), 500


@app.route("/api/translate/chapter", methods=["POST"])
def api_translate_chapter():
    data = request.get_json(silent=True) or {}
    novel_id = data.get("novelId", "")
    chapter_index = data.get("chapterIndex")
    target = (data.get("target") or "zh-CN").lower()
    source = data.get("source", "auto")
    force = bool(data.get("force"))

    if not novel_id or chapter_index is None:
        return jsonify({"error": "novelId and chapterIndex are required"}), 400

    chapter = novel_manager.get_chapter(novel_id, int(chapter_index))
    if not chapter:
        return jsonify({"error": "chapter not found"}), 404

    translation_dir = novel_manager._novel_path(novel_id) / "translations"
    translation_dir.mkdir(parents=True, exist_ok=True)
    safe_target = re.sub(r"[^a-z0-9_-]+", "-", target)
    cache_file = translation_dir / f"chapter_{int(chapter_index)}_{safe_target}.txt"
    if cache_file.exists() and not force:
        translated = cache_file.read_text(encoding="utf-8")
        return jsonify({
            "novelId": novel_id,
            "chapterIndex": int(chapter_index),
            "target": target,
            "translated": translated,
            "text": translated,
            "cached": True,
        })

    try:
        chunks = chunk_text(chapter.get("content", ""), max_chars=1800)
        translated_chunks = [
            translation_service.translate(chunk, target, source).get("text", "")
            for chunk in chunks
        ]
        translated = "\n\n".join(item for item in translated_chunks if item)
        cache_file.write_text(translated, encoding="utf-8")
        return jsonify({
            "novelId": novel_id,
            "chapterIndex": int(chapter_index),
            "target": target,
            "translated": translated,
            "text": translated,
            "cached": False,
        })
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        return jsonify({"error": f"Translation failed: {exc}"}), 500


@app.route("/api/languages", methods=["GET"])
def api_languages():
    """Return supported target languages for translation."""
    return jsonify({
        "languages": [
            {"code": "zh-CN", "name": "简体中文"},
            {"code": "zh-TW", "name": "繁体中文"},
            {"code": "en", "name": "English"},
            {"code": "ja", "name": "日本語"},
            {"code": "ko", "name": "한국어"},
            {"code": "fr", "name": "Français"},
            {"code": "de", "name": "Deutsch"},
            {"code": "es", "name": "Español"},
            {"code": "ru", "name": "Русский"},
            {"code": "th", "name": "ไทย"},
            {"code": "vi", "name": "Tiếng Việt"},
        ]
    })


@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    settings = {**DEFAULT_SETTINGS, **read_json(SETTINGS_FILE, {})}
    return jsonify(settings)


@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    # 部分合并：仅覆盖 payload 中的字段，保留已持久化但未提交的键（默认值在 GET 时合并）
    payload = request.get_json(silent=True) or {}
    settings = {**read_json(SETTINGS_FILE, {}), **payload}
    write_json(SETTINGS_FILE, settings)
    return jsonify({"success": True, "settings": settings})


@app.route("/<path:path>")
def static_files(path: str):
    return send_from_directory(str(PROJECT_DIR), path)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print("Novel reader backend starting")
    print(f"Python: {sys.executable}")
    print(f"Storage: {NOVELS_DIR}")
    _chattts_ok = tts_service._chattts_available()
    print(f"ChatTTS: {'✓ available' if _chattts_ok else '✗ NOT FOUND'}")
    if tts_service._cuda_available():
        import torch
        _vram = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        print(f"CUDA: ✓ {torch.cuda.get_device_name()} ({_vram:.1f} GB)")
    else:
        print("CUDA: ✗ not available")
    print(f"URL: http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
