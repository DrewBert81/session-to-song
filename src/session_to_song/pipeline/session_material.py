from __future__ import annotations

import re
from pathlib import Path
from datetime import datetime

from ..connectors.openclaw_sessions import ResolvedSource
from ..domain import SessionMaterial
from ..project_filter import filter_text_for_project


NOISE_PATTERNS = [
    r"Conversation info \(untrusted metadata\):",
    r"Sender \(untrusted metadata\):",
    r"System \(untrusted\):.*",
    r"\[Audio\]",
    r"\[non-text content:.*?\]",
    r"\bassistant:\s*NO_REPLY\b",
    r"\bassistant:\s*HEARTBEAT_OK\b",
    r"\bCurrent session\b",
    r"port=\d+\s+state=\w+",
    r"\[plugins?\].*",
    r"xai failed to load.*",
    r"failed to load from\s+\S+",
    r"Error:\s*Cannot.*",
    r"Treat Project Context as partial.*",
]


def strip_tool_noise(text: str) -> str:
    cleaned = text
    cleaned = re.sub(r"```json.*?```", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"```.*?```", "", cleaned, flags=re.DOTALL)
    for pattern in NOISE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"(?im)^assistant:\s*NO_REPLY\s*$", "", cleaned)
    cleaned = re.sub(r"(?im)^assistant:\s*HEARTBEAT_OK\s*$", "", cleaned)
    cleaned = re.sub(r"(?im)^user:\s*Read HEARTBEAT\.md.*$", "", cleaned)
    cleaned = re.sub(r"(?im)^\s*timestamp:\s*.*$", "", cleaned)
    return cleaned


