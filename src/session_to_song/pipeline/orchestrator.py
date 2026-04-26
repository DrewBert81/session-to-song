from __future__ import annotations

import re

from ..domain import RunRequest, SessionMaterial, SongArtifacts, StylePreset, UserConfig
from ..styles import get_style_preset
from ..providers import detect_provider_status, llm_artifact_synthesis_available, synthesize_artifacts_via_llm

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "in", "into", "is", "it",
    "of", "on", "or", "that", "the", "to", "up", "was", "we", "were", "with", "today", "this", "our",
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
}

USE_HELPERS = {
    "alarm": {
        "pulse_label": "Momentum",
        "bridge": "Remember what you built. Feel where the mission is pointing next.",
        "music": "Make it feel like waking back into the mission: what happened yesterday, what matters now, and where today is headed.",
    },
    "reminder": {
        "pulse_label": "Direction",
        "bridge": "State, change, direction, and tension all stay clear.",
        "music": "Favor clarity about project state and direction over victory framing.",
    },
    "celebrate": {
        "pulse_label": "Payoff",
        "bridge": "Name what shipped, what changed, and why it matters.",
        "music": "Make it feel like a payoff for real completed work, not abstract hype.",
    },
    "next_steps": {
        "pulse_label": "Next move",
        "bridge": "Where we are now points straight at the next concrete move.",
        "music": "Create urgency around the next action and make the move feel obvious.",
    },
}


def _top_keywords(text: str, limit: int = 6) -> list[str]:
    counts: dict[str, int] = {}
    for token in re.findall(r"[A-Za-z][A-Za-z0-9'-]+", text.lower()):
        if token in STOPWORDS or len(token) < 4:
            continue
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [word for word, _ in ranked[:limit]]


def _compress(line: str, max_words: int = 10) -> str:
    words = line.split()
    clipped = words[:max_words]
    if len(words) > max_words:
        clipped.append("...")
    return " ".join(clipped)


def _humanize_line(line: str) -> str:
    cleaned = " ".join(line.strip().split())
    lowered = cleaned.lower()
    for old, new in HUMAN_REWRITES.items():
        lowered = lowered.replace(old, new)
    cleaned = lowered
    for pattern in JARGON_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.-")
    if not cleaned:
        return "we moved the work forward with real momentum"
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
    return _compress(focus.strip().rstrip("?"), 12)


def summarize_material(material: SessionMaterial, use: str = "alarm", focus: str | None = None) -> str:
    keyword_source = material.raw_text + (f"\n{focus}" if focus else "")
    keywords = ", ".join(_top_keywords(keyword_source)) or "focus"
    helper = USE_HELPERS.get(use, USE_HELPERS["alarm"])
    lines: list[str] = []
    focus_line = _focus_line(focus)
    if focus_line:
        lines.append(f"• Focus: {focus_line}")

    if use == "alarm":
        if material.wins:
            lines.append(f"• Yesterday: {_compress(_humanize_line(material.wins[0]))}")
        if len(material.wins) > 1:
            lines.append(f"• Also landed: {_compress(_humanize_line(material.wins[1]))}")
        if material.next_actions:
            lines.append(f"• Today: {_compress(_humanize_line(material.next_actions[0]))}")
    elif use == "reminder":
        if material.wins:
            lines.append(f"• State: {_compress(_humanize_line(material.wins[0]))}")
        if material.blockers:
            lines.append(f"• Tension: {_compress(_humanize_line(material.blockers[0]))}")
        if material.next_actions:
            lines.append(f"• Direction: {_compress(_humanize_line(material.next_actions[0]))}")
    elif use == "celebrate":
        if material.wins:
            lines.append(f"• Shipped: {_compress(_humanize_line(material.wins[0]))}")
        if len(material.wins) > 1:
            lines.append(f"• Solved: {_compress(_humanize_line(material.wins[1]))}")
        if material.next_actions:
            lines.append(f"• Why it matters: {_compress(_humanize_line(material.next_actions[0]))}")
    elif use == "next_steps":
        if material.wins:
            lines.append(f"• Now: {_compress(_humanize_line(material.wins[0]))}")
        if material.next_actions:
            lines.append(f"• Next: {_compress(_humanize_line(material.next_actions[0]))}")
        elif len(material.wins) > 1:
            lines.append(f"• Next: {_compress(_humanize_line(material.wins[1]))}")
        if material.blockers:
            lines.append(f"• Watch: {_compress(_humanize_line(material.blockers[0]))}")

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
    verse_a = _compress(best[0] if len(best) > 0 else "we moved the work forward fast and clean", 12)
    verse_b = _compress(best[1] if len(best) > 1 else "pressure showed up but direction stayed clear", 12)
    verse_c = _compress(best[2] if len(best) > 2 else "next move is the highest leverage one", 12)
    bridge = USE_HELPERS.get(use, USE_HELPERS["alarm"])["bridge"]

    if use == "alarm" and material.wins:
        verse_a = f"Yesterday hit: {_compress(_humanize_line(material.wins[0]), 12)}"
    elif use == "reminder" and material.wins:
        verse_a = f"Current state: {_compress(_humanize_line(material.wins[0]), 12)}"
    elif use == "celebrate" and material.wins:
        verse_a = f"We shipped: {_compress(_humanize_line(material.wins[0]), 12)}"
    elif use == "next_steps" and material.next_actions:
        verse_a = f"Next up: {_compress(_humanize_line(material.next_actions[0]), 12)}"

    duration_seconds = request.duration_seconds or 45
    intro_line = focus_line.capitalize() if focus_line else style.intro_seed
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
        (f"Keep it on: {focus_line}" if focus_line else "Hold the line and keep the point sharp"),
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
    use = request.resolved_use
    keyword_source = material.raw_text + (f"\n{focus}" if focus else "")
    keywords = ", ".join(_top_keywords(keyword_source)) or "focused work"
    project_phrase = f" for project {material.project}" if material.project else ""
    focus_phrase = f" Focus: {focus}. Treat it as the main emphasis, not a footnote." if focus else ""
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
        f"{focus_phrase} "
        "Keep it catchy, short, PG, and suitable for chat delivery. Use these lyrics as the backbone:\n\n"
        f"{lyrics}\n\n"
        "End with a clean sting, not a long fade."
    )


def build_from_material(material: SessionMaterial, user_config: UserConfig, request: RunRequest) -> SongArtifacts:
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
    }
    return SongArtifacts(pulse=pulse, lyrics=lyrics, music_prompt=music_prompt, manifest=manifest)
