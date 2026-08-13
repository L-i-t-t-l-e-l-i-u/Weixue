"""Audio transcription abstraction for the demo pipeline.

Providers (ASR_PROVIDER env):
- mock:      returns a canned demo transcript — offline-safe, DEFAULT
- qwen_asr:  DashScope (百炼) qwen3-asr-flash via the OpenAI-compatible
             chat/completions endpoint with base64 audio input; reuses
             LLM_API_KEY / LLM_BASE_URL — one key covers LLM + ASR
- openai:    OpenAI-compatible /audio/transcriptions (e.g. whisper-1); works when
             LLM_PROVIDER/LLM_BASE_URL exposes an audio endpoint
- dashscope: DashScope (百炼) paraformer via the `dashscope` SDK;
             requires `pip install dashscope` and a Model Studio API key

Frontend uploads audio -> this transcribes -> raw_text enters the existing
two-layer evaluation pipeline.
"""

import asyncio
import base64
import os
from typing import Optional

import httpx

# MIME types for the qwen_asr base64 data-URL input.
MIME_BY_EXT = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
    ".flac": "audio/flac",
    ".amr": "audio/amr",
    ".wma": "audio/x-ms-wma",
}

# qwen-asr input limit is 10MB *after* base64 (~33% inflation); keep raw < 7MB.
MAX_QWEN_ASR_BYTES = 7 * 1024 * 1024

DEFAULT_ASR_MODEL = {
    "openai": "whisper-1",
    "dashscope": "paraformer-realtime-v2",
    "qwen_asr": "qwen3-asr-flash",
}

# A realistic demo transcript for the 动物园 debate topics, used by the mock
# provider so the whole upload -> transcribe -> assess flow can be demoed
# offline / on GitHub Pages without any external API.
MOCK_TRANSCRIPT = (
    "我觉得应该把老鹰放回野外。因为老鹰本来就是天空的动物，"
    "关在动物园里就只能走来走去，很不自由。我同意它康复后放走，"
    "但是要确认它真的能自己抓食物再放，不然它又会受伤。"
)


class ASRError(Exception):
    """Raised when audio transcription fails."""


