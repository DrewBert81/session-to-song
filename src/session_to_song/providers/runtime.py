from __future__ import annotations

import json
import os
import re
from urllib import request as urllib_request

from ..domain import RunRequest, SessionMaterial, StylePreset, UserConfig
from .status import detect_provider_status


class LLMRuntimeError(RuntimeError):
    pass


def _post_json(url: str, payload: dict, headers: dict[str, str], timeout: int = 45) -> dict:
    req = urllib_request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _extract_openai_content(response: dict) -> str:
    try:
        return response["choices"][0]["message"]["content"]
    except Exception as exc:  # pragma: no cover
        raise LLMRuntimeError(f"Bad LLM response shape: {exc}") from exc


def _parse_artifact_json(content: str) -> dict[str, str]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    if "{" in cleaned and "}" in cleaned:
        cleaned = cleaned[cleaned.find("{") : cleaned.rfind("}") + 1]
    data = json.loads(cleaned)
    aliases = {
        "pulse": ["pulse", "summary"],
        "lyrics": ["lyrics", "speech", "script"],
        "music_prompt": ["music_prompt", "prompt", "audio_prompt"],
    }
    normalized: dict[str, str] = {}
    for target, keys in aliases.items():
        value = next((data.get(key) for key in keys if isinstance(data.get(key), str) and data.get(key).strip()), None)
        if not value:
            raise LLMRuntimeError("LLM output missing required fields")
        normalized[target] = value.strip()
    return normalized


def _content_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+", text.lower())
        if len(token) >= 5 and token not in {"there", "their", "about", "would", "could", "should", "focus", "today", "yesterday", "where", "which", "while", "brand", "anthem", "dream", "momentum"}
    }


def _ensure_specific_enough(artifacts: dict[str, str], facts: list[str]) -> None:
    fact_tokens = _content_tokens("\n".join(facts[:6]))
    if not fact_tokens:
        return
    output_tokens = _content_tokens("\n".join([artifacts.get("pulse", ""), artifacts.get("lyrics", ""), artifacts.get("music_prompt", "")]))
    overlap = fact_tokens & output_tokens
    if len(overlap) < 2:
        raise LLMRuntimeError("LLM output was too generic and did not carry enough source facts")


def llm_artifact_synthesis_available(user_config: UserConfig) -> bool:
    status = detect_provider_status(
        llm_provider=user_config.llm_provider,
        llm_model=user_config.llm_model,
        music_provider=user_config.music_provider,
        music_model=user_config.music_model,
    )
    return status.llm.available and status.llm.runtime_supported and status.llm.provider in {"openrouter", "openai", "google"}


