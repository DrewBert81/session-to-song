from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..project_filter import filter_lines_for_project, project_matches


@dataclass
class ResolvedSource:
    mode: str
    session_key: str | None
    session_id: str | None
    label: str | None
    project: str | None
    started_at: str | None
    ended_at: str | None
    score: float
    reason: str
    raw_text: str
    preview: str


@dataclass
class SourceRequest:
    mode: str = "auto"
    session_key: str | None = None
    project: str | None = None
    lookback_hours: int = 36
    limit: int = 12
    use: str | None = None
    target_date: str | None = None


def _openclaw_root() -> Path:
    return Path(os.getenv("OPENCLAW_HOME", str(Path.home() / ".openclaw")))


def _session_registry_files() -> list[Path]:
    root = _openclaw_root() / "agents"
    if not root.exists():
        return []
    return list(root.glob("*/sessions/sessions.json"))


def _openclaw_workspace_root() -> Path:
    explicit = os.getenv("SESSION_TO_SONG_OPENCLAW_WORKSPACE") or os.getenv("OPENCLAW_WORKSPACE")
    if explicit:
        return Path(explicit)
    return _openclaw_root() / "workspace"


def _workspace_candidates() -> list[Path]:
    candidates: list[Path] = []
    explicit = os.getenv("SESSION_TO_SONG_OPENCLAW_WORKSPACE") or os.getenv("OPENCLAW_WORKSPACE")
    if explicit:
        candidates.append(Path(explicit))
    home = _openclaw_root()
    candidates.extend([
        home / "workspace",
        home / "workspace-Ehgent",
    ])
    seen: set[str] = set()
    output: list[Path] = []
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            continue
        seen.add(key)
        output.append(candidate)
    return output


def _parse_timestamp(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value) / 1000, tz=UTC)
        except Exception:
            return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_text_from_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text" and item.get("text"):
            parts.append(str(item["text"]))
    return "\n".join(parts)


def build_preview(text: str, max_chars: int = 400) -> str:
    lines = text.splitlines()
    clean_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        # Skip known noise in preview
        if any(noise in lowered for noise in [
            "port=", "state=probing", "xai failed", "failed to load",
            "node_modules", "error: cannot", "treat project context",
            "untrusted metadata", "no_reply", "heartbeat_ok", "chat_id",
            "message_id", "sender_id", "current session",
            "[health-monitor]", "[gateway]", "[plugins]", "[agent]",
            "[telegram]", "[signal]", "[webchat]", "[device-pair]",
            "agent model:", "startup-grace", "channel-connect-grace",
            "interval:", "ready (",
        ]):
            continue
        # Skip timestamped log output (HH:MM:SS [tag])
        if re.match(r'^\d{2}:\d{2}(:\d{2})?\s*\[', stripped):
            continue
        # Skip session separators and very short lines
        if stripped.startswith("--- session:") or stripped.startswith("---"):
            continue
        if len(stripped.split()) < 5:
            continue
        # Strip role prefixes for cleaner display
        for prefix in ("user: ", "assistant: "):
            if stripped.lower().startswith(prefix):
                stripped = stripped[len(prefix):]
                break
        if stripped:
            clean_lines.append(stripped)
    # Deduplicate
    seen: set[str] = set()
    unique: list[str] = []
    for line in clean_lines:
        norm = re.sub(r"\s+", " ", line.lower()).strip()
        if norm not in seen:
            seen.add(norm)
            unique.append(line)
    # Format as bullet points
    bullets = [f"• {line}" for line in unique[:8]]
    cleaned = "\n".join(bullets).strip()
    if not cleaned:
        cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


