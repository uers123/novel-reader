# AI Audiobook Novel Reader (Novel Reader)

> **Merge note**: This project is the merged result of two sibling codebases, `novel` and `novel-reader`, built on the `novel-reader` baseline (a strict feature superset of `novel`); the `novel` repository has been archived. Shared defects were fixed during the merge: `POST /api/settings` now uses **partial-merge** semantics (only submitted fields are overwritten — unsubmitted fields are no longer reset to defaults), hardcoded machine paths were removed, and dead code / duplicate CSS were cleaned up. Where API or behavior differs from older versions, this README is authoritative.

A local-first web novel reader that combines **reading and listening** in one app: TXT/URL import → bookshelf management → chapter reading → ChatTTS local text-to-speech with sentence-by-sentence playback, plus real-time chapter translation. All data is stored locally as JSON files — no database required. When the backend is unreachable, the app gracefully falls back to built-in demo books with a one-click retry.

## Features

### 📚 Import & Bookshelf
- **TXT import**: click or drag-and-drop to upload; files larger than 2 MB are automatically split into 2 MB chunks, uploaded, and reassembled; encodings are auto-detected (UTF-8 / GBK / GB2312 / UTF-16)
- **Auto chapter splitting**: recognizes headers like “第X章 / 卷 / 回 / 节” plus prologues (序章), prefaces (楔子), epilogues (终章/尾声), afterwords (后记), extras (番外), etc.; books without a chapter list are split evenly by paragraphs
- **URL crawl import**: paste a catalog URL to import; a background thread prefetches the first 100 chapters while the frontend polls progress every 3 seconds; chapters not yet cached are fetched on demand when you open them (resumable crawling)
- **Automatic site detection**: adapts to Biquge-style sites (xbiquge / biquge / biqubao / 69shu and a dozen more domains) and Syosetu (syosetu.com / novel18.syosetu.com); the source type can also be chosen manually
- **Bookshelf management**: All / Reading / Finished tabs, search filter by title or author, edit title/author/cover color, delete, and export the current chapter as TXT

### 📖 Reader
- **5 ways to switch chapters**: previous/next buttons, dragging the progress slider, the table-of-contents panel, ←/→ keyboard keys, and left/right touch swipes
- **Resume reading**: chapter progress is saved automatically (backend + localStorage); book cards show a reading percentage and reopening jumps to where you left off
- **4 themes**: Day / Night / Eye-care / Parchment
- **Reading settings**: font size (14–34), line height, background color (preset palette + custom), brightness (30–120%), and 4 page-turn animations (push / cover / simulation / up-down); settings persist automatically
- **Sentence-level highlighting**: text is rendered sentence by sentence; the sentence being read is highlighted and scrolled into view

### 🔊 ChatTTS Local TTS
- **8 voices**: 软萌萝莉 (cute girl), 萌娃童声 (child), 深沉大叔 (deep male), 温柔少年 (gentle boy), 清朗男声 (clear male), 成熟男声 (mature male), 温柔女声 (gentle female), 清冷女声 (cool female) — click any voice to preview and set it as default
- **6 emotions**: auto / neutral / happy / sad / angry / surprised (auto-detected from keywords and punctuation)
- **Speed 0.5–2.0**: adjustable via slider, sentence-by-sentence playback
- **Seamless preloading**: two `Audio` objects — the next sentence is preloaded as the current one nears its end for gapless transitions
- **Batch pre-synthesis**: while playing, the next 20 sentences are synthesized ahead in one batch GPU call and cached locally
- **SHA-256 audio cache**: wav files are named by a digest of “voice|rate|emotion|text”, so repeat readings reuse cached audio instead of re-synthesizing
- **GPU tuning**: batch size (1–20), half precision to save VRAM (auto-falls back to full precision), per-batch CUDA cache clearing, and a VRAM threshold that automatically halves the batch size when exceeded
- **Lazy model loading**: startup only probes whether ChatTTS is installed (no model load); the model is loaded on first synthesis. Reading works fine without ChatTTS installed

### 🌐 Real-time Chapter Translation
- Based on the free Google Translate interface (via the `deep-translator` library) with automatic source-language detection
- Whole-chapter translation: the chapter is split into ≤1800-character chunks, translated chunk by chunk, and stitched back together; results are cached to a file per chapter × target language, so repeat translations return instantly
- 11 target languages (Simplified/Traditional Chinese, English, Japanese, Korean, French, German, Spanish, Russian, Thai, Vietnamese); optional “auto-translate on chapter switch”

## Quick Start

Requires Python 3.10+.

```powershell
# 1. Install backend dependencies
python -m pip install -r backend/requirements.txt

# 2. Start the server (it also serves the frontend)
python backend/app.py
```

Open `http://localhost:5000` in your browser. The port can be overridden with the `PORT` environment variable (e.g. `$env:PORT=8080`).

On Windows you can also double-click `start_novel_reader.bat` in the repo root: it checks/installs dependencies, starts the backend, polls until the server is ready (up to 90 s), then opens the browser, and keeps the window attached so the server stops when you close it.

### Enable Local TTS (optional)

```powershell
python -m pip install ChatTTS torch torchaudio soundfile transformers==4.41.0
```