def synthesize_artifacts_via_llm(
    *,
    material: SessionMaterial,
    user_config: UserConfig,
    request: RunRequest,
    style: StylePreset,
    fallback_pulse: str,
    fallback_lyrics: str,
    fallback_music_prompt: str,
) -> dict[str, str]:
    focus = (request.resolved_focus or "").strip()
    sound_reference = (request.sound_reference or "").strip()
    artifact_use = request.resolved_use
    def clean_fact_for_writer(value: object) -> str:
        line = " ".join(str(value).split())
        line = re.sub(r"`?\b(?:src|server|webui|tests|docs|scripts|content)/[^\s`]+`?:\s*", "", line, flags=re.IGNORECASE)
        line = re.sub(r"`?\b[a-z0-9_-]+\.(?:tsx|ts|jsx|js|py|md|css|json)`?:\s*", "", line, flags=re.IGNORECASE)
        line = re.sub(r"\b[0-9a-f]{7,40}\b", "", line, flags=re.IGNORECASE)
        line = re.sub(r"\s{2,}", " ", line).strip(" -•,.;")
        return line

    cleaned_lines = []
    for bucket in (material.wins, material.blockers, material.next_actions):
        for item in bucket:
            line = clean_fact_for_writer(item)
            if line and line not in cleaned_lines:
                cleaned_lines.append(line)
    for item in material.metadata.get("decisions", []) if isinstance(material.metadata.get("decisions"), list) else []:
        line = clean_fact_for_writer(item)
        if line and line not in cleaned_lines:
            cleaned_lines.append(line)
    facts_block = "\n".join(f"- {line}" for line in cleaned_lines[:8]) or "- No structured facts extracted; infer carefully from raw text."
    dream_context = str(material.metadata.get("dream_context") or "").strip()
    memory_context = str(material.metadata.get("memory_context") or "").strip()
    prompt = f"""
You are generating one short artifact package for a product called session-to-song.

Return ONLY valid JSON with this exact shape:
{{
  "pulse": "string",
  "lyrics": "string",
  "music_prompt": "string"
}}

Rules:
- Make the output materially reflect the user's focus.
- Treat Sound reference as sound design only; do not make it the lyrical subject.
- Do not just restate the same template with swapped nouns.
- Keep it concise, high-signal, and specific to the source text.
- Name concrete achievements, changes, fixes, decisions, or next moves from the source. Avoid vague lines like "we moved forward" or "momentum is real" unless paired with specifics.
- Respect use={artifact_use}, genre={style.label}, duration_seconds={request.duration_seconds or user_config.duration_seconds}.
- Use decides content. Genre decides sound.
- If the focus is strategic/business-oriented, answer that focus inside the artifact instead of forcing a generic recap.
- For alarm: this is mission re-entry after sleep. It must orient the listener into today, not simply celebrate what shipped.
- For alarm: use yesterday as context, then point at today’s first move and why getting up matters.
- For alarm: avoid phrases like "what shipped and why it matters" unless the source itself says that.
- For reminder: this is a status/reminder artifact. It should preserve state, unresolved tension, decisions, and what must not be forgotten. It should not sound like a victory lap.
- For celebrate: this is payoff. Make completed work feel earned, replayable, and specific.
- For next_steps: this is a launch command. Prioritize the next concrete move over recap.
- The pulse should be 3-5 short bullet lines.
- The lyrics field may be spoken-word / structured lines, not necessarily a song chorus.
- The music_prompt should be usable as a generation prompt and should mention the focus explicitly.
- If the focus mentions a specific artist or real person, describe their musical style and instruments in the music_prompt rather than naming them directly, to avoid triggering copyright safety filters.
- If Sound reference is present, it should OVERRIDE the default Genre sound. The music_prompt MUST be heavily tailored to that sound's vibe and instrumentation without naming specific real artists.
- Start the lyrics with a creative, AI-generated title block (e.g. `[<Creative Title> | genre={style.key}]`). Do NOT just echo the raw title or focus.
- Write a custom, punchy intro line. Do not use generic filler.
- The lyrics must open immediately with content; no slow intro, no scene-setting fluff, no empty hype.
- Use at least 2 concrete facts from Structured facts / Wins / Blockers / Next actions when they are available.
- Do NOT mention internal product/tool/framework words unless the user explicitly wants them.
- Avoid words like: OpenClaw, config, genre set, style set, generate, validate, edge cases, vertical slice, Python.
- Rewrite technical notes into human language before writing lyrics.
- Never include file paths, filenames, component names, commit hashes, markdown mojibake, or raw developer changelog syntax in lyrics.
- If a fact contains a path like src/components/foo.tsx, ignore the path and sing only the human product change.
- For rap specifically: write in bars with punch, compression, momentum, and at least light rhyme/internal rhythm. It should sound performable, not like a checklist.
- For rap specifically: make it feel like a wake-up banger that makes the listener want to get up and finish the repo/project.
- For rap specifically: prefer direct verbs, concrete nouns, short bars, and motivational lift over soft reflection.
- Use strong active language; avoid generic lines like "we moved forward" when a more specific achievement is available.
- Never output lines that read like UI labels, bullet summaries, or developer notes.
- If the available facts are thin, infer carefully, but still prefer concrete detail over abstraction.

Artifact use:
{artifact_use}

User focus:
{focus or '(none)'}

Sound reference:
{sound_reference or '(none)'}

Genre:
- key: {style.key}
- label: {style.label}
- sound: {style.music_prompt_seed}
- intro: {style.intro_seed}
- hook: {style.hook_seed}

Source title: {material.title}
Project: {material.project or '(none)'}
Structured facts to work from:
{facts_block}

Dream context:
{dream_context or '(none)'}

Recent memory context:
{memory_context or '(none)'}

Wins: {json.dumps(material.wins)}
Blockers: {json.dumps(material.blockers)}
Next actions: {json.dumps(material.next_actions)}
Decisions: {json.dumps(material.metadata.get("decisions", []))}
Raw text (truncated for cost/context limits):
{material.raw_text[-20000:] if len(material.raw_text) > 20000 else material.raw_text}

Fallback reference only for rough factual orientation. Do not mimic its wording or structure:
PULSE:
{fallback_pulse}

MUSIC PROMPT FACTS:
{fallback_music_prompt}
""".strip()

    def run_once(instructions: str, temperature: float) -> dict[str, str]:
        provider_status = detect_provider_status(
            llm_provider=user_config.llm_provider,
            llm_model=user_config.llm_model,
            music_provider=user_config.music_provider,
            music_model=user_config.music_model,
        )
        resolved = provider_status.llm
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        google_key = os.getenv("GOOGLE_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY", "").strip()

        if resolved.provider == "openrouter" and openrouter_key:
            response = _post_json(
                "https://openrouter.ai/api/v1/chat/completions",
                {
                    "model": resolved.model,
                    "messages": [
                        {"role": "system", "content": instructions},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": temperature,
                },
                {"Authorization": f"Bearer {openrouter_key}"},
            )
            content = _extract_openai_content(response)
        elif resolved.provider == "openai" and openai_key:
            response = _post_json(
                "https://api.openai.com/v1/chat/completions",
                {
                    "model": resolved.model,
                    "messages": [
                        {"role": "system", "content": instructions},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": temperature,
                    "response_format": {"type": "json_object"},
                },
                {"Authorization": f"Bearer {openai_key}"},
            )
            content = _extract_openai_content(response)
        elif resolved.provider == "google" and google_key:
            response = _post_json(
                f"https://generativelanguage.googleapis.com/v1beta/models/{resolved.model}:generateContent?key={google_key}",
                {
                    "systemInstruction": {"parts": [{"text": instructions}]},
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"}
                },
                {}
            )
            try:
                content = response["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as exc:
                raise LLMRuntimeError(f"Bad LLM response shape: {exc}") from exc
        else:  # pragma: no cover
            raise LLMRuntimeError(provider_status.llm.message or f"No supported live LLM credentials for provider: {resolved.provider}")
        artifacts = _parse_artifact_json(content)
        _ensure_specific_enough(artifacts, cleaned_lines)
        return artifacts

    errors: list[str] = []
    attempts = [
        ("You are a precise artifact generator. Output strict JSON only.", 0.8),
        ("Output strict JSON only with keys pulse, lyrics, music_prompt. No markdown, no commentary, no extra keys.", 0.2),
        ("Return compact JSON with exactly three string fields: pulse, lyrics, music_prompt. Every field is required. No prose outside JSON.", 0.1),
    ]
    for instructions, temperature in attempts:
        try:
            return run_once(instructions, temperature)
        except Exception as exc:
            errors.append(str(exc))
    raise LLMRuntimeError(" | ".join(errors) or "LLM synthesis failed")