class ASRClient:
    SUPPORTED_PROVIDERS = ("mock", "qwen_asr", "openai", "dashscope")

    # paraformer-realtime-v2 supports pcm/wav/mp3/opus/speex/aac/amr.
    DASHSCOPE_FORMATS = {"pcm", "wav", "mp3", "opus", "speex", "aac", "amr"}

    def __init__(self, provider: Optional[str] = None) -> None:
        self.provider = (provider or os.getenv("ASR_PROVIDER") or "mock").lower().strip()
        if self.provider not in self.SUPPORTED_PROVIDERS:
            raise ASRError(f"unknown ASR_PROVIDER: {self.provider}")
        self.api_key = os.getenv("ASR_API_KEY") or os.getenv("LLM_API_KEY", "")
        self.base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
        self.model = os.getenv("ASR_MODEL") or DEFAULT_ASR_MODEL.get(self.provider, "")

    async def transcribe(self, file_path: str) -> str:
        if self.provider == "mock":
            return MOCK_TRANSCRIPT
        if self.provider == "qwen_asr":
            return await self._transcribe_qwen_asr(file_path)
        if self.provider == "openai":
            return await self._transcribe_openai(file_path)
        if self.provider == "dashscope":
            return await asyncio.to_thread(self._transcribe_dashscope, file_path)
        raise ASRError(f"unknown ASR_PROVIDER: {self.provider}")

    async def transcribe_segments(self, file_path: str) -> list[dict]:
        """Transcribe with per-sentence timestamps: [{start_ms, end_ms, text}].

        Hook for the classroom-recording flow (Scenario B). The mock provider
        returns plausible canned segments so the UI can be developed offline.
        """
        if self.provider == "mock":
            return self._mock_segments()
        if self.provider == "qwen_asr":
            # qwen-asr returns no per-sentence timestamps; single segment.
            text = await self._transcribe_qwen_asr(file_path)
            return [{"start_ms": 0, "end_ms": 0, "text": text}]
        if self.provider == "openai":
            return await self._transcribe_openai_segments(file_path)
        if self.provider == "dashscope":
            return await asyncio.to_thread(self._transcribe_dashscope_segments, file_path)
        raise ASRError(f"unknown ASR_PROVIDER: {self.provider}")

    def _mock_segments(self) -> list[dict]:
        sentences = [s.strip() + "。" for s in MOCK_TRANSCRIPT.split("。") if s.strip()]
        segments, cursor = [], 0
        for text in sentences:
            start_ms = cursor
            cursor += max(len(text) * 450, 1800)  # ~0.45s per char, min 1.8s
            segments.append({"start_ms": start_ms, "end_ms": cursor, "text": text})
        return segments

    async def _transcribe_qwen_asr(self, file_path: str) -> str:
        """DashScope qwen3-asr-flash via OpenAI-compatible chat/completions.

        Sends the local file as a base64 data URL (no public URL / OSS needed),
        reusing LLM_API_KEY + LLM_BASE_URL — one key covers LLM and ASR.
        """
        if not self.api_key:
            raise ASRError("ASR_API_KEY / LLM_API_KEY not configured")
        if not self.model:
            raise ASRError("ASR_MODEL not configured (expected e.g. qwen3-asr-flash)")
        size = os.path.getsize(file_path)
        if size > MAX_QWEN_ASR_BYTES:
            raise ASRError(
                f"音频过大（{size // 1024 // 1024}MB），qwen-asr 限制约 7MB 原始文件，请截短后重试"
            )
        mime = MIME_BY_EXT.get(os.path.splitext(file_path)[1].lower(), "application/octet-stream")
        with open(file_path, "rb") as fh:
            data_uri = f"data:{mime};base64,{base64.b64encode(fh.read()).decode()}"

        url = f"{self.base_url or 'https://dashscope.aliyuncs.com/compatible-mode/v1'}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_audio", "input_audio": {"data": data_uri}}
                    ],
                }
            ],
            "stream": False,
            # 课堂中文音频；不开 ITN，保留学生原话的数字表述
            "asr_options": {"language": "zh", "enable_itn": False},
        }
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
        if resp.status_code != 200:
            raise ASRError(f"qwen-asr failed: HTTP {resp.status_code} {resp.text[:200]}")
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError):
            raise ASRError("qwen-asr returned unexpected response shape")
        text = (content or "").strip()
        if not text:
            raise ASRError("qwen-asr returned empty text")
        return text

    async def _transcribe_openai(self, file_path: str) -> str:
        if not self.api_key:
            raise ASRError("ASR_API_KEY / LLM_API_KEY not configured")
        url = f"{self.base_url or 'https://api.openai.com/v1'}/audio/transcriptions"
        with open(file_path, "rb") as fh:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files={
                        "file": (os.path.basename(file_path), fh, "application/octet-stream")
                    },
                    data={"model": self.model},
                )
        if resp.status_code != 200:
            raise ASRError(f"openai transcription failed: HTTP {resp.status_code} {resp.text[:200]}")
        text = (resp.json().get("text") or "").strip()
        if not text:
            raise ASRError("openai transcription returned empty text")
        return text

    async def _transcribe_openai_segments(self, file_path: str) -> list[dict]:
        if not self.api_key:
            raise ASRError("ASR_API_KEY / LLM_API_KEY not configured")
        url = f"{self.base_url or 'https://api.openai.com/v1'}/audio/transcriptions"
        with open(file_path, "rb") as fh:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files={
                        "file": (os.path.basename(file_path), fh, "application/octet-stream")
                    },
                    data={"model": self.model, "response_format": "verbose_json"},
                )
        if resp.status_code != 200:
            raise ASRError(f"openai transcription failed: HTTP {resp.status_code} {resp.text[:200]}")
        payload = resp.json()
        segments = payload.get("segments") or []
        result = []
        for seg in segments:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            result.append({
                "start_ms": int(seg.get("start", 0) * 1000),
                "end_ms": int(seg.get("end", 0) * 1000),
                "text": text,
            })
        if not result:
            text = (payload.get("text") or "").strip()
            if text:
                result = [{"start_ms": 0, "end_ms": 0, "text": text}]
        if not result:
            raise ASRError("openai transcription returned empty segments")
        return result

    def _transcribe_dashscope(self, file_path: str) -> str:
        _, result = self._dashscope_call(file_path)
        sentences = result.get_sentence() or []
        text = "".join((s.get("text") or "") for s in sentences).strip()
        if not text:
            raise ASRError("dashscope ASR returned empty text")
        return text

    def _transcribe_dashscope_segments(self, file_path: str) -> list[dict]:
        _, result = self._dashscope_call(file_path)
        segments = []
        for sentence in result.get_sentence() or []:
            text = (sentence.get("text") or "").strip()
            if not text:
                continue
            segments.append({
                "start_ms": int(sentence.get("begin_time", 0)),
                "end_ms": int(sentence.get("end_time", 0)),
                "text": text,
            })
        if not segments:
            raise ASRError("dashscope ASR returned empty segments")
        return segments

    def _dashscope_call(self, file_path: str):
        """Non-streaming local-file recognition (see 百炼 paraformer Python SDK docs).

        Correct usage is `Recognition(model=..., format=..., sample_rate=...,
        callback=None).call(local_file_path)` — passing a local path via
        `file_urls` (the old code) only works for publicly reachable URLs.
        """
        try:
            import dashscope
            from dashscope.audio.asr import Recognition
        except ImportError:
            raise ASRError("dashscope SDK not installed — run: pip install dashscope")
        if not self.api_key:
            raise ASRError("ASR_API_KEY / LLM_API_KEY not configured")
        ext = os.path.splitext(file_path)[1].lstrip(".").lower()
        if ext not in self.DASHSCOPE_FORMATS:
            raise ASRError(
                f"dashscope paraformer does not support .{ext} "
                f"(supported: {sorted(self.DASHSCOPE_FORMATS)})"
            )
        dashscope.api_key = self.api_key
        recognition = Recognition(
            model=self.model,
            format=ext,
            sample_rate=16000,
            language_hints=["zh"],
            callback=None,
        )
        result = recognition.call(file_path)
        if result.status_code != 200:
            raise ASRError(
                f"dashscope ASR failed: {result.status_code} "
                f"{getattr(result, 'code', '')} {getattr(result, 'message', '')}"
            )
        return recognition, result