def clean_session_text(text: str) -> str:
    cleaned = strip_tool_noise(text)
    cleaned = re.sub(r"(?im)^user:\s*", "", cleaned)
    cleaned = re.sub(r"(?im)^assistant:\s*", "", cleaned)
    cleaned = re.sub(r"(?is)conversation info\s*\(untrusted metadata\):.*?sender\s*\(untrusted metadata\):", "", cleaned)
    cleaned = re.sub(r"(?is)```json.*?```", "", cleaned)
    cleaned = re.sub(r"(?is)`json\s*\{.*?\}\s*```", "", cleaned)
    cleaned = re.sub(r"(?im)^\s*(chat_id|message_id|sender_id|sender|timestamp|label|id|name)\s*:\s*.*$", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def infer_theme(text: str) -> str | None:
    lowered = text.lower()
    if "session-to-song" in lowered:
        return "turning work into a replayable morning artifact"
    if "ship" in lowered or "built" in lowered:
        return "turning recent work into momentum"
    return None


def infer_emotional_tone(text: str) -> str | None:
    lowered = text.lower()
    if any(word in lowered for word in ["frustrating", "terrible", "stuck", "blocked"]):
        return "frustrated but pushing"
    if any(word in lowered for word in ["good", "working", "fixed", "yep"]):
        return "forward-moving"
    return None


def load_recent_dream_context(limit_entries: int = 2, dreams_path: Path | None = None) -> str:
    if dreams_path is None:
        workspace_root = Path(__file__).resolve().parents[4]
        dreams_path = workspace_root / "DREAMS.md"
    if not dreams_path.exists():
        return ""
    try:
        text = dreams_path.read_text(encoding="utf-8")
    except Exception:
        return ""
    if "<!-- openclaw:dreaming:diary:start -->" in text:
        text = text.split("<!-- openclaw:dreaming:diary:start -->", 1)[1]
    entries = [chunk.strip() for chunk in text.split("---") if chunk.strip()]
    selected = entries[-limit_entries:]
    cleaned = "\n\n".join(selected)
    return cleaned[:4000]


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _kb_sessions_root() -> Path:
    return _workspace_root() / "knowledge-base" / "raw" / "sessions"


def _memory_root() -> Path:
    return _workspace_root() / "memory"


def _score_fact_line(text: str) -> float:
    lowered = text.lower()
    if _looks_like_noise_line(text):
        return -5.0
    score = 0.0
    if len(text.split()) >= 6:
        score += 0.5
    if len(text.split()) >= 12:
        score += 0.5
    if any(word in lowered for word in ["built", "fixed", "shipped", "implemented", "added", "wired", "restarted", "verified", "checked", "cut", "trimmed"]):
        score += 1.5
    if any(word in lowered for word in ["decided", "decision", "going with", "keep", "use ", "remove", "hard-block"]):
        score += 1.0
    if any(word in lowered for word in ["next", "need to", "follow up", "today", "tomorrow", "where am i going", "matters now"]):
        score += 1.25
    if any(word in lowered for word in ["blocked", "stuck", "wrong", "bug", "issue", "problem", "too generic", "too vague"]):
        score += 1.0
    if any(word in lowered for word in ["untrusted metadata", "no_reply", "heartbeat_ok", "chat_id", "message_id", "sender_id", "timestamp"]):
        score -= 3.0
    return score


def _looks_like_noise_line(text: str) -> bool:
    lowered = text.lower().strip()
    if not lowered:
        return True
    if len(lowered.split()) < 4:
        return True
    if len(lowered.split()) > 40:
        return True
    if lowered.startswith("#") or lowered.startswith("[") or lowered.startswith("```"):
        return True
    if "##" in lowered or "**" in lowered:
        return True
    if re.search(r"\[[0-9]+(?:\.[0-9]+)?\:[0-9]+(?:\.[0-9]+)?\]", lowered):
        return True
    if re.search(r"[a-z]:\\|/users/|c:\\|https?://|\.html\b|\.json\b|\.py\b", lowered):
        return True
    if any(token in lowered for token in [
        "caption:", "[hook]", "[verse]", "[intro]", "reference pulse",
        "toolresult", "non-text content", "backenddomnodeid", "fullscreenelement",
        "current url", "mockup", "dream recap track", "track opens with", "send me",
        "pick for me", "any calendar hard stops", "source preview card text",
        "port=", "state=probing", "[plugins]", "xai failed", "failed to load from",
        "node_modules", "error: cannot", "treat project context",
    ]):
        return True
    if lowered.startswith("if ") or lowered.startswith("2)") or lowered.startswith("3)"):
        return True
    if text.count("`") >= 2:
        return True
    weird = len(re.findall(r"[^\w\s,.!?':;()-]", text))
    if weird > max(6, len(text) // 12):
        return True
    return False


def _split_fact_candidates(text: str) -> list[str]:
    cleaned = clean_session_text(text)
    if not cleaned:
        return []
    chunks: list[str] = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip(" -•\t")
        if not line:
            continue
        parts = re.split(r"(?<=[.!?])\s+", line)
        for part in parts:
            part = part.strip(" -•\t")
            if len(part.split()) < 4:
                continue
            if _looks_like_noise_line(part):
                continue
            chunks.append(part)
    return chunks


def _select_fact_lines(*texts: str, limit: int = 12) -> list[str]:
    scored: list[tuple[float, str]] = []
    seen: set[str] = set()
    for text in texts:
        for line in _split_fact_candidates(text):
            line = _normalize_fact_line(line)
            normalized = re.sub(r"\s+", " ", line.lower()).strip()
            if normalized in seen:
                continue
            seen.add(normalized)
            score = _score_fact_line(line)
            if score <= 0:
                continue
            scored.append((score, line))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [line for _, line in scored[:limit]]


def _normalize_fact_line(text: str) -> str:
    cleaned = " ".join(text.split())
    replacements = {
        "session two songs": "session-to-song",
        "session two song": "session-to-song",
        "convict show": "config controls",
        "convicts show": "config controls",
        "genre cest": "genre controls",
        "open claw memory": "memory",
        "mission re entry": "mission re-entry",
    }
    lowered = cleaned.lower()
    for old, new in replacements.items():
        lowered = lowered.replace(old, new)
    lowered = lowered.replace("  ", " ").strip()
    if lowered.startswith("shift built") or lowered.startswith("shifts built"):
        lowered = lowered.replace("shift built", "built", 1).replace("shifts built", "built", 1)
    return lowered[0].upper() + lowered[1:] if lowered else cleaned


def _dedupe_lines(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        normalized = re.sub(r"\s+", " ", line.lower()).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(line)
    return output


def _classify_fact_lines(lines: list[str]) -> tuple[list[str], list[str], list[str], list[str]]:
    wins: list[str] = []
    blockers: list[str] = []
    next_actions: list[str] = []
    decisions: list[str] = []
    for line in lines:
        lowered = line.lower()
        if any(word in lowered for word in ["decision:", "product requirement:", "decided", "going with", "keep ", "remove ", "hard-block"]):
            decisions.append(line)
        if any(word in lowered for word in ["next", "today", "tomorrow", "follow up", "need to", "fixing", "where am i going", "matters now"]):
            next_actions.append(line)
        elif any(word in lowered for word in ["blocked", "stuck", "wrong", "issue", "problem", "too generic", "too vague", "error", "failing"]):
            blockers.append(line)
        else:
            wins.append(line)
    return _dedupe_lines(wins), _dedupe_lines(blockers), _dedupe_lines(next_actions), _dedupe_lines(decisions)


def load_recent_memory_context(limit_files: int = 2) -> str:
    memory_root = _memory_root()
    if not memory_root.exists():
        return ""
    files = sorted(memory_root.glob("20??-??-??.md"), key=lambda p: p.name, reverse=True)[:limit_files]
    lines: list[str] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line.startswith("- **"):
                continue
            if len(line.split()) < 6:
                continue
            lines.append(line.lstrip("- "))
    deduped = _dedupe_lines(lines)
    return "\n".join(f"- {line}" for line in deduped[:12])


def _wiki_root() -> Path:
    return _workspace_root() / "knowledge-base" / "wiki"


def _dream_session_corpus_root() -> Path:
    return _workspace_root() / "memory" / ".dreams" / "session-corpus"


def load_wiki_context(limit_files: int = 3) -> str:
    """Load recent wiki reports, syntheses, and daily entries for broader project context."""
    wiki = _wiki_root()
    if not wiki.exists():
        return ""
    chunks: list[str] = []
    for subdir in ("reports", "syntheses", "daily"):
        target = wiki / subdir
        if not target.exists():
            continue
        for path in sorted(target.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:2]:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
                chunks.append(f"[wiki {subdir}: {path.stem}]\n{text[:2000]}")
            except Exception:
                continue
    return "\n\n".join(chunks[:limit_files])


def load_previous_day_sessions(days_back: int = 2) -> str:
    """Load archived session digests from the past N days for broader temporal context."""
    kb_root = _kb_sessions_root()
    if not kb_root.exists():
        return ""
    import datetime as _dt
    today = _dt.date.today()
    chunks: list[str] = []
    for offset in range(1, days_back + 1):
        target_date = (today - _dt.timedelta(days=offset)).isoformat()
        for path in sorted(kb_root.glob(f"{target_date}_*.md")):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
                chunks.append(f"[archived session: {path.stem}]\n{text[:3000]}")
            except Exception:
                continue
    return "\n\n".join(chunks[:4])


def load_dream_context_enriched(limit_entries: int = 3, dreams_path: Path | None = None) -> str:
    """Load dream diary + dream session corpus for the alarm use case."""
    parts: list[str] = []
    diary = load_recent_dream_context(limit_entries=limit_entries, dreams_path=dreams_path)
    if diary:
        parts.append(f"[dream diary]\n{diary}")
    corpus_root = _dream_session_corpus_root()
    if corpus_root.exists():
        for path in sorted(corpus_root.glob("*.txt"), key=lambda p: p.name, reverse=True)[:2]:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
                parts.append(f"[dream corpus: {path.stem}]\n{text[:2000]}")
            except Exception:
                continue
    return "\n\n".join(parts)


def _extract_daily_session_excerpt(source: ResolvedSource) -> str:
    if not source.session_id or not source.started_at:
        return ""
    try:
        date = datetime.fromisoformat(source.started_at.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return ""
    kb_root = _kb_sessions_root()
    if not kb_root.exists():
        return ""
    candidates = sorted(kb_root.glob(f"{date}_*.md"))
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        marker = f"**Session ID:** {source.session_id}"
        idx = text.find(marker)
        if idx < 0:
            continue
        start = text.rfind("# Session:", 0, idx)
        start = 0 if start < 0 else start
        end = text.find("\n# Session:", idx)
        excerpt = text[start:end if end > idx else None].strip()
        return excerpt[:12000]
    return ""


# ─── USE-AWARE SOURCING STRATEGY ────────────────────────────────────────────

USE_SOURCING_STRATEGY = {
    "alarm": {
        "include_dreams": True,
        "include_wiki": True,
        "include_previous_days": True,
        "include_memory": True,
        "fact_limit": 18,
    },
    "celebrate": {
        "include_dreams": False,
        "include_wiki": False,
        "include_previous_days": True,
        "include_memory": True,
        "fact_limit": 16,
    },
    "reminder": {
        "include_dreams": False,
        "include_wiki": True,
        "include_previous_days": True,
        "include_memory": True,
        "fact_limit": 16,
    },
    "next_steps": {
        "include_dreams": False,
        "include_wiki": True,
        "include_previous_days": True,
        "include_memory": True,
        "fact_limit": 16,
    },
}


def extract_material_from_session(
    source: ResolvedSource,
    title: str | None = None,
    use: str | None = None,
) -> SessionMaterial:
    strategy = USE_SOURCING_STRATEGY.get(use or "", {})
    fact_limit = strategy.get("fact_limit", 14)
    project = source.project

    # Source text is already project-scoped by the OpenClaw resolver when a
    # project is set. Keep nearby context lines so facts do not disappear just
    # because the project name was mentioned one message earlier.
    cleaned = clean_session_text(source.raw_text)
    archived_excerpt = _extract_daily_session_excerpt(source)
    archived_cleaned = clean_session_text(archived_excerpt)
    memory_context = load_recent_memory_context()

    if project:
        archived_cleaned = filter_text_for_project(archived_cleaned, project)
        memory_context = filter_text_for_project(memory_context, project)

    # Use-aware enrichment
    dream_context = ""
    wiki_context = ""
    previous_day_context = ""

    if strategy.get("include_dreams"):
        dream_context = load_dream_context_enriched(limit_entries=3)
    if strategy.get("include_wiki"):
        wiki_context = load_wiki_context(limit_files=3)
    if strategy.get("include_previous_days"):
        previous_day_context = load_previous_day_sessions(days_back=2)

    if project:
        dream_context = filter_text_for_project(dream_context, project)
        wiki_context = filter_text_for_project(wiki_context, project)
        previous_day_context = filter_text_for_project(previous_day_context, project)

    # Combine all text sources for fact extraction
    all_sources = [cleaned, archived_cleaned, memory_context]
    if dream_context:
        all_sources.append(dream_context)
    if wiki_context:
        all_sources.append(wiki_context)
    if previous_day_context:
        all_sources.append(previous_day_context)

    curated_facts = _select_fact_lines(*all_sources, limit=fact_limit)
    wins, blockers, next_actions, decisions = _classify_fact_lines(curated_facts)

    # Build combined text with all enrichment layers
    combined_text = cleaned
    if curated_facts:
        combined_text = "Structured session facts:\n" + "\n".join(f"- {line}" for line in curated_facts)
        if dream_context:
            combined_text += f"\n\nDream context (for tone and continuity):\n{dream_context[:3000]}"
        if wiki_context:
            combined_text += f"\n\nWiki context (project state and direction):\n{wiki_context[:3000]}"
        if previous_day_context:
            combined_text += f"\n\nPrevious day sessions:\n{previous_day_context[:3000]}"
        if memory_context:
            combined_text += f"\n\nRecent memory context:\n{memory_context[:2500]}"
        if archived_cleaned:
            combined_text += f"\n\nArchived session excerpt:\n{archived_cleaned[:4000]}"
        if cleaned:
            combined_text += f"\n\nLive session transcript:\n{cleaned[:4000]}"

    material = SessionMaterial(
        source="openclaw_session",
        title=title or source.label or "auto-session",
        raw_text=combined_text,
        project=project,
        wins=wins,
        blockers=blockers,
        next_actions=next_actions,
        metadata={"line_count": len(curated_facts)},
    )
    material.metadata.update(
        {
            "session_key": source.session_key,
            "session_id": source.session_id,
            "source_mode": source.mode,
            "source_reason": source.reason,
            "source_score": source.score,
            "source_preview": source.preview,
            "archived_session_excerpt": archived_cleaned[:4000] if archived_cleaned else "",
            "curated_facts": curated_facts,
            "decisions": decisions,
            "memory_context": memory_context[:2500] if memory_context else "",
            "dream_context": dream_context[:2000] if dream_context else "",
            "wiki_context": wiki_context[:2000] if wiki_context else "",
            "previous_day_context": previous_day_context[:2000] if previous_day_context else "",
            "use": use or "",
            "theme": infer_theme(cleaned),
            "emotional_tone": infer_emotional_tone(cleaned),
        }
    )
    return material