def _message_signal_score(text: str) -> float:
    lowered = text.lower()
    score = 0.0
    score += min(len(re.findall(r"\b(built|fixed|shipped|implemented|working|done|launched|tested|improved|wired)\b", lowered)) * 0.8, 2.4)
    score += min(len(re.findall(r"\b(next|need to|follow up|today|tomorrow|blocker|stuck|waiting|should)\b", lowered)) * 0.6, 1.8)
    score += min(len(re.findall(r"\b(decision|decided|problem|issue|wrong|bug|fix|goal|project)\b", lowered)) * 0.4, 1.2)
    if "session-to-song" in lowered:
        score += 1.5
    if len(text.split()) >= 12:
        score += 0.5
    if len(text.split()) >= 30:
        score += 0.5
    if re.search(r"\b(no_reply|heartbeat_ok|untrusted metadata|chat_id|message_id|sender_id|timestamp)\b", lowered):
        score -= 4.0
    if re.search(r"\b(read heartbeat\.md|conversation info|sender \(untrusted metadata\)|system \(untrusted\))\b", lowered):
        score -= 4.0
    if re.search(r"\b(crappy sessions? info|same lyrics as the last song|asking it to talk about|celebrate track \| genre=|reference pulse|generated_audio|lyrics\.txt)\b", lowered):
        score -= 5.0
    if re.search(r"\b(open:\s*http|running locally|started it from|status check|keys present|web app running|left the web app running|server process is running)\b", lowered):
        score -= 3.0
    # OpenClaw system/infrastructure noise
    if re.search(r"\bport=\d+\b", lowered):
        score -= 4.0
    if re.search(r"\bstate=probing\b", lowered):
        score -= 4.0
    if re.search(r"\b(failed to load|xai failed|plugins?\]|extensions?[\\/]|\.js:|cannot find|cannot read|error:)\b", lowered):
        score -= 4.0
    if re.search(r"\b(node_modules|dist[\\/]|appdata[\\/]|npm[\\/]|index\.js)\b", lowered):
        score -= 4.0
    if re.search(r"\b(treat project context|project context as partial)\b", lowered):
        score -= 3.0
    # OpenClaw boot/gateway/agent log lines
    if re.search(r"\[(health-monitor|gateway|agent|telegram|signal|webchat|device-pair|plugins?)\]", lowered):
        score -= 4.0
    if re.search(r"\b(startup-grace|channel-connect-grace|agent model:|interval:\s*\d+s)\b", lowered):
        score -= 4.0
    # Timestamped log lines: 09:25:42 [tag]
    if re.match(r"\d{2}:\d{2}(:\d{2})?\s*\[", text.strip()):
        score -= 5.0
    return max(score, 0.0)


def _split_into_snippets(line: str) -> list[str]:
    text = re.sub(r"\s+", " ", line).strip()
    if not text:
        return []
    role_prefix = ""
    if text.startswith("user: ") or text.startswith("assistant: "):
        role_prefix, text = text.split(": ", 1)
        role_prefix = f"{role_prefix}: "
    parts: list[str] = []
    for segment in re.split(r"(?<=[.!?])\s+|\s+[•\-]\s+", text):
        segment = segment.strip(" -•\t")
        if not segment:
            continue
        if len(segment.split()) < 4:
            continue
        parts.append(f"{role_prefix}{segment}")
    return parts or ([line] if len(text.split()) >= 4 else [])


def _select_meaningful_lines(lines: list[str], limit: int) -> list[str]:
    snippet_rows: list[tuple[int, float, str]] = []
    for idx, line in enumerate(lines):
        for snippet in _split_into_snippets(line):
            score = _message_signal_score(snippet)
            if score <= 0:
                continue
            snippet_rows.append((idx, score, snippet))
    scored: list[tuple[int, float, str]] = []
    seen_normalized: set[str] = set()
    for idx, score, snippet in snippet_rows:
        normalized = re.sub(r"\s+", " ", snippet.lower()).strip()
        if normalized in seen_normalized:
            continue
        seen_normalized.add(normalized)
        scored.append((idx, score, snippet))
    for idx, line in enumerate(lines):
        if scored:
            break
        score = _message_signal_score(line)
        if score <= 0:
            continue
        scored.append((idx, score, line))
    if not scored:
        return []
    scored.sort(key=lambda item: (item[1], item[0]), reverse=True)
    selected = sorted(scored[:limit], key=lambda item: item[0])
    return [line for _, _, line in selected]


def _project_context_lines(lines: list[str], project: str | None, context: int = 0) -> list[str]:
    if not project:
        return lines
    selected_indexes: set[int] = set()
    for idx, line in enumerate(lines):
        if not project_matches(line, project):
            continue
        for nearby in range(max(0, idx - context), min(len(lines), idx + context + 1)):
            selected_indexes.add(nearby)
    return [line for idx, line in enumerate(lines) if idx in selected_indexes]


def _read_text_limited(path: Path, max_chars: int = 300_000) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return handle.read(max_chars)
    except Exception:
        return ""


