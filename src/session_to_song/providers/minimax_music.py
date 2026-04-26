from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from .audio_utils import trim_audio_to_mp3
from .music_common import GeneratedAudio, MusicGenerationError

DEFAULT_MINIMAX_BASE_URL = "https://api.minimax.io"
DEFAULT_MINIMAX_MODEL = "music-2.5+"
DEFAULT_TIMEOUT_SECONDS = 120


def minimax_music_available() -> bool:
    return bool(os.getenv("MINIMAX_API_KEY", "").strip())


def _resolve_base_url() -> str:
    candidate = (os.getenv("MINIMAX_BASE_URL") or "").strip()
    if not candidate:
        return DEFAULT_MINIMAX_BASE_URL
    parsed = urllib_parse.urlparse(candidate)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return DEFAULT_MINIMAX_BASE_URL


def _resolve_model(preferred_model: str | None = None) -> str:
    candidate = (preferred_model or "").strip()
    if not candidate:
        return DEFAULT_MINIMAX_MODEL
    if "/" in candidate:
        candidate = candidate.split("/", 1)[1]
    return candidate or DEFAULT_MINIMAX_MODEL


def _build_prompt(prompt: str, duration_seconds: int) -> str:
    return f"{prompt.strip()}\n\nTarget duration: about {max(1, int(duration_seconds))} seconds."


def _assert_base_response(payload: dict) -> None:
    base_resp = payload.get("base_resp")
    if not isinstance(base_resp, dict):
        return
    status_code = base_resp.get("status_code")
    if isinstance(status_code, int) and status_code != 0:
        raise MusicGenerationError(
            f"MiniMax music generation failed ({status_code}): {base_resp.get('status_msg') or 'unknown error'}"
        )


def _is_remote_url(value: str | None) -> bool:
    return bool(value and value.strip().lower().startswith(("http://", "https://")))


def _decode_possible_binary(data: str) -> bytes:
    trimmed = data.strip()
    if not trimmed:
        raise MusicGenerationError("MiniMax returned an empty inline audio payload.")
    if all(ch in "0123456789abcdefABCDEF" for ch in trimmed) and len(trimmed) % 2 == 0:
        return bytes.fromhex(trimmed)
    try:
        return base64.b64decode(trimmed, validate=False)
    except Exception as exc:  # pragma: no cover - defensive
        raise MusicGenerationError("MiniMax returned an invalid inline audio payload.") from exc


def _decode_possible_text(data: str | None) -> str | None:
    trimmed = (data or "").strip()
    if not trimmed:
        return None
    if all(ch in "0123456789abcdefABCDEF" for ch in trimmed) and len(trimmed) % 2 == 0:
        try:
            return bytes.fromhex(trimmed).decode("utf-8").strip() or None
        except Exception:
            return trimmed
    return trimmed


def _json_request(url: str, payload: dict, headers: dict[str, str], timeout_seconds: int) -> dict:
    request = urllib_request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # pragma: no cover - network failure path
        raise MusicGenerationError(f"MiniMax music request failed: {exc}") from exc


def _download_bytes(url: str, timeout_seconds: int) -> tuple[bytes, str]:
    try:
        with urllib_request.urlopen(url, timeout=timeout_seconds) as response:
            mime_type = response.headers.get("Content-Type") or "audio/mpeg"
            return response.read(), mime_type
    except Exception as exc:  # pragma: no cover - network failure path
        raise MusicGenerationError(f"MiniMax audio download failed: {exc}") from exc


def generate_minimax_music(*, prompt: str, out_dir: Path, duration_seconds: int, preferred_model: str | None = None) -> GeneratedAudio:
    api_key = (os.getenv("MINIMAX_API_KEY") or "").strip()
    if not api_key:
        raise MusicGenerationError("MiniMax music generation is not configured. Set MINIMAX_API_KEY.")

    model = _resolve_model(preferred_model)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "generated_audio_raw.mp3"
    final_path = out_dir / "generated_audio.mp3"
    timeout_seconds = int((os.getenv("MINIMAX_TIMEOUT_SECONDS") or str(DEFAULT_TIMEOUT_SECONDS)).strip() or DEFAULT_TIMEOUT_SECONDS)

    payload = _json_request(
        f"{_resolve_base_url()}/v1/music_generation",
        {
            "model": model,
            "prompt": _build_prompt(prompt, duration_seconds),
            "lyrics_optimizer": True,
            "output_format": "url",
            "audio_setting": {
                "sample_rate": 44100,
                "bitrate": 256000,
                "format": "mp3",
            },
        },
        {"Authorization": f"Bearer {api_key}"},
        timeout_seconds,
    )
    _assert_base_response(payload)

    audio_candidate = str(payload.get("audio") or payload.get("data", {}).get("audio") or "").strip() or None
    audio_url = (
        str(payload.get("audio_url") or payload.get("data", {}).get("audio_url") or "").strip()
        or (audio_candidate if _is_remote_url(audio_candidate) else None)
    )
    inline_audio = None if _is_remote_url(audio_candidate) else audio_candidate
    lyrics = _decode_possible_text(payload.get("lyrics") or payload.get("data", {}).get("lyrics"))

    if audio_url:
        audio_bytes, mime_type = _download_bytes(audio_url, timeout_seconds)
        raw_path.write_bytes(audio_bytes)
    elif inline_audio:
        raw_path.write_bytes(_decode_possible_binary(inline_audio))
        mime_type = "audio/mpeg"
    else:
        raise MusicGenerationError("MiniMax music generation response missing audio output.")

    trim_audio_to_mp3(raw_path, final_path, duration_seconds)
    notes: list[str] = []
    task_id = str(payload.get("task_id") or "").strip()
    if task_id:
        notes.append(f"task_id={task_id}")
    if lyrics:
        notes.append(f"lyrics:\n{lyrics}")
    return GeneratedAudio(
        provider="minimax",
        model=model,
        mime_type="audio/mpeg",
        path=final_path,
        prompt_notes="\n\n".join(notes) or None,
    )
