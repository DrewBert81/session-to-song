from __future__ import annotations

import re
import secrets

from ..domain import RunRequest, SessionMaterial, SongArtifacts, StylePreset, UserConfig
from ..styles import get_style_preset
from ..providers import detect_provider_status, llm_artifact_synthesis_available, synthesize_artifacts_via_llm

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "in", "into", "is", "it",
    "of", "on", "or", "that", "the", "to", "up", "was", "we", "were", "with", "today", "this", "our",
    "openclaw", "session", "sessions", "song", "songs", "session-to-song", "product", "curated", "recent",
    "commits", "commit", "github", "repo", "memory", "source", "sources", "what", "should", "focus",
    "project", "build", "built", "drew", "mode", "style", "use", "angle", "copy", "labels",
}

JARGON_PATTERNS = [
    r"\bopenclaw\b",
    r"\bmemory\b",
    r"\bconfig show\b",
    r"\bgenre set\b",
    r"\bstyle set\b",
    r"\binit\b",
    r"\bgenerate\b",
    r"\bvalidate(?:ing|d)?\b",
    r"\bedge cases?\b",
    r"\bvertical slice\b",
    r"\bweb flow\b",
    r"\bsetup flow\b",
    r"\bllm\b",
    r"\bpython\b",
]

HUMAN_REWRITES = {
    "setup flow": "the flow",
    "genre set": "the controls",
    "config show": "the controls",
    "validating the new flow": "proving the new flow works",
    "tightening edge cases": "cleaning up the rough edges",
    "vertical slice": "working version",
    "web flow": "the experience",
    "drew approved": "build mode was approved",
    "drew identified": "the product copy showed",
}

USE_HELPERS = {
    "alarm": {
        "pulse_label": "Re-entry",
        "bridge": "Wake back into the thread: yesterday is context, today is the mission.",
        "music": "Make it feel like mission re-entry after sleep: orient the listener, name what changed, then point at today's first move. Not a victory lap.",
        "fallback_intro": "Eyes open, thread intact, yesterday hands today the map",
    },
    "reminder": {
        "pulse_label": "State check",
        "bridge": "Hold the map steady: state, tension, decision, and next reminder.",
        "music": "Make it feel like a crisp project status reminder: less hype, more clarity, unresolved tension, and what must not be forgotten.",
        "fallback_intro": "Status light on, keep the thread from slipping",
    },
    "celebrate": {
        "pulse_label": "Win replay",
        "bridge": "Turn completed work into a replayable win without losing the specifics.",
        "music": "Make it feel like payoff for real completed work: what landed, what changed, and why the win is worth replaying.",
        "fallback_intro": "Win on the board, turn the proof up loud",
    },
    "next_steps": {
        "pulse_label": "Move now",
        "bridge": "Cut through the recap: one clear next move, one reason to act.",
        "music": "Create urgency around the next concrete action. The track should feel like a launch command, not a recap.",
        "fallback_intro": "No more circling, name the move and hit it",
    },
}

# Variant fallback phrases used by the template path when source facts are empty.
# Each list has four options so consecutive runs with no new session content still
# produce noticeably different lyrics.
_VERSE_FALLBACKS_A = [
    "we moved the work forward fast and clean",
    "the signal came through and the output landed",
    "effort stacked and the project took its shape",
    "the work held up and the record is real",
]
_VERSE_FALLBACKS_B = [
    "pressure showed up but direction stayed clear",
    "obstacles came and the thread held steady",
    "the noise faded and the purpose came through",
    "friction burned off and the path stayed lit",
]
_VERSE_FALLBACKS_C = [
    "next move is the highest leverage one",
    "the next step is already in reach",
    "what happens next is the only move that counts",
    "one more push and the gap closes fast",
]
_ALARM_FALLBACKS_A = [
    "Wake back in, find the thread, choose the first move",
    "Eyes open, orient fast, yesterday hands you the map",
    "Back in the mission, thread intact, first move is clear",
    "Wake up sharp, the context is loaded, start with one step",
]
_REMINDER_FALLBACKS_A = [
    "State check, hold the map, don't lose the thread",
    "Status is alive, tension is real, keep the line clear",
    "Map is steady, decision is waiting, stay on it",
    "Thread is live, state is known, don't let it slip",
]
_NEXT_STEPS_FALLBACKS_A = [
    "Move now, pick the lever, make the next cut",
    "Pick the move, close the gap, keep the pressure on",
    "The next action is the only thing that counts now",
    "One move, one moment, let the work speak forward",
]
_HUMANIZE_FALLBACKS = [
    "we moved the work forward with real momentum",
    "the work landed and the progress is real",
    "the thread held and the output is solid",
    "forward motion held and the result is clear",
]