- The model is downloaded from HuggingFace on first synthesis (requires internet; loading takes a few dozen seconds); afterwards everything runs locally
- With an NVIDIA GPU, CUDA is used automatically; batch size / half precision / VRAM threshold can be tuned in the reading settings
- No GPU or no model? Use the mock mode to exercise the full pipeline (it produces silent audio):

```powershell
$env:NOVEL_READER_MOCK_TTS = "1"
python backend/app.py
```

## Usage

1. Click the **+** button at the bottom-right to import: upload a TXT file or paste a novel catalog URL
2. Book cards show the first character of the cover, title/author, and reading progress; the “Reading / Finished” tabs and the search box help you find books quickly
3. In the reader, the bottom toolbar offers: Table of Contents, Night mode, Reading Settings, Voice (TTS), and Translate
4. Listening: tap “听” (listen), pick a voice and emotion, and playback starts sentence by sentence with the current sentence highlighted
5. Translation: tap “译” (translate), choose a target language, then “translate this chapter”; tick “auto-translate on chapter switch” to translate automatically

## API Summary

| Endpoint | Description |
|---|---|
| `GET /api/novels` | Bookshelf list |
| `GET /api/novels/{id}` | Book detail (with chapter list) |
| `GET /api/novels/{id}/chapters/{index}` | Chapter content (fetched on demand if not cached) |
| `POST /api/novels/import` | TXT upload (≤2 MB) |
| `POST /api/novels/import/start\|chunk\|complete` | Chunked upload for large files |
| `POST /api/novels/import-url` | URL catalog import + background prefetch |
| `GET /api/novels/{id}/crawl-status` | Crawl cache progress (`{cached,total,inProgress}`) |
| `PUT /api/novels/{id}/progress` | Save reading progress |
| `PUT /api/novels/{id}/meta` | Update title/author/description/cover color |
| `POST /api/tts/synthesize\|synthesize_batch` | Single / batch TTS synthesis |
| `GET /api/tts/voices`, `/api/tts/emotions` | Voice / emotion lists |
| `GET\|PUT /api/tts/gpu-settings` | Read / update GPU settings |
| `POST /api/translate/chapter` | Whole-chapter translation (file-cached) |
| `GET /api/languages`, `GET\|POST /api/settings` | Language list / settings read-write |

## Directory Layout

```
novel-reader/
├── index.html / css/ / js/      # Frontend: vanilla JS (IIFE modules), no framework, no build step
├── backend/
│   ├── app.py                   # Flask routes & app assembly (also serves frontend static files)
│   ├── services/
│   │   ├── novel_service.py     # Bookshelf, chapters, crawl scheduling (lazy load + background prefetch)
│   │   ├── tts_service.py       # ChatTTS adapter, SHA-256 cache, GPU throttling
│   │   └── translation_service.py  # Free Google translation + in-memory cache
│   ├── storage_utils.py         # Atomic JSON writes (temp file + os.replace)
│   ├── text_utils.py            # Sentence splitting, text chunking
│   └── test_delivery.py         # Delivery regression tests
├── ASD/novel_crawler.py         # Standalone crawler (also usable from the command line)
└── .github/workflows/ci.yml     # CI: Python 3.10–3.12 + unittest
```

Runtime data (`backend/novels/`, `settings.json`, `tts_cache/`, `uploads/`) is excluded via `.gitignore` and never enters the repository.

## Technical Notes

- **No database**: bookshelf index, metadata, chapters, crawl status, and translation caches are all JSON files; writes are atomic (temp file + `os.replace`) with concurrency protection
- **Lazy chapter loading**: URL import only stores the catalog; a background thread prefetches chapters at 0.2 s intervals, and uncached chapters are fetched on demand — crawling can resume where it left off
- **TTS cache**: audio files are named by the first 24 hex chars of `SHA-256(voice|rate|emotion|text)`; batch synthesis groups by emotion, splits by batch size, and halves the batch when VRAM usage exceeds the threshold
- **Encoding fallback**: TXT import tries UTF-8 → GBK → GB2312 → UTF-16 → ASCII in order

## Testing

```powershell
$env:NOVEL_READER_MOCK_TTS = "1"
python -m unittest discover -s backend -p "test*.py" -v
```

All 14 backend unit tests pass (covering TXT/chunked import, URL import & lazy loading, concurrent JSON writes, settings round-trip, mock TTS, GPU-setting clamping, translation cache, and frontend static assets); GitHub Actions runs them on Python 3.10 / 3.11 / 3.12.

## Known Limitations

- **Hardcoded local paths**: `start_novel_reader.bat` and `tts_service.py` contain absolute fallback paths from the author's machine (e.g. `D:\py3.13.3\python.exe`) — adjust them for your environment, or point to your Python via the `NOVEL_READER_PYTHON` environment variable
- **No frontend tests**: only backend unit tests and static-asset regression checks exist
- **ChatTTS is a heavy optional dependency**: model download on first use needs internet; CPU-only synthesis is slow
- **Translation relies on a free API**: the Google free endpoint used by `deep-translator` may be rate-limited or unavailable; failures surface in the UI
- **Crawling depends on site structure**: site redesigns or anti-bot measures can break parsing; ad-line filtering is regex-based heuristics and may over- or under-filter
- **Single-user local app**: JSON file storage targets single-machine use; no multi-user or cloud sync

## License

[MIT](LICENSE) © 2026 uers123
