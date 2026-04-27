from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from pathlib import Path

from .domain import SessionMaterial

VIDEO_STYLES = ("launch", "gritty-battle", "founder-update")
RENDER_PROVIDERS = ("none",)

STYLE_GUIDANCE = {
    "launch": {
        "tone": "clean launch trailer, confident, bright, product-led",
        "visual": "cinematic SaaS/product launch visuals, polished UI abstractions, warm studio light",
        "arc": "problem, proof, momentum, call to action",
    },
    "gritty-battle": {
        "tone": "gritty founder battle trailer, intense but grounded, earned momentum",
        "visual": "dark workbench, glowing screens, high-contrast practical light, fast cuts",
        "arc": "pressure, constraint, focused build, breakthrough",
    },
    "founder-update": {
        "tone": "direct founder update, clear and human, investor/customer friendly",
        "visual": "simple documentary product update, desk, notes, diagrams, calm camera moves",
        "arc": "what changed, why it matters, what comes next",
    },
}

_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|passwd|auth|bearer)\s*[:=]\s*[^\s,;]+"
)
_WINDOWS_PATH_RE = re.compile(r"(?i)\b[a-z]:\\(?:[^\s`'\")<>|]+\\?)+")
_UNIX_PRIVATE_PATH_RE = re.compile(r"/(?:Users|home)/[^\s`'\")]+")
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_LONG_TOKEN_RE = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|[A-Za-z0-9_-]{32,})\b")
_PHONE_ID_RE = re.compile(r"(?i)\b(phone|device|android|imei|serial)\s*(id|identifier|serial)?\s*[:=#-]?\s*[A-Za-z0-9_.:-]{6,}")

PRIVATE_NAME_REWRITES = {
    "Drew": "the founder",
    "Drew's": "the founder's",
    "dbagl": "local-user",
}