def _variation_index() -> int:
    """Return a random index 0-3 for selecting among fallback phrase variants."""
    return secrets.randbelow(len(_VERSE_FALLBACKS_A))


def _top_keywords(text: str, limit: int = 6) -> list[str]:
    counts: dict[str, int] = {}
    for token in re.findall(r"[A-Za-z][A-Za-z0-9'-]+", text.lower()):
        if token in STOPWORDS or len(token) < 4:
            continue
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [word for word, _ in ranked[:limit]]


def _strip_commit_noise(line: str) -> str:
    cleaned = re.sub(r"\b[0-9a-f]{7,40}\b", "", line, flags=re.IGNORECASE)
    cleaned = re.sub(r"\brecent commits?:?\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(feat|fix|docs|chore|refactor|test):\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\|\s*", ", ", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip(" ,.-") or line


def _compress(line: str, max_words: int = 10) -> str:
    line = _strip_commit_noise(line)
    words = line.split()
    clipped = words[:max_words]
    if len(words) > max_words:
        clipped.append("...")
    return " ".join(clipped)


def _humanize_line(line: str) -> str:
    cleaned = " ".join(line.strip().split())
    cleaned = re.sub(r"`?\b(?:src|server|webui|tests|docs|scripts|content)/[^\s`]+`?:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"`?\b[a-z0-9_-]+\.(?:tsx|ts|jsx|js|py|md|css|json)`?:\s*", "", cleaned, flags=re.IGNORECASE)
    lowered = cleaned.lower()
    for old, new in HUMAN_REWRITES.items():
        lowered = lowered.replace(old, new)
    cleaned = lowered
    cleaned = _strip_commit_noise(cleaned)
    for pattern in JARGON_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.-")
    if not cleaned:
        return _HUMANIZE_FALLBACKS[_variation_index()]
    return cleaned


def _best_lines(material: SessionMaterial, limit: int = 4) -> list[str]:
    lines: list[str] = []
    for bucket in (material.wins, material.blockers, material.next_actions):
        for item in bucket:
            human = _humanize_line(item)
            if human and human not in lines:
                lines.append(human)
    return lines[:limit]


def _focus_line(focus: str | None) -> str | None:
    if not focus:
        return None
    if re.match(r"(?i)^\s*(sound reference|artist style)\s*:", focus):
        return None
    return _compress(focus.strip().rstrip("?"), 12)


def summarize_material(material: SessionMaterial, use: str = "alarm", focus: str | None = None) -> str:
    keyword_source = material.raw_text + (f"\n{focus}" if focus else "")
    keywords = ", ".join(_top_keywords(keyword_source)) or "focus"
    helper = USE_HELPERS.get(use, USE_HELPERS["alarm"])
    lines: list[str] = []
    focus_line = _focus_line(focus)

    if use == "alarm":
        if material.wins:
            lines.append(f"• Yesterday's signal: {_compress(_humanize_line(material.wins[0]))}")
        if material.next_actions:
            lines.append(f"• First move today: {_compress(_humanize_line(material.next_actions[0]))}")
        elif len(material.wins) > 1:
            lines.append(f"• Carry forward: {_compress(_humanize_line(material.wins[1]))}")
        lines.append("• Wake cue: re-enter the work with orientation, not hype.")
    elif use == "reminder":
        if material.wins:
            lines.append(f"• Current state: {_compress(_humanize_line(material.wins[0]))}")
        if material.blockers:
            lines.append(f"• Don't forget: {_compress(_humanize_line(material.blockers[0]))}")
        elif material.next_actions:
            lines.append(f"• Remember next: {_compress(_humanize_line(material.next_actions[0]))}")
        lines.append("• Reminder cue: keep the map clear and the tension visible.")
    elif use == "celebrate":
        if material.wins:
            lines.append(f"• Win: {_compress(_humanize_line(material.wins[0]))}")
        if len(material.wins) > 1:
            lines.append(f"• Change: {_compress(_humanize_line(material.wins[1]))}")
        lines.append("• Replay cue: make the completed work feel earned.")
    elif use == "next_steps":
        if material.next_actions:
            lines.append(f"• Move: {_compress(_humanize_line(material.next_actions[0]))}")
        elif material.wins:
            lines.append(f"• From here: {_compress(_humanize_line(material.wins[0]))}")
        if material.blockers:
            lines.append(f"• Watch: {_compress(_humanize_line(material.blockers[0]))}")
        lines.append("• Launch cue: less recap, more action.")

    if focus_line and use not in {"alarm", "reminder", "celebrate", "next_steps"}:
        lines.insert(0, f"• Focus: {focus_line}")
    lines.append(f"• {helper['pulse_label']}: {keywords}")
    return "\n".join(lines)


def _hook_from_keywords(keywords: list[str], style: StylePreset, focus: str | None = None) -> str:
    focus_line = _focus_line(focus)
    if focus_line:
        return f"{style.hook_seed} | {focus_line}"
    if not keywords:
        return style.hook_seed
    return f"{style.hook_seed} | {', '.join(keywords[:3])}"


def build_lyrics(material: SessionMaterial, pulse: str, request: RunRequest, style: StylePreset) -> str:
    focus = request.resolved_focus
    use = request.resolved_use
    keyword_source = material.raw_text + (f"\n{focus}" if focus else "")
    keywords = _top_keywords(keyword_source)
    focus_line = _focus_line(focus)
    best = _best_lines(material)
    _v = _variation_index()
    verse_a = _compress(best[0] if len(best) > 0 else _VERSE_FALLBACKS_A[_v], 12)
    verse_b = _compress(best[1] if len(best) > 1 else _VERSE_FALLBACKS_B[_v], 12)
    verse_c = _compress(best[2] if len(best) > 2 else _VERSE_FALLBACKS_C[_v], 12)
    bridge = USE_HELPERS.get(use, USE_HELPERS["alarm"])["bridge"]

    if use == "alarm":
        verse_a = f"Wake back in: {_compress(_humanize_line(material.wins[0]), 12)}" if material.wins else _ALARM_FALLBACKS_A[_v]
        verse_b = f"First move: {_compress(_humanize_line(material.next_actions[0]), 12)}" if material.next_actions else verse_b
    elif use == "reminder":
        verse_a = f"State check: {_compress(_humanize_line(material.wins[0]), 12)}" if material.wins else _REMINDER_FALLBACKS_A[_v]
        verse_b = f"Remember: {_compress(_humanize_line((material.blockers or material.next_actions or ['keep the next decision visible'])[0]), 12)}"
    elif use == "celebrate" and material.wins:
        verse_a = f"Win replay: {_compress(_humanize_line(material.wins[0]), 12)}"
    elif use == "next_steps":
        verse_a = f"Move now: {_compress(_humanize_line(material.next_actions[0]), 12)}" if material.next_actions else _NEXT_STEPS_FALLBACKS_A[_v]

    duration_seconds = request.duration_seconds or 45
    intro_line = USE_HELPERS.get(use, USE_HELPERS["alarm"])["fallback_intro"]
    lines = [
        f"[{use.replace('_', ' ').title()} Track | genre={style.key} | ~{duration_seconds}s]",
        "",
        "[Intro]",
        intro_line,
    ]
    if focus_line:
        lines += ["", "[Focus]", focus_line]
    lines += [
        "",
        "[Verse]",
        verse_a,
        verse_b,
        verse_c,
        (f"Keep it aimed: {focus_line}" if focus_line and use == "next_steps" else "Hold the line and keep the point sharp"),
        bridge,
        "",
        "[Hook]",
        _hook_from_keywords(keywords, style, focus),
        "",
        "[Reference Pulse]",
        pulse,
    ]
    return "\n".join(lines)


def build_music_prompt(material: SessionMaterial, lyrics: str, request: RunRequest, style: StylePreset) -> str:
    focus = request.resolved_focus
    sound_reference = (request.sound_reference or "").strip()
    use = request.resolved_use
    keyword_source = material.raw_text + (f"\n{focus}" if focus else "")
    keywords = ", ".join(_top_keywords(keyword_source)) or "focused work"
    project_phrase = f" for project {material.project}" if material.project else ""
    focus_phrase = f" Focus: {focus}. Treat it as the main emphasis, not a footnote." if _focus_line(focus) else ""
    sound_phrase = f" Sound reference: {sound_reference}. Treat this as sound design only; do not make it the lyrical subject." if sound_reference else ""
    use_phrase = USE_HELPERS.get(use, USE_HELPERS["alarm"])["music"]
    duration_seconds = request.duration_seconds or 45
    factual_lines = []
    for item in (material.wins + material.blockers + material.next_actions)[:4]:
        factual = _compress(_humanize_line(item), 14)
        if factual and factual not in factual_lines:
            factual_lines.append(factual)
    fact_block = (" Concrete facts to include: " + " | ".join(factual_lines) + ".") if factual_lines else ""
    return (
        f"Create a {duration_seconds}-second {use.replace('_', ' ')} track{project_phrase}. "
        f"Duration target: {duration_seconds} seconds; do not deliver a full-length song unless explicitly requested. "
        f"Genre: {style.label}. "
        f"Sound guidance: {style.music_prompt_seed}. "
        "Start vocals immediately in the first bar; avoid a long instrumental intro. "
        f"Use guidance: {use_phrase} "
        f"Theme keywords: {keywords}."
        f"{fact_block}"
        f"{focus_phrase}{sound_phrase} "
        "Keep it catchy, short, PG, and suitable for chat delivery. Use these lyrics as the backbone:\n\n"
        f"{lyrics}\n\n"
        "End with a clean sting, not a long fade."
    )


def build_from_material(material: SessionMaterial, user_config: UserConfig, request: RunRequest, previous_lyrics: str | None = None) -> SongArtifacts:
    style = get_style_preset(request.genre or user_config.default_genre)
    pulse = summarize_material(material, use=request.resolved_use, focus=request.resolved_focus)
    lyrics = build_lyrics(material, pulse, request, style)
    music_prompt = build_music_prompt(material, lyrics, request, style)
    provider_status = detect_provider_status(
        llm_provider=user_config.llm_provider,
        llm_model=user_config.llm_model,
        music_provider=user_config.music_provider,
        music_model=user_config.music_model,
    )
    generation_mode = "template"
    generation_error = None
    if llm_artifact_synthesis_available(user_config):
        try:
            generated = synthesize_artifacts_via_llm(
                material=material,
                user_config=user_config,
                request=request,
                style=style,
                fallback_pulse=pulse,
                fallback_lyrics=lyrics,
                fallback_music_prompt=music_prompt,
                previous_lyrics=previous_lyrics,
            )
            pulse = generated["pulse"]
            lyrics = generated["lyrics"]
            music_prompt = generated["music_prompt"]
            generation_mode = "llm"
        except Exception as exc:
            generation_mode = "template_fallback"
            generation_error = str(exc)
    manifest = {
        "use": request.resolved_use,
        "genre": style.key,
        "delivery": request.delivery or user_config.delivery,
        "duration_seconds": request.duration_seconds or user_config.duration_seconds,
        "input_source": material.source,
        "source_mode": request.source_mode,
        "source_session_key": material.metadata.get("session_key"),
        "project": material.project,
        "title": material.title,
        "focus": request.resolved_focus,
        "generation_mode": generation_mode,
        "generation_error": generation_error,
        "llm": {
            "configured_provider": user_config.llm_provider,
            "configured_model": user_config.llm_model,
            "provider": provider_status.llm.provider,
            "model": provider_status.llm.model,
            "source": provider_status.llm.source,
            "available": provider_status.llm.available,
            "runtime_supported": provider_status.llm.runtime_supported,
        },
        "music": {
            "configured_provider": user_config.music_provider,
            "configured_model": user_config.music_model,
            "provider": provider_status.music.provider,
            "model": provider_status.music.model,
            "source": provider_status.music.source,
            "available": provider_status.music.available,
            "runtime_supported": provider_status.music.runtime_supported,
        },
        "keywords": _top_keywords(material.raw_text + (f'\n{request.resolved_focus}' if request.resolved_focus else '')),
        "mode": request.mode,
        "style": request.style,
        "question": request.question,
        "sound_reference": request.sound_reference,
    }
    return SongArtifacts(pulse=pulse, lyrics=lyrics, music_prompt=music_prompt, manifest=manifest)
