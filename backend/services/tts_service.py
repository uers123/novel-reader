from __future__ import annotations

import hashlib
import os
import sys
import threading
from pathlib import Path
from typing import Any

from text_utils import split_sentences

class TTSService:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.speakers_dir = cache_dir / "speakers"
        self.speakers_dir.mkdir(parents=True, exist_ok=True)
        self._chat = None
        self._model_error: str | None = None
        self._lock = threading.Lock()
        self._speaker_cache: dict[str, Any] = {}

        # GPU / VRAM settings (can be updated via API)
        self.gpu = {
            "maxBatchSize": 5,
            "useHalfPrecision": False,
            "clearCache": True,
            "maxVRAM": 80,
            "halfPrecisionFallback": False,
        }

        self.voices = [
            {"id": "ruanmeng_female", "name": "软萌萝莉", "gender": "female", "avatar": "萝", "seed": 11451},
            {"id": "child", "name": "萌娃童声", "gender": "child", "avatar": "童", "seed": 2222},
            {"id": "dashu_male", "name": "深沉大叔", "gender": "male", "avatar": "叔", "seed": 3333},
            {"id": "young_male", "name": "温柔少年", "gender": "male", "avatar": "少", "seed": 4444},
            {"id": "qinglang_male", "name": "清朗男声", "gender": "male", "avatar": "朗", "seed": 5555},
            {"id": "mature_male", "name": "成熟男声", "gender": "male", "avatar": "熟", "seed": 6666},
            {"id": "gentle_female", "name": "温柔女声", "gender": "female", "avatar": "温", "seed": 7777},
            {"id": "cool_female", "name": "清冷女声", "gender": "female", "avatar": "冷", "seed": 8888},
        ]

        self.emotions = {
            "neutral": {"prompt": "[oral_0]", "temperature": 0.3},
            "happy": {"prompt": "[oral_4][laugh_1]", "temperature": 0.5},
            "sad": {"prompt": "[oral_1][break_4]", "temperature": 0.2},
            "angry": {"prompt": "[oral_6]", "temperature": 0.7},
            "surprise": {"prompt": "[oral_5][break_4]", "temperature": 0.6},
        }

    def _cuda_available(self) -> bool:
        try:
            import torch
            return torch.cuda.is_available()
        except Exception:
            return False

    def _clear_gpu_cache(self) -> None:
        if not self.gpu.get("clearCache"):
            return
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            pass

    def _vram_usage_pct(self) -> float:
        try:
            import torch
            if not torch.cuda.is_available():
                return 0
            allocated = torch.cuda.memory_allocated()
            total = torch.cuda.get_device_properties(0).total_memory
            return (allocated / total) * 100 if total > 0 else 0
        except Exception:
            return 0

    def _maybe_throttle_batch(self, requested: int) -> int:
        requested = max(1, requested)
        vram_pct = self._vram_usage_pct()
        limit = self.gpu.get("maxVRAM", 80)
        if vram_pct > limit and requested > 1:
            reduced = max(1, requested // 2)
            print(f"  VRAM {vram_pct:.0f}% > {limit}% — throttling {requested}->{reduced}", file=sys.stderr)
            return reduced
        return max(1, min(requested, int(self.gpu.get("maxBatchSize", 5) or 1)))

    def update_gpu_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        if "maxBatchSize" in settings:
            self.gpu["maxBatchSize"] = max(1, min(20, int(settings["maxBatchSize"])))
        if "maxVRAM" in settings:
            self.gpu["maxVRAM"] = max(1, min(100, int(settings["maxVRAM"])))
        for key in ("useHalfPrecision", "clearCache"):
            if key in settings:
                self.gpu[key] = bool(settings[key])
        return dict(self.gpu)

    def list_voices(self) -> list[dict[str, Any]]:
        available = self._chattts_available()
        return [{**voice, "installed": available, "available": available} for voice in self.voices]

    def list_emotions(self) -> list[dict[str, str]]:
        names = {
            "auto": "自动识别",
            "neutral": "平静",
            "happy": "开心",
            "sad": "悲伤",
            "angry": "愤怒",
            "surprise": "惊讶",
        }
        return [{"id": key, "name": names[key]} for key in ["auto", *self.emotions.keys()]]

    def _mock_enabled(self) -> bool:
        return os.environ.get("NOVEL_READER_MOCK_TTS", "").lower() in {"1", "true", "yes"}

    def _chattts_available(self) -> bool:
        if self._model_error:
            return False
        # Fast probe: locate the package without actually importing it.
        # Importing ChatTTS pulls in torch/transformers and can take 40-60s,
        # which is unacceptable during startup banner checks.
        try:
            import importlib.util

            if importlib.util.find_spec("ChatTTS") is not None:
                return True
        except Exception:
            pass
        # Fallback: scan known site-packages paths
        try:
            import glob as _glob

            for _p in _glob.glob(
                sys.prefix + "/Lib/site-packages/ChatTTS",
            ) + _glob.glob(
                sys.prefix + "/lib/python*/site-packages/ChatTTS",
            ):
                if _p:
                    return True
        except Exception:
            pass
        return False

    def _ensure_chattts_importable(self) -> None:
        """Ensure ChatTTS can be imported, trying alternate site-packages paths if needed."""
        try:
            import ChatTTS  # noqa: F401
            return
        except ImportError:
            pass
        # Fallback: scan for ChatTTS in common site-packages locations
        import glob
        candidates = glob.glob(
            sys.prefix + "/Lib/site-packages/ChatTTS"
        ) + glob.glob(
            sys.prefix + "/lib/python*/site-packages/ChatTTS"
        )
        for _p in candidates:
            _sp = _p.replace("/ChatTTS", "").replace("\\ChatTTS", "")
            if _sp not in sys.path:
                sys.path.insert(0, _sp)
                try:
                    import ChatTTS  # noqa: F401
                    print(f"  ChatTTS found via fallback path: {_sp}", file=sys.stderr)
                    return
                except ImportError:
                    if _sp in sys.path:
                        sys.path.remove(_sp)
        raise ImportError("ChatTTS not found in any Python site-packages")

    def _load_model(self):
        if self._chat is not None:
            return self._chat
        if self._model_error:
            raise RuntimeError(self._model_error)
        try:
            self._ensure_chattts_importable()
            import ChatTTS
            import numpy as np
            import torch

            with self._lock:
                if self._chat is None:
                    chat = ChatTTS.Chat()
                    chat.load(source="huggingface", compile=False)
                    use_half = self._cuda_available() and self.gpu.get("useHalfPrecision", True)
                    if use_half:
                        try:
                            if hasattr(chat, 'decoder') and hasattr(chat.decoder, 'half'):
                                chat.decoder = chat.decoder.half()
                            if hasattr(chat, 'model') and hasattr(chat.model, 'half'):
                                chat.model = chat.model.half()
                        except Exception:
                            self.gpu["useHalfPrecision"] = False
                            self.gpu["halfPrecisionFallback"] = True
                    self._chat = chat
                    self._init_voice_embeddings()
                    self._clear_gpu_cache()
            return self._chat
        except Exception as exc:
            self._model_error = (
                "ChatTTS is not installed or failed to load. "
                "Install: pip install ChatTTS torch torchaudio soundfile transformers==4.41.0. "
                f"Details: {exc}"
            )
            raise RuntimeError(self._model_error) from exc

    def _init_voice_embeddings(self) -> None:
        for voice in self.voices:
            emb_path = self.speakers_dir / f"{voice['id']}.txt"
            if emb_path.exists():
                continue
            spk_emb = self._chat.sample_random_speaker()
            emb_path.write_text(spk_emb, encoding="utf-8")

    def _get_speaker_embedding(self, voice_id: str) -> str:
        if voice_id in self._speaker_cache:
            return self._speaker_cache[voice_id]
        emb_path = self.speakers_dir / f"{voice_id}.txt"
        if emb_path.exists():
            spk_emb = emb_path.read_text(encoding="utf-8")
        else:
            spk_emb = self._chat.sample_random_speaker()
            emb_path.write_text(spk_emb, encoding="utf-8")
        self._speaker_cache[voice_id] = spk_emb
        return spk_emb

    @staticmethod
    def detect_emotion(text: str) -> str:
        happy_kw = ["开心", "高兴", "快乐", "欢喜", "愉快", "兴奋", "惊喜", "美好", "棒", "赞", "哈哈", "嘻嘻", "笑了"]
        sad_kw = ["伤心", "难过", "悲伤", "悲哀", "流泪", "痛苦", "失落", "忧愁", "可怜", "呜呜", "哭了"]
        angry_kw = ["生气", "可恶", "该死", "混蛋", "滚开", "烦躁", "暴躁", "气死", "气人", "愤怒", "讨厌", "恨"]
        surprise_kw = ["惊讶", "震惊", "诧异", "竟然", "居然", "没想到", "天哪", "哇", "啊呀"]
        text_lower = text
        scores = {"neutral": 0, "happy": 0, "sad": 0, "angry": 0, "surprise": 0}
        for kw in happy_kw:
            scores["happy"] += text_lower.count(kw) * 2
        for kw in surprise_kw:
            scores["surprise"] += text_lower.count(kw) * 2
        for kw in sad_kw:
            scores["sad"] += text_lower.count(kw) * 2
        for kw in angry_kw:
            scores["angry"] += text_lower.count(kw) * 2
        scores["happy"] += text_lower.count("！") + text_lower.count("!")
        scores["surprise"] += text_lower.count("？") + text_lower.count("?")
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "neutral"

    def _tts_params(self, voice_id: str, rate: float, emotion: str):
        import ChatTTS as CT
        voice_seed = 42
        for v in self.voices:
            if v["id"] == voice_id:
                voice_seed = v["seed"]
                break
        emotion_cfg = self.emotions.get(emotion, self.emotions["neutral"])
        spk_emb = self._get_speaker_embedding(voice_id)
        speed_val = max(1, min(9, round(rate * 5)))
        params_refine_text = CT.Chat.RefineTextParams(prompt=emotion_cfg["prompt"])
        params_infer_code = CT.Chat.InferCodeParams(
            spk_emb=spk_emb,
            manual_seed=voice_seed,
            temperature=emotion_cfg["temperature"],
            top_P=0.7,
            top_K=20,
            prompt=f"[speed_{speed_val}]",
        )
        return params_refine_text, params_infer_code

    def _write_mock_wav(self, audio_path: Path) -> None:
        if audio_path.exists():
            return
        import wave

        audio_path.parent.mkdir(parents=True, exist_ok=True)
        sample_rate = 24000
        duration_seconds = 0.25
        silence = b"\x00\x00" * int(sample_rate * duration_seconds)
        with wave.open(str(audio_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(silence)

    def _synthesize_one(self, text: str, voice_id: str, rate: float, emotion: str) -> dict[str, Any]:
        digest = hashlib.sha256(f"{voice_id}|{rate}|{emotion}|{text}".encode("utf-8")).hexdigest()[:24]
        audio_path = self.cache_dir / f"{digest}.wav"
        if audio_path.exists():
            return {"cached": True, "audioUrl": f"/api/tts/audio/{audio_path.name}"}
        if self._mock_enabled():
            mock_path = self.cache_dir / f"mock-{digest}.wav"
            self._write_mock_wav(mock_path)
            return {"cached": False, "audioUrl": f"/api/tts/audio/{mock_path.name}", "mock": True}
        chat = self._load_model()
        import soundfile as sf
        prp, pic = self._tts_params(voice_id, rate, emotion)
        try:
            with self._lock:
                wavs = chat.infer([text], params_refine_text=prp, params_infer_code=pic, use_decoder=True)
        except RuntimeError as exc:
            if self.gpu.get("useHalfPrecision") and "Half" in str(exc):
                self.gpu["useHalfPrecision"] = False
                self.gpu["halfPrecisionFallback"] = True
                self._chat = None
                chat = self._load_model()
                prp, pic = self._tts_params(voice_id, rate, emotion)
                with self._lock:
                    wavs = chat.infer([text], params_refine_text=prp, params_infer_code=pic, use_decoder=True)
            else:
                raise
        sf.write(str(audio_path), wavs[0], 24000)
        self._clear_gpu_cache()
        return {"cached": False, "audioUrl": f"/api/tts/audio/{audio_path.name}"}

    def synthesize(self, text: str, voice_id: str, rate: float = 1.0, emotion: str | None = None) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise ValueError("text is required")
        voice_id = voice_id or "qinglang_male"
        if emotion == "auto":
            emotion = None
        emotion = emotion or self.detect_emotion(text)
        sentences = split_sentences(text)
        result = self._synthesize_one(text, voice_id, rate, emotion)
        return {**result, "sentences": sentences, "voiceId": voice_id}

    def synthesize_batch(self, texts: list[str], voice_id: str, rate: float = 1.0, emotion: str | None = None) -> list[dict[str, Any]]:
        texts = [t.strip() for t in texts if t.strip()]
        if not texts:
            return []
        voice_id = voice_id or "qinglang_male"
        if emotion == "auto":
            emotion = None
        results: list[dict[str, Any]] = [None] * len(texts)
        uncached: list[tuple[int, str, str, str]] = []
        for i, text in enumerate(texts):
            emo = emotion or self.detect_emotion(text)
            digest = hashlib.sha256(f"{voice_id}|{rate}|{emo}|{text}".encode("utf-8")).hexdigest()[:24]
            audio_path = self.cache_dir / f"{digest}.wav"
            if audio_path.exists():
                results[i] = {"index": i, "cached": True, "audioUrl": f"/api/tts/audio/{audio_path.name}"}
            else:
                uncached.append((i, text, emo, digest))
        if not uncached:
            return results
        if self._mock_enabled():
            for orig_idx, _text, _emo, digest in uncached:
                mock_path = self.cache_dir / f"mock-{digest}.wav"
                self._write_mock_wav(mock_path)
                results[orig_idx] = {
                    "index": orig_idx,
                    "cached": False,
                    "audioUrl": f"/api/tts/audio/{mock_path.name}",
                    "mock": True,
                }
            return results
        chat = self._load_model()
        import soundfile as sf
        emotion_groups: dict[str, list[tuple[int, str, str, str]]] = {}
        for item in uncached:
            emotion_groups.setdefault(item[2], []).append(item)
        for group in emotion_groups.values():
            sub_batch_size = self._maybe_throttle_batch(len(group))
            for chunk_start in range(0, len(group), sub_batch_size):
                chunk = group[chunk_start:chunk_start + sub_batch_size]
                chunk_texts = [item[1] for item in chunk]
                batch_emo = chunk[0][2]
                prp, pic = self._tts_params(voice_id, rate, batch_emo)
                try:
                    with self._lock:
                        wavs = chat.infer(chunk_texts, params_refine_text=prp, params_infer_code=pic, use_decoder=True, split_text=False)
                except RuntimeError as exc:
                    if self.gpu.get("useHalfPrecision") and "Half" in str(exc):
                        self.gpu["useHalfPrecision"] = False
                        self.gpu["halfPrecisionFallback"] = True
                        self._chat = None
                        chat = self._load_model()
                        prp, pic = self._tts_params(voice_id, rate, batch_emo)
                        with self._lock:
                            wavs = chat.infer(chunk_texts, params_refine_text=prp, params_infer_code=pic, use_decoder=True, split_text=False)
                    else:
                        raise
                for (orig_idx, _text, _emo, digest), wav in zip(chunk, wavs):
                    audio_path = self.cache_dir / f"{digest}.wav"
                    sf.write(str(audio_path), wav, 24000)
                    results[orig_idx] = {"index": orig_idx, "cached": False, "audioUrl": f"/api/tts/audio/{audio_path.name}"}
                self._clear_gpu_cache()
        return results