@dataclass
class VideoArtifacts:
    prompt_pack: str
    video_model_prompt: str
    manifest: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def scrub_public_text(text: str | None) -> str:
    """Remove private/local implementation details before public creative output."""
    if not text:
        return ""
    cleaned = str(text)
    cleaned = _SECRET_ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}=[redacted secret]", cleaned)
    cleaned = _WINDOWS_PATH_RE.sub("[local path]", cleaned)
    cleaned = _UNIX_PRIVATE_PATH_RE.sub("[local path]", cleaned)
    cleaned = _EMAIL_RE.sub("[email]", cleaned)
    cleaned = _PHONE_ID_RE.sub(lambda m: f"{m.group(1)} id: [redacted device id]", cleaned)
    cleaned = _LONG_TOKEN_RE.sub("[redacted token]", cleaned)
    for private, public in PRIVATE_NAME_REWRITES.items():
        cleaned = re.sub(rf"\b{re.escape(private)}\b", public, cleaned)
    cleaned = re.sub(r"`?\b(?:src|server|webui|tests|docs|scripts|content)/[^\s`]+`?:?", "[repo file]", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"`?\b[a-z0-9_-]+\.(?:tsx|ts|jsx|js|py|md|css|json|env)`?:?", "[repo file]", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
    return cleaned or "the project moved forward"


def _words(line: str, limit: int) -> str:
    safe = scrub_public_text(line)
    parts = safe.split()
    if len(parts) > limit:
        return " ".join(parts[:limit]) + " ..."
    return safe


def _keywords(text: str, limit: int = 6) -> list[str]:
    counts: dict[str, int] = {}
    stop = {
        "the", "and", "for", "with", "that", "this", "from", "into", "have", "has", "was", "were",
        "project", "session", "openclaw", "local", "path", "redacted", "secret", "token", "repo", "file",
    }
    safe = scrub_public_text(text).lower()
    for token in re.findall(r"[a-z][a-z0-9'-]+", safe):
        if len(token) < 4 or token in stop:
            continue
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [word for word, _ in ranked[:limit]]


def _facts(material: SessionMaterial, limit: int = 5) -> list[str]:
    selected: list[str] = []
    for item in [*material.wins, *material.blockers, *material.next_actions]:
        fact = _words(item, 16)
        if fact and fact not in selected:
            selected.append(fact)
        if len(selected) >= limit:
            break
    if not selected:
        for raw in material.raw_text.splitlines():
            fact = _words(raw.strip(" -\t"), 16)
            if fact and fact not in selected:
                selected.append(fact)
            if len(selected) >= limit:
                break
    return selected or ["A focused build session produced a clearer product story and next step."]


def _stamp(seconds: int) -> str:
    seconds = max(0, int(seconds))
    minutes, remainder = divmod(seconds, 60)
    return f"{minutes}:{remainder:02d}"


def _shot_rows(style: str, facts: list[str], duration_seconds: int) -> list[tuple[str, str, str, str]]:
    step = max(5, duration_seconds // 6)
    labels = [
        ("0", "Cold open", "Slow push-in", "A messy signal becomes a clear launch"),
        (str(step), "Problem frame", "Quick cuts", facts[0]),
        (str(step * 2), "Build proof", "Match cuts across notes, UI, and diagrams", facts[min(1, len(facts) - 1)]),
        (str(step * 3), "Tension", "Tighter handheld / faster edit", facts[min(2, len(facts) - 1)]),
        (str(step * 4), "Resolution", "Clean reveal, calmer camera", facts[min(3, len(facts) - 1)]),
        (str(duration_seconds - 4), "End card", "Hold for readability", "Text-only prompt pack. Manual render required."),
    ]
    if style == "founder-update":
        labels[0] = ("0", "Founder desk open", "Static medium shot", "Here is what changed and why it matters")
    elif style == "gritty-battle":
        labels[0] = ("0", "After-hours build table", "Hard cut from black", "The work got sharper under pressure")
    return [(_stamp(int(t)), visual, motion, text) for t, visual, motion, text in labels]


def build_video_prompt_pack(
    material: SessionMaterial,
    *,
    project: str | None = None,
    style: str = "launch",
    duration_seconds: int = 30,
    render_provider: str = "none",
) -> VideoArtifacts:
    if style not in VIDEO_STYLES:
        raise ValueError(f"Unsupported video style: {style}")
    if render_provider != "none":
        raise ValueError("MVP only supports render_provider='none'; rendering is manual/external.")
    duration_seconds = max(15, min(600, int(duration_seconds)))
    guidance = STYLE_GUIDANCE[style]
    project_name = scrub_public_text(project or material.project or "the project")
    facts = _facts(material)
    keywords = _keywords(material.raw_text + "\n" + "\n".join(facts))
    keyword_phrase = ", ".join(keywords[:4]) or "clarity, momentum, launch"
    core_fact = facts[0]

    concept = (
        f"A {duration_seconds}-second {guidance['tone']} for {project_name}: "
        f"turn the session's strongest proof point into a public-safe launch trailer."
    )
    logline = f"{project_name} moves from scattered context to a sharper public story: {core_fact}."

    cut1 = max(3, duration_seconds // 6)
    cut2 = max(cut1 + 3, duration_seconds // 3)
    cut3 = max(cut2 + 3, (duration_seconds * 3) // 5)
    cut4 = max(cut3 + 3, (duration_seconds * 5) // 6)
    cut4 = min(cut4, max(cut3 + 1, duration_seconds - 1))
    voiceover_lines = [
        (f"{_stamp(0)}-{_stamp(cut1)}", "Every build starts as a wall of signals."),
        (f"{_stamp(cut1)}-{_stamp(cut2)}", f"Then one thread gets clear: {core_fact}."),
        (f"{_stamp(cut2)}-{_stamp(cut3)}", f"The work tightens around {keyword_phrase}."),
        (f"{_stamp(cut3)}-{_stamp(cut4)}", "The rough edges become a path someone else can understand."),
        (f"{_stamp(cut4)}-{_stamp(duration_seconds)}", "Now the story is ready to show, test, and refine."),
    ]
    shots = _shot_rows(style, facts, duration_seconds)
    image_prompts = [
        f"Cinematic keyframe, {guidance['visual']}, abstract product context for {project_name}, no readable private text, no real names, no logos, 16:9.",
        f"Close-up keyframe of anonymized notes becoming a clean storyboard, theme keywords: {keyword_phrase}, no secrets or local paths visible, 16:9.",
        f"Hero keyframe for a public launch trailer, {guidance['tone']}, subtle interface shapes, safe generic copy only, 16:9.",
    ]
    video_model_prompt = (
        f"Create a {duration_seconds}-second launch trailer in a {guidance['tone']} style. "
        f"Arc: {guidance['arc']}. Project label: {project_name}. "
        f"Use only public-safe generic visuals; do not show private names, local file paths, device IDs, API keys, emails, secrets, or readable proprietary text. "
        f"Visual direction: {guidance['visual']}. "
        f"Narrative facts to imply, not quote verbatim: {' | '.join(facts[:4])}. "
        "End on a clean title card with generic call-to-action text: 'Ready to launch the next version.'"
    )

    shot_table = "\n".join(
        ["| Time | Visual | Motion | On-screen text |", "| --- | --- | --- | --- |"]
        + [f"| {t} | {v} | {m} | {scrub_public_text(text)} |" for t, v, m, text in shots]
    )
    voiceover = "\n".join(f"- **{t}:** {line}" for t, line in voiceover_lines)
    keyframes = "\n".join(f"{idx}. {prompt}" for idx, prompt in enumerate(image_prompts, start=1))
    fact_lines = "\n".join(f"- {fact}" for fact in facts)

    prompt_pack = f"""# Session-to-Video Trailer Prompt Pack

## Render Policy

- Render provider: `{render_provider}`.
- This MVP generated text/markdown only. It did not call Sora, Veo, Gemini, Runway, or any paid video API.
- Rendering is manual/external; review costs and privacy before pasting into a third-party tool.

## Trailer Concept

{concept}

## Logline

{logline}

## Public-Safe Source Facts

{fact_lines}

## 30-Second Script / Voiceover

{voiceover}

## Shot List / Storyboard

{shot_table}

## Image Keyframe Prompts

{keyframes}

## Video Model Prompt

{video_model_prompt}

## Safety / Redaction Notes

- Public wording only: avoid real private names, phone/device IDs, local absolute paths, secrets, emails, and proprietary readable text.
- Keep UI/screens abstract unless the project owner approves specific screenshots.
- If a paid render provider is used manually, confirm pricing and data-retention terms first.
- Run a final human review before publishing.
"""

    manifest = {
        "kind": "session-to-video",
        "style": style,
        "duration_seconds": duration_seconds,
        "render_provider": render_provider,
        "render_invoked": False,
        "project": project_name,
        "input_source": material.source,
        "title": scrub_public_text(material.title),
        "keywords": keywords,
        "files_expected": ["trailer_prompt_pack.md", "video_model_prompt.txt", "run_manifest.json"],
    }
    return VideoArtifacts(prompt_pack=prompt_pack, video_model_prompt=video_model_prompt, manifest=manifest)


def write_video_artifacts(outdir: str | Path, artifacts: VideoArtifacts) -> dict[str, Path]:
    out_path = Path(outdir)
    out_path.mkdir(parents=True, exist_ok=True)
    files = {
        "prompt_pack": out_path / "trailer_prompt_pack.md",
        "video_model_prompt": out_path / "video_model_prompt.txt",
        "manifest": out_path / "run_manifest.json",
    }
    files["prompt_pack"].write_text(artifacts.prompt_pack.rstrip() + "\n", encoding="utf-8")
    files["video_model_prompt"].write_text(artifacts.video_model_prompt.rstrip() + "\n", encoding="utf-8")
    files["manifest"].write_text(json.dumps(artifacts.manifest, indent=2) + "\n", encoding="utf-8")
    return files