def _curated_context_files() -> list[Path]:
    candidates: list[Path] = []
    for workspace in _workspace_candidates():
        roots = [
            workspace / "knowledge-base" / "wiki" / "daily",
            workspace / "knowledge-base" / "wiki" / "syntheses",
            workspace / "knowledge-base" / "wiki" / "reports",
            workspace / "knowledge-base" / "wiki" / "entities",
            workspace / "knowledge-base" / "wiki" / "articles",
            workspace / "knowledge-base" / "raw" / "sessions",
            workspace / "memory",
        ]
        for root in roots:
            if not root.exists():
                continue
            candidates.extend(path for path in root.glob("*.md") if path.is_file())
            candidates.extend(path for path in root.glob("*.txt") if path.is_file())
    unique = {str(path.resolve()): path for path in candidates}
    return sorted(unique.values(), key=lambda path: path.stat().st_mtime, reverse=True)


def _relative_curated_label(path: Path) -> str:
    for workspace in _workspace_candidates():
        try:
            return str(path.resolve().relative_to(workspace.resolve()))
        except Exception:
            continue
    return path.name


def _target_date(request: SourceRequest) -> datetime.date:
    if request.target_date:
        try:
            return datetime.fromisoformat(request.target_date).date()
        except ValueError:
            pass
    if (request.use or "").lower() == "alarm":
        return (datetime.now() - timedelta(days=1)).date()
    return datetime.now().date()


def _date_labels(day) -> tuple[str, str]:
    iso = day.isoformat()
    pretty = f"{day.strftime('%B')} {day.day}, {day.year}"
    return iso, pretty


def _daily_context_files(day) -> list[Path]:
    iso, _ = _date_labels(day)
    candidates: list[Path] = []
    for workspace in _workspace_candidates():
        direct = [
            workspace / "memory" / f"{iso}.md",
            workspace / "knowledge-base" / "wiki" / "daily" / f"{iso}.md",
            workspace / "knowledge-base" / "wiki" / "daily" / f"{iso}.txt",
        ]
        candidates.extend(path for path in direct if path.exists() and path.is_file())
        wiki_daily = workspace / "knowledge-base" / "wiki" / "daily"
        if wiki_daily.exists():
            candidates.extend(path for path in wiki_daily.glob(f"*{iso}*.md") if path.is_file())
    unique = {str(path.resolve()): path for path in candidates}
    return list(unique.values())


def _dream_files() -> list[Path]:
    candidates: list[Path] = []
    for workspace in _workspace_candidates():
        candidates.append(workspace / "DREAMS.md")
    unique = {str(path.resolve()): path for path in candidates if path.exists() and path.is_file()}
    return list(unique.values())


def _dream_entries_for_date(day) -> list[str]:
    _, pretty = _date_labels(day)
    entries: list[str] = []
    for path in _dream_files():
        text = _read_text_limited(path, max_chars=500_000)
        if "<!-- openclaw:dreaming:diary:start -->" in text:
            text = text.split("<!-- openclaw:dreaming:diary:start -->", 1)[1]
        for chunk in [part.strip() for part in text.split("---") if part.strip()]:
            if f"*{pretty}" in chunk or pretty in chunk:
                entries.append(chunk)
    return entries


def _select_curated_file_lines(text: str, project: str | None, limit: int = 18) -> list[str]:
    raw_lines = [line.strip(" -•\t") for line in text.splitlines() if line.strip()]
    if project:
        raw_lines = filter_lines_for_project(raw_lines, project)
    selected = _select_meaningful_lines(raw_lines, limit)
    return [line for line in selected if line.strip()]


def resolve_daily_dream_context_source(request: SourceRequest) -> ResolvedSource | None:
    """Build the intended alarm source: dated wiki/memory first, dated dreams second.

    For wake-up alarms, the valuable source is usually yesterday's durable
    summary plus dream imagery. Raw sessions should only be fallback evidence
    when that curated bundle is too thin.
    """
    if (request.use or "").lower() != "alarm" or request.mode not in {"auto", "recent_session"}:
        return None
    day = _target_date(request)
    iso, pretty = _date_labels(day)
    parts: list[str] = []
    labels: list[str] = []
    fact_count = 0
    for path in _daily_context_files(day):
        text = _read_text_limited(path, max_chars=350_000)
        if not text.strip():
            continue
        selected = _select_curated_file_lines(text, request.project, limit=80)
        if request.project and not selected:
            continue
        body = "\n".join(selected) if selected else text
        fact_count += len([line for line in body.splitlines() if line.strip()])
        label = _relative_curated_label(path)
        labels.append(label)
        parts.append(f"--- dated source: {label} ---\n{body}")
    dream_entries = _dream_entries_for_date(day)
    if dream_entries:
        dream_text = "\n\n".join(dream_entries)[:8000]
        labels.append(f"DREAMS.md:{pretty}")
        parts.append(f"--- dream source: DREAMS.md {pretty} ---\n{dream_text}")
    if not parts:
        return None
    combined_text = "\n\n".join(parts)
    # Require enough non-dream factual material before blocking raw-session fallback.
    if fact_count < 2 and len(dream_entries) == 0:
        return None
    return ResolvedSource(
        mode="curated_daily_dreams",
        session_key=None,
        session_id=None,
        label=labels[0] + (f" (+{len(labels) - 1} more)" if len(labels) > 1 else ""),
        project=request.project,
        started_at=f"{iso}T00:00:00",
        ended_at=f"{iso}T23:59:59",
        score=1.0,
        reason="dated wiki/memory plus dreams for alarm" + (", project scoped" if request.project else ""),
        raw_text=combined_text,
        preview=build_preview(combined_text),
    )


