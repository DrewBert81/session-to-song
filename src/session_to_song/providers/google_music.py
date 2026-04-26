from __future__ import annotations

import os
from pathlib import Path

from .audio_utils import trim_audio_to_mp3
from .music_common import GeneratedAudio, MusicGenerationError


def google_music_available() -> bool:
    return bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))


def _resolve_model(preferred_model: str | None = None) -> str:
    candidate = (preferred_model or "").strip()
    if "lyria" in candidate.lower():
        return candidate if candidate.startswith("models/") else f"models/{candidate}"
    return "models/lyria-3-pro-preview"


def _extract_audio_and_notes(response) -> tuple[bytes, str, str | None]:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        feedback = getattr(response, "prompt_feedback", None)
        if feedback and getattr(feedback, "block_reason", None):
            reason = str(feedback.block_reason)
            if "PROHIBITED" in reason.upper():
                raise MusicGenerationError("Generation blocked. Google's Lyria API prohibits imitating specific, real-world artists or copyrighted IP.")
            raise MusicGenerationError(f"Generation blocked by safety filters: {reason}")
        raise MusicGenerationError("No music candidates returned.")

    parts = getattr(getattr(candidates[0], "content", None), "parts", None) or []
    notes: list[str] = []
    for part in parts:
        inline = getattr(part, "inline_data", None)
        if inline and getattr(inline, "data", None):
            return inline.data, inline.mime_type or "audio/mpeg", "\n\n".join(notes).strip() or None
        text = getattr(part, "text", None)
        if text:
            notes.append(text)

    raise MusicGenerationError("Model returned no audio data.")


def generate_google_music(*, prompt: str, out_dir: Path, duration_seconds: int, preferred_model: str | None = None) -> GeneratedAudio:
    if not google_music_available():
        raise MusicGenerationError("Google/Gemini music generation is not configured.")

    try:
        from google import genai
        from google.genai import types
    except Exception as exc:  # pragma: no cover - optional dependency
        raise MusicGenerationError("google-genai is not installed.") from exc

    model = _resolve_model(preferred_model)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "generated_audio_raw.mp3"
    final_path = out_dir / "generated_audio.mp3"

    client = genai.Client()
    normalized_prompt = prompt.strip()
    vocal_instruction = (
        "Create a short vocal song, not an instrumental bed. "
        "Use clear sung or rapped lead vocals with audible words. "
        "Start the lead vocal almost immediately, within the first 1-2 seconds; avoid long instrumental intros. "
        "Treat any provided lyrics or backbone text as mandatory content, not optional inspiration. "
        f"Keep it concise, memorable, and suitable for a {duration_seconds}-second final export."
    )
    response = client.models.generate_content(
        model=model,
        contents=f"{vocal_instruction}\n\nDirection and required lyrical backbone:\n\n{normalized_prompt}",
        config=types.GenerateContentConfig(response_modalities=["AUDIO"]),
    )
    audio_bytes, mime_type, notes = _extract_audio_and_notes(response)
    raw_path.write_bytes(audio_bytes)
    trimmed = trim_audio_to_mp3(raw_path, final_path, duration_seconds)
    return GeneratedAudio(
        provider="google",
        model=model,
        mime_type=mime_type,
        path=trimmed,
        prompt_notes=notes,
    )
