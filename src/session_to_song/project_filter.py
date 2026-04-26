from __future__ import annotations

import re


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def _compact_for_match(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def project_terms(project: str | None) -> set[str]:
    """Return conservative project match terms.

    Prefer whole project-name matches over broad token matches so a project like
    ``session-to-song`` does not accidentally match every line mentioning only
    "session" or "song".
    """
    raw = (project or "").strip()
    if not raw:
        return set()
    normalized = _normalize_for_match(raw)
    compact = _compact_for_match(raw)
    terms = {term for term in {raw.lower(), normalized, compact} if len(term) >= 3}
    tokens = normalized.split()
    if len(tokens) == 1 and len(tokens[0]) >= 3:
        terms.add(tokens[0])
    return terms


def project_matches(text: str, project: str | None) -> bool:
    terms = project_terms(project)
    if not terms:
        return False
    normalized_text = _normalize_for_match(text)
    compact_text = _compact_for_match(text)
    lowered_text = text.lower()
    for term in terms:
        if " " in term and term in normalized_text:
            return True
        if " " not in term and (term in compact_text or term in normalized_text.split() or term in lowered_text):
            return True
    return False


def filter_lines_for_project(lines: list[str], project: str | None) -> list[str]:
    if not project:
        return lines
    return [line for line in lines if project_matches(line, project)]


def _split_project_filter_units(line: str) -> list[str]:
    """Split mixed context lines so one project hit does not drag in unrelated facts."""
    stripped = line.strip()
    if not stripped:
        return []
    # Dream/memory corpora often store many semicolon/bullet-delimited facts on
    # one physical line. Project filtering must operate on the fact-sized units,
    # not the whole line, or a single project mention leaks unrelated projects.
    units = [part.strip(" -•\t") for part in re.split(r"\s+[•;]\s+|(?<=[.!?])\s+", stripped)]
    units = [unit for unit in units if unit]
    return units or [stripped]


def filter_text_for_project(text: str, project: str | None) -> str:
    if not text.strip() or not project:
        return text
    filtered: list[str] = []
    for line in [line for line in text.splitlines() if line.strip()]:
        for unit in _split_project_filter_units(line):
            if project_matches(unit, project):
                filtered.append(unit)
    return "\n".join(filtered)
