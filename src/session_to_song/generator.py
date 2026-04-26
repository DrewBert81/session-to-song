from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from .models import RunConfig

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "in",
    "into", "is", "it", "of", "on", "or", "that", "the", "to", "up", "was", "we",
    "were", "with", "today", "this", "our", "after", "before", "over", "out",
}

ACTION_HINTS = {
    "built": "Built",
    "shipped": "Shipped",
    "fixed": "Fixed",
    "debugged": "Debugged",
    "drafted": "Drafted",
    "designed": "Designed",
    "tested": "Tested",
    "reviewed": "Reviewed",
    "launched": "Launched",
    "blocked": "Blocked on",
    "waiting": "Waiting on",
    "need": "Need to",
    "next": "Next",
}


@dataclass
class PulseArtifacts:
    pulse: str
    lyrics: str
    music_prompt: str
    manifest: dict[str, object]


def _clean_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = raw.strip(" -\t")
        if line:
            lines.append(line)
    return lines


def _top_keywords(text: str, limit: int = 6) -> list[str]:
    counts: dict[str, int] = {}
    for token in re.findall(r"[A-Za-z][A-Za-z0-9'-]+", text.lower()):
        if token in STOPWORDS or len(token) < 4:
            continue
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [word for word, _ in ranked[:limit]]


def _classify_lines(lines: Iterable[str]) -> tuple[list[str], list[str], list[str]]:
    wins: list[str] = []
    blockers: list[str] = []
    next_up: list[str] = []
    for line in lines:
        lower = line.lower()
        if any(word in lower for word in ("blocked", "stuck", "waiting", "risk", "issue")):
            blockers.append(line)
        elif any(word in lower for word in ("next", "tomorrow", "follow up", "ship next", "need to")):
            next_up.append(line)
        else:
            wins.append(line)
    return wins, blockers, next_up


def _compress(line: str, max_words: int = 10) -> str:
    words = line.split()
    clipped = words[:max_words]
    if len(words) > max_words:
        clipped.append("...")
    return " ".join(clipped)


def summarize_day(text: str) -> str:
    lines = _clean_lines(text)
    wins, blockers, next_up = _classify_lines(lines)
    keywords = ", ".join(_top_keywords(text)) or "focus"

    summary_lines = []
    if wins:
        summary_lines.append(f"• Win: {_compress(wins[0])}")
    if blockers:
        summary_lines.append(f"• Watch: {_compress(blockers[0])}")
    if next_up:
        summary_lines.append(f"• Next: {_compress(next_up[0])}")
    elif len(wins) > 1:
        summary_lines.append(f"• Next: {_compress(wins[1])}")
    summary_lines.append(f"• Signal: {keywords}")
    return "\n".join(summary_lines)


def _hook_from_keywords(keywords: list[str]) -> str:
    if not keywords:
        return "Wake up, lock in, we already know the mission"
    joined = ", ".join(keywords[:3])
    return f"Wake up to {joined}, lock in and move with precision"


def _mode_intro(mode: str) -> str:
    intros = {
        "alarm": "Alarm on, screen glow, status check, let's go",
        "recap": "Playback on, yesterday loud, here's the shape of it",
        "milestone": "Milestone hit, save the echo, mark the memory",
        "memory": "Question asked, pull it back, let the story breathe",
    }
    return intros.get(mode, intros["alarm"])


def _mode_tag(mode: str) -> str:
    tags = {
        "alarm": "Daily pulse loaded. Move the next thing.",
        "recap": "Session recap loaded. Carry the signal forward.",
        "milestone": "Milestone saved. Replay it when you need the fire.",
        "memory": "Memory recalled. Turn it back into motion.",
    }
    return tags.get(mode, tags["alarm"])


def generate_lyrics(
    text: str,
    pulse: str | None = None,
    duration_seconds: int = 45,
    *,
    mode: str = "alarm",
) -> str:
    pulse = pulse or summarize_day(text)
    keywords = _top_keywords(text)
    wins, blockers, next_up = _classify_lines(_clean_lines(text))

    verse_a = _compress(wins[0] if wins else "We moved the work forward fast and clean", 12)
    verse_b = _compress(blockers[0] if blockers else "No panic, just pressure turning into direction", 12)
    verse_c = _compress(next_up[0] if next_up else "Tomorrow starts with the highest leverage move", 12)
    hook = _hook_from_keywords(keywords)

    return "\n".join([
        f"[{mode.title()} Track | ~{duration_seconds}s]",
        "",
        "[Intro]",
        _mode_intro(mode),
        "",
        "[Verse]",
        f"{verse_a}",
        f"{verse_b}",
        f"{verse_c}",
        "Small team rhythm, big day energy, no drift",
        "",
        "[Hook]",
        hook,
        "Wake up, stack wins, turn the signal into momentum",
        "",
        "[Spoken Tag]",
        _mode_tag(mode),
        "",
        "[Reference Pulse]",
        pulse,
    ])


def generate_music_prompt(text: str, pulse: str, lyrics: str, *, mode: str = "alarm") -> str:
    keywords = ", ".join(_top_keywords(text)) or "focused work"
    mode_guidance = {
        "alarm": "Create a 30-60 second wake-up track with crisp alarm energy, light hip hop drums, confident spoken/rap delivery, and motivating startup feel.",
        "recap": "Create a 30-60 second recap track with reflective momentum, clear vocal phrasing, and a memorable hook.",
        "milestone": "Create a 30-60 second victory anthem with lift, punch, and replay value for a completed milestone.",
        "memory": "Create a 30-60 second recall track that feels emotionally sticky, clear, and easy to remember later.",
    }
    return (
        f"{mode_guidance.get(mode, mode_guidance['alarm'])} "
        f"Theme keywords: {keywords}. "
        "Keep it catchy, short, PG, and suitable for chat delivery. "
        "Use these lyrics as the backbone:\n\n"
        f"{lyrics}\n\n"
        "End with a clean sting, not a long fade."
    )


def build_artifacts(text: str, config: RunConfig | None = None) -> PulseArtifacts:
    config = config or RunConfig()
    pulse = summarize_day(text)
    lyrics = generate_lyrics(text, pulse=pulse, mode=config.mode)
    music_prompt = generate_music_prompt(text, pulse=pulse, lyrics=lyrics, mode=config.mode)
    manifest = {
        "mode": config.mode,
        "input_source": config.input_source,
        "llm": {"provider": config.llm_provider, "model": config.llm_model},
        "music": {"provider": config.music_provider, "model": config.music_model},
        "keywords": _top_keywords(text),
    }
    return PulseArtifacts(pulse=pulse, lyrics=lyrics, music_prompt=music_prompt, manifest=manifest)
