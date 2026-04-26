from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
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


def _openclaw_root() -> Path:
    return Path(os.getenv("OPENCLAW_HOME", str(Path.home() / ".openclaw")))


def _session_registry_files() -> list[Path]:
    root = _openclaw_root() / "agents"
    if not root.exists():
        return []
    return list(root.glob("*/sessions/sessions.json"))


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
        return lines[-limit:]
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
    project_score = 0.0
    if project and (project_matches(lowered, project) or project_matches(label, project)):
        project_score = 1.0
    elif project:
        project_score = -0.25
    channel = str(session.get("channel") or "")
    channel_score = 0.2 if channel in {"telegram", "signal", "webchat"} else 0.0
    score = recency_score * 0.4 + volume_score * 0.2 + progress_score * 0.3 + project_score * 0.1 + channel_score
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