def resolve_curated_context_source(request: SourceRequest) -> ResolvedSource | None:
    """Resolve summarized OpenClaw context before falling back to raw JSONL sessions.

    Modern OpenClaw installs often maintain wiki pages, daily summaries, and
    archived session digests. Those are cleaner song inputs than raw transcripts.
    This resolver reads only local user-owned files under the user's OpenClaw
    workspace and never requires Drew's data or a hosted service.
    """
    files = _curated_context_files()
    if not files:
        return None
    now_ms = datetime.now(tz=UTC).timestamp() * 1000
    min_mtime_ms = now_ms - (request.lookback_hours * 3600 * 1000)
    rows: list[tuple[float, Path, list[str]]] = []
    for path in files[:80]:
        try:
            mtime_ms = path.stat().st_mtime * 1000
        except Exception:
            continue
        # Keep project matches even if older; otherwise respect the lookback.
        text = _read_text_limited(path)
        if not text.strip():
            continue
        label = _relative_curated_label(path)
        project_hit = bool(request.project and (project_matches(label, request.project) or project_matches(text, request.project)))
        if mtime_ms < min_mtime_ms and not project_hit:
            continue
        lines = _select_curated_file_lines(text, request.project, limit=18)
        if request.project and not lines:
            continue
        if not request.project and not lines:
            continue
        age_hours = max(0.0, (now_ms - mtime_ms) / 3600000)
        recency_score = max(0.0, 1.0 - min(age_hours / max(request.lookback_hours, 1), 1.0))
        path_lower = label.lower()
        source_boost = 0.0
        if "wiki" in path_lower:
            source_boost += 0.18
        if "syntheses" in path_lower or "reports" in path_lower:
            source_boost += 0.12
        if "raw" in path_lower and "sessions" in path_lower:
            source_boost += 0.08
        project_boost = 0.25 if project_hit else 0.0
        signal = min(sum(_message_signal_score(line) for line in lines[:8]) / 10.0, 0.35)
        score = min(1.0, 0.35 + recency_score * 0.25 + source_boost + project_boost + signal)
        rows.append((score, path, lines[:18]))
    if not rows:
        return None
    rows.sort(key=lambda item: item[0], reverse=True)
    selected = rows[: min(4, max(1, request.limit // 3))]
    parts: list[str] = []
    labels: list[str] = []
    for _, path, lines in selected:
        label = _relative_curated_label(path)
        labels.append(label)
        parts.append(f"--- curated source: {label} ---\n" + "\n".join(lines))
    combined_text = "\n\n".join(parts)
    best_score = selected[0][0]
    reason = "curated OpenClaw memory/wiki/session digest"
    if request.project:
        reason += ", project match"
    return ResolvedSource(
        mode="curated_context",
        session_key=None,
        session_id=None,
        label=labels[0] + (f" (+{len(labels) - 1} more)" if len(labels) > 1 else ""),
        project=request.project,
        started_at=None,
        ended_at=None,
        score=round(best_score, 3),
        reason=reason,
        raw_text=combined_text,
        preview=build_preview(combined_text),
    )


def list_candidate_sessions(project: str | None = None, lookback_hours: int = 36, limit: int = 12) -> list[dict]:
    now_ms = datetime.now(tz=UTC).timestamp() * 1000
    min_updated_ms = now_ms - (lookback_hours * 3600 * 1000)
    candidates: list[dict] = []
    project_lower = (project or "").lower().strip()

    for registry in _session_registry_files():
        try:
            payload = json.loads(registry.read_text(encoding="utf-8"))
        except Exception:
            continue
        agent_name = registry.parents[1].name
        for session_key, meta in payload.items():
            if not isinstance(meta, dict):
                continue
            updated_at = meta.get("updatedAt") or 0
            if updated_at < min_updated_ms:
                continue
            session_file = meta.get("sessionFile")
            if not session_file:
                continue
            label = str(meta.get("label") or "").strip()
            # Build a human-readable label if the metadata label is empty or a UUID
            if not label or (len(label) > 30 and "-" in label):
                age_ms = now_ms - float(updated_at)
                age_hours = age_ms / 3600000
                if age_hours < 1:
                    time_str = f"{int(age_ms / 60000)}m ago"
                elif age_hours < 24:
                    time_str = f"{int(age_hours)}h ago"
                else:
                    time_str = f"{int(age_hours / 24)}d ago"
                label = f"{agent_name} · {time_str}"
            hay = f"{label} {session_key} {meta.get('channel') or ''} {meta.get('lastChannel') or ''}".lower()
            if project_lower and project_lower not in hay:
                # still allow it; project match is a boost, not a hard filter
                pass
            candidates.append(
                {
                    "session_key": session_key,
                    "session_id": meta.get("sessionId") or Path(session_file).stem,
                    "label": label or Path(session_file).stem,
                    "session_file": session_file,
                    "updated_at": int(updated_at),
                    "started_at": meta.get("startedAt"),
                    "ended_at": meta.get("endedAt"),
                    "agent": agent_name,
                    "channel": meta.get("channel") or meta.get("lastChannel") or meta.get("deliveryContext", {}).get("channel"),
                }
            )
    candidates.sort(key=lambda item: item.get("updated_at", 0), reverse=True)
    return candidates[:limit]


def fetch_session_text(session_key: str, limit: int = 240, project: str | None = None) -> str:
    for registry in _session_registry_files():
        try:
            payload = json.loads(registry.read_text(encoding="utf-8"))
        except Exception:
            continue
        meta = payload.get(session_key)
        if not isinstance(meta, dict):
            continue
        session_file = Path(str(meta.get("sessionFile") or ""))
        if not session_file.exists():
            return ""
        lines: list[str] = []
        try:
            with session_file.open("r", encoding="utf-8") as handle:
                for raw in handle:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        item = json.loads(raw)
                    except Exception:
                        continue
                    if item.get("type") != "message":
                        continue
                    message = item.get("message") or {}
                    role = message.get("role")
                    if role not in {"user", "assistant"}:
                        continue
                    text = _extract_text_from_content(message.get("content"))
                    if not text.strip():
                        continue
                    lines.append(f"{role}: {text.strip()}")
        except Exception:
            return ""
        if project:
            contextual_lines = _project_context_lines(lines, project)
            strict_lines = filter_lines_for_project(lines, project)
            lines = contextual_lines or strict_lines or []
            if not lines:
                return ""
        # Score ALL lines from the entire session, not just the tail.
        # This ensures work content from early in the session isn't lost.
        selected = _select_meaningful_lines(lines, min(limit, 64))
        return "\n\n".join(selected)
    return ""


def score_session_candidate(session: dict, transcript: str, project: str | None = None) -> tuple[float, str]:
    lowered = transcript.lower()
    label = str(session.get("label") or "")
    now_ms = datetime.now(tz=UTC).timestamp() * 1000
    age_hours = max(0.0, (now_ms - float(session.get("updated_at") or 0)) / 3600000)
    recency_score = max(0.0, 1.0 - min(age_hours / 48.0, 1.0))
    line_count = max(1, len([line for line in transcript.splitlines() if line.strip()]))
    volume_score = min(line_count / 60.0, 1.0)
    progress_hits = sum(lowered.count(word) for word in ["built", "fixed", "done", "shipped", "working", "launched", "implemented"])
    next_hits = sum(lowered.count(word) for word in ["next", "need to", "follow up", "today", "tomorrow", "blocker", "stuck", "waiting"])
    progress_score = min((progress_hits + next_hits) / 8.0, 1.0)
    if re.search(r"\b(crappy sessions? info|same lyrics as the last song|asking it to talk about|celebrate track \| genre=|reference pulse)\b", lowered):
        progress_score = 0.0
        recency_score *= 0.2
    if re.search(r"\b(open:\s*http|running locally|started it from|status check|keys present|web app running|left the web app running|server process is running)\b", lowered):
        progress_score *= 0.25
    project_score = 0.0
    if project and (project_matches(lowered, project) or project_matches(label, project)):
        project_score = 1.0
    elif project:
        project_score = -0.25
    channel = str(session.get("channel") or "")
    channel_score = 0.2 if channel in {"telegram", "signal", "webchat"} else 0.0
    label_score = 0.15 if project and project_matches(label, project) else 0.0
    completion_score = 0.15 if re.search(r"\b(completed successfully|subagent task|implemented first-pass|public-readiness review)\b", lowered) else 0.0
    noise_penalty = 0.0
    if re.search(r"\b(system \(untrusted\)|exec failed|exec completed|http://|running locally|status check|keys present)\b", lowered):
        noise_penalty = 0.25
    score = recency_score * 0.35 + volume_score * 0.15 + progress_score * 0.25 + project_score * 0.15 + channel_score + label_score + completion_score - noise_penalty
    score = min(max(score, 0.0), 1.0)
    reason_bits: list[str] = []
    if recency_score > 0.6:
        reason_bits.append("recent")
    if volume_score > 0.5:
        reason_bits.append("substantial")
    if progress_score > 0.4:
        reason_bits.append("high-signal")
    if project_score > 0:
        reason_bits.append("project match")
    return score, ", ".join(reason_bits) or "best recent session"


def resolve_best_session_source(request: SourceRequest) -> ResolvedSource | None:
    # Source ladder:
    # 1) explicit session_key/current session -> raw session path by user intent
    # 2) alarm auto: dated wiki/memory + dreams -> wake-up source of truth
    # 3) curated OpenClaw wiki/memory/session digests -> cleaner default
    # 4) raw JSONL session transcripts -> evidence fallback
    if not request.session_key and request.mode in {"auto", "recent_session"}:
        daily_dreams = resolve_daily_dream_context_source(request)
        if daily_dreams and daily_dreams.score >= 0.55:
            return daily_dreams
        curated = resolve_curated_context_source(request)
        if curated and curated.score >= 0.55:
            return curated

    candidates = list_candidate_sessions(project=request.project, lookback_hours=request.lookback_hours, limit=request.limit)
    if request.session_key:
        candidates = [candidate for candidate in candidates if candidate["session_key"] == request.session_key] or candidates
    scored: list[tuple[float, str, dict, str]] = []
    for candidate in candidates:
        label_matches_project = bool(request.project and project_matches(str(candidate.get("label") or ""), request.project))
        transcript = fetch_session_text(
            candidate["session_key"],
            project=None if label_matches_project else request.project,
        )
        if not transcript.strip():
            continue
        score, reason = score_session_candidate(candidate, transcript, project=request.project)
        if request.mode == "current_session":
            score += 0.15
        elif request.mode == "recent_session":
            score += 0.05
        score = min(score, 1.0)
        scored.append((score, reason, candidate, transcript))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    # Use the best session as the primary, but combine material from top sessions
    best_score, best_reason, best_candidate, best_transcript = scored[0]
    # Combine transcripts from the top sessions for a fuller picture
    combined_parts = [best_transcript]
    extra_labels: list[str] = []
    for extra_score, _, extra_candidate, extra_transcript in scored[1:3]:
        if extra_score < 0.2:
            continue
        extra_label = extra_candidate.get("label") or extra_candidate.get("session_id") or "session"
        combined_parts.append(f"--- session: {extra_label} ---\n{extra_transcript}")
        extra_labels.append(extra_label)
    combined_text = "\n\n".join(combined_parts)
    started = _parse_timestamp(best_candidate.get("started_at"))
    ended = _parse_timestamp(best_candidate.get("ended_at"))
    label = best_candidate.get("label") or best_candidate.get("agent", "session")
    if extra_labels:
        label = f"{label} (+{len(extra_labels)} more)"
        best_reason = f"{best_reason}, combined from {1 + len(extra_labels)} sessions"
    return ResolvedSource(
        mode=request.mode,
        session_key=best_candidate["session_key"],
        session_id=best_candidate.get("session_id"),
        label=label,
        project=request.project,
        started_at=started.isoformat() if started else None,
        ended_at=ended.isoformat() if ended else None,
        score=round(best_score, 3),
        reason=best_reason,
        raw_text=combined_text,
        preview=build_preview(combined_text),
    )
