from __future__ import annotations

import json
import mimetypes
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from urllib import request as urllib_request
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from .adapters.common import material_from_text
from .alarm_slots import AlarmSlotError, alarm_slot_suggestions, publish_alarm_slot
from .connectors.openclaw_sessions import SourceRequest, resolve_best_session_source
from .config_loader import load_user_config, resolve_run_request
from .domain import RunRequest
from .pipeline import build_from_material
from .pipeline.session_material import extract_material_from_session, load_recent_dream_context
from .openclaw_memory import append_audio_to_openclaw_memory, export_artifacts_to_openclaw_memory
from .playback import PlaybackError, play_audio
from .providers.music_common import MusicGenerationError
from .providers import detect_provider_status, generate_music_audio, music_generation_available
from .storage import write_artifacts
from .styles import STYLE_PRESETS

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "webui"
WEB_OUTPUT_DIR = ROOT / "content" / "output" / "webui-latest"
LATEST_AUDIO_PATH: Path | None = None
LATEST_MEMORY_PATH: Path | None = None
WRITE_TOKEN = secrets.token_urlsafe(24)

USES = ["alarm", "reminder", "celebrate"]

LLM_MODEL_PRESETS = {
    "openai": [
        {"model": "gpt-5.5", "label": "OpenAI GPT-5.5", "profile": "quality/latest"},
        {"model": "gpt-4o-mini", "label": "OpenAI GPT-4o mini", "profile": "fast/cheap"},
    ],
    "google": [
        {"model": "gemini-3.1-pro", "label": "Gemini 3.1 Pro", "profile": "quality/latest"},
        {"model": "gemini-2.5-flash", "label": "Gemini 2.5 Flash", "profile": "fast/cheap"},
    ],
    "openrouter": [
        {"model": "anthropic/claude-3.7-sonnet", "label": "OpenRouter Claude 3.7 Sonnet", "profile": "balanced"},
    ],
    "anthropic": [
        {"model": "claude-3-5-sonnet-latest", "label": "Anthropic Claude 3.5 Sonnet", "profile": "not wired yet"},
    ],
    "ollama": [
        {"model": "llama3.2", "label": "Ollama Llama 3.2", "profile": "local / not wired yet"},
    ],
}

_MODEL_DISCOVERY_CACHE: dict[str, tuple[float, list[dict]]] = {}
MODEL_DISCOVERY_TTL_SECONDS = 10 * 60


def _is_probably_placeholder_key(value: str | None) -> bool:
    lowered = (value or "").strip().lower()
    return not lowered or lowered.startswith(("test-", "fake-", "example", "your_", "sk-test"))


def _json_get(url: str, headers: dict[str, str] | None = None, timeout: int = 3) -> dict:
    req = urllib_request.Request(url, headers=headers or {}, method="GET")
    with urllib_request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _rank_model_id(model_id: str) -> tuple[int, str]:
    lowered = model_id.lower()
    score = 0
    for token, weight in (("5.5", 60), ("5", 50), ("4.1", 35), ("4o", 30), ("3.1", 60), ("3", 45), ("2.5", 25), ("pro", 12), ("flash", 6), ("mini", -4), ("embedding", -100), ("audio", -40), ("image", -40), ("tts", -40)):
        if token in lowered:
            score += weight
    return score, model_id


def _dedupe_model_rows(rows: list[dict], limit: int = 18) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    output: list[dict] = []
    for row in rows:
        key = (str(row.get("provider") or ""), str(row.get("model") or ""))
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        output.append(row)
        if len(output) >= limit:
            break
    return output


def _discover_openai_models() -> list[dict]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if _is_probably_placeholder_key(api_key):
        return []
    payload = _json_get("https://api.openai.com/v1/models", {"Authorization": f"Bearer {api_key}"})
    ids = [str(item.get("id") or "") for item in payload.get("data", []) if isinstance(item, dict)]
    usable = [model_id for model_id in ids if model_id.startswith(("gpt-", "o")) and not any(skip in model_id.lower() for skip in ("realtime", "transcribe", "tts", "image", "embedding"))]
    usable.sort(key=_rank_model_id, reverse=True)
    return [
        {"provider": "openai", "model": model_id, "label": f"OpenAI {model_id}", "profile": "detected"}
        for model_id in usable[:12]
    ]


def _discover_google_models() -> list[dict]:
    api_key = (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    if _is_probably_placeholder_key(api_key):
        return []
    payload = _json_get(f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}")
    rows: list[dict] = []
    for item in payload.get("models", []):
        if not isinstance(item, dict):
            continue
        methods = item.get("supportedGenerationMethods") or []
        raw_name = str(item.get("name") or "")
        model_id = raw_name.removeprefix("models/")
        if "generateContent" not in methods or "gemini" not in model_id.lower():
            continue
        rows.append({
            "provider": "google",
            "model": model_id,
            "label": item.get("displayName") or f"Gemini {model_id}",
            "profile": "detected",
        })
    rows.sort(key=lambda row: _rank_model_id(str(row["model"])), reverse=True)
    return rows[:12]


def _discover_openrouter_models() -> list[dict]:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if _is_probably_placeholder_key(api_key):
        return []
    payload = _json_get("https://openrouter.ai/api/v1/models", {"Authorization": f"Bearer {api_key}"})
    rows = []
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "")
        if not model_id:
            continue
        rows.append({
            "provider": "openrouter",
            "model": model_id,
            "label": item.get("name") or f"OpenRouter {model_id}",
            "profile": "detected",
        })
    rows.sort(key=lambda row: _rank_model_id(str(row["model"])), reverse=True)
    return rows[:12]


def _discover_provider_models(provider: str) -> list[dict]:
    now = time.time()
    cached = _MODEL_DISCOVERY_CACHE.get(provider)
    if cached and now - cached[0] < MODEL_DISCOVERY_TTL_SECONDS:
        return cached[1]
    try:
        if provider == "openai":
            rows = _discover_openai_models()
        elif provider == "google":
            rows = _discover_google_models()
        elif provider == "openrouter":
            rows = _discover_openrouter_models()
        else:
            rows = []
    except Exception:
        rows = []
    _MODEL_DISCOVERY_CACHE[provider] = (now, rows)
    return rows


def _llm_model_rows(provider_options) -> list[dict]:
    rows: list[dict] = []
    for opt in provider_options:
        presets = [
            {**preset, "provider": opt.name}
            for preset in LLM_MODEL_PRESETS.get(opt.name, [{"model": opt.default_model, "label": f"{opt.name} {opt.default_model}", "profile": "default"}])
        ]
        discovered = _discover_provider_models(opt.name) if opt.available and opt.runtime_supported else []
        for preset in presets + discovered:
            rows.append({
                "provider": opt.name,
                "model": preset["model"],
                "label": preset["label"],
                "profile": preset["profile"],
                "available": opt.available,
                "runtime_supported": opt.runtime_supported,
            })
    return _dedupe_model_rows(rows, limit=36)


def _json(start_response, payload: dict, status: str = "200 OK"): 
    body = json.dumps(payload).encode("utf-8")
    start_response(status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))])
    return [body]


def _read_json_body(environ) -> dict:
    length = int(environ.get("CONTENT_LENGTH") or 0)
    raw = environ["wsgi.input"].read(length) if length else b"{}"
    return json.loads(raw.decode("utf-8") or "{}")


def _is_safe_local_write(environ) -> bool:
    token = environ.get("HTTP_X_S2S_TOKEN") or ""
    if token != WRITE_TOKEN:
        return False
    host = (environ.get("HTTP_HOST") or "").split(":", 1)[0].lower()
    origin = environ.get("HTTP_ORIGIN") or ""
    if origin:
        try:
            origin_host = origin.split("//", 1)[1].split("/", 1)[0].split(":", 1)[0].lower()
        except Exception:
            return False
        allowed = {host, "127.0.0.1", "localhost", "eheye", "100.126.49.109"}
        if origin_host not in allowed:
            return False
    return True


def _guard_write_endpoint(environ, start_response):
    if _is_safe_local_write(environ):
        return None
    return _json(start_response, {"error": "forbidden", "detail": "Invalid local write token or origin."}, "403 Forbidden")


def _serve_file(start_response, file_path: Path):
    if not file_path.exists() or not file_path.is_file():
        return _json(start_response, {"error": "not_found"}, "404 Not Found")
    content = file_path.read_bytes()
    mime, _ = mimetypes.guess_type(str(file_path))
    start_response("200 OK", [
        ("Content-Type", f"{mime or 'application/octet-stream'}"),
        ("Content-Length", str(len(content))),
        ("Cache-Control", "no-cache, no-store, must-revalidate"),
        ("Pragma", "no-cache"),
        ("Expires", "0")
    ])
    return [content]


def _serve_web_asset(start_response, relative_path: str):
    web_root = WEB_DIR.resolve()
    target = (WEB_DIR / relative_path.lstrip("/")).resolve()
    if target != web_root and web_root not in target.parents:
        return _json(start_response, {"error": "not_found"}, "404 Not Found")
    return _serve_file(start_response, target)


def _bounded_int(value, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, minimum), maximum)


def _handle_generate(start_response, payload: dict):
    raw_text = (payload.get("raw_text") or "").strip()
    source_mode = (payload.get("source_mode") or "manual").strip() or "manual"
    if not raw_text:
        if source_mode == "manual":
            return _json(start_response, {"error": "raw_text_required"}, "400 Bad Request")

    user_config = load_user_config(payload.get("config") or None)
    preferred_llm_provider = (payload.get("llm_provider") or "").strip() or None
    preferred_llm_model = (payload.get("llm_model") or "").strip() or None
    if preferred_llm_provider:
        user_config.llm_provider = preferred_llm_provider
    if preferred_llm_model:
        user_config.llm_model = preferred_llm_model
    request = resolve_run_request(
        user_config,
        RunRequest(
            use=payload.get("use") or None,
            genre=payload.get("genre") or None,
            focus=payload.get("focus") or None,
            sound_reference=payload.get("sound_reference") or None,
            delivery=(payload.get("delivery") or None),
            duration_seconds=payload.get("duration_seconds") or None,
            input_source=payload.get("input_source") or "text",
            source_mode=source_mode.replace("-", "_"),
            source_session_key=(payload.get("source_session_key") or None),
            lookback_hours=_bounded_int(payload.get("lookback_hours"), 36, minimum=1, maximum=24 * 14),
            project=(payload.get("project") or None),
            mode=(payload.get("mode") or None),
            style=(payload.get("style") or None),
            question=(payload.get("question") or None),
        ),
    )
    resolved_source = None
    if request.source_mode == "manual":
        material = material_from_text(
            source=request.input_source,
            title=(payload.get("title") or "pasted-session").strip() or "pasted-session",
            raw_text=raw_text,
            project=request.project,
        )
    else:
        # Use-aware lookback: alarm needs previous day context, others need broader window
        default_lookback = 72 if request.resolved_use == "alarm" else 48
        resolved_source = resolve_best_session_source(
            SourceRequest(
                mode=request.source_mode,
                session_key=request.source_session_key,
                project=request.project,
                lookback_hours=int(request.lookback_hours or default_lookback),
                use=request.resolved_use,
            )
        )
        if resolved_source is None:
            return _json(start_response, {"error": "source_not_found"}, "404 Not Found")
        material = extract_material_from_session(
            resolved_source,
            title=(payload.get("title") or resolved_source.label or "auto-session").strip() or "auto-session",
            use=request.resolved_use,
        )
    _prev_lyrics_path = WEB_OUTPUT_DIR / "lyrics.txt"
    _previous_lyrics: str | None = None
    if _prev_lyrics_path.exists():
        try:
            _previous_lyrics = _prev_lyrics_path.read_text(encoding="utf-8").strip() or None
        except Exception:
            pass
    artifacts = build_from_material(material, user_config, request, previous_lyrics=_previous_lyrics)
    files = write_artifacts(WEB_OUTPUT_DIR, artifacts)
    memory_path = export_artifacts_to_openclaw_memory(artifacts, files)
    global LATEST_MEMORY_PATH
    LATEST_MEMORY_PATH = memory_path
    return _json(
        start_response,
        {
            "pulse": artifacts.pulse,
            "lyrics": artifacts.lyrics,
            "music_prompt": artifacts.music_prompt,
            "manifest": artifacts.manifest,
            "source": None if resolved_source is None else {
                "mode": resolved_source.mode,
                "session_key": resolved_source.session_key,
                "label": resolved_source.label,
                "project": resolved_source.project,
                "started_at": resolved_source.started_at,
                "ended_at": resolved_source.ended_at,
                "score": resolved_source.score,
                "reason": resolved_source.reason,
                "preview": resolved_source.preview,
            },
            "files": {key: str(path) for key, path in files.items()},
            "openclaw_memory": None if memory_path is None else str(memory_path),
        },
    )


def _handle_resolve_source(start_response, params: dict[str, list[str]]):
    mode = (params.get("mode") or ["auto"])[0].strip() or "auto"
    project = (params.get("project") or [""])[0].strip() or None
    session_key = (params.get("session_key") or [""])[0].strip() or None
    lookback_hours = _bounded_int((params.get("lookback_hours") or ["36"])[0], 36, minimum=1, maximum=24 * 14)
    source = resolve_best_session_source(
        SourceRequest(
            mode=mode.replace("-", "_"),
            session_key=session_key,
            project=project,
            lookback_hours=lookback_hours,
            use=(params.get("use") or [None])[0],
            target_date=(params.get("target_date") or [None])[0],
        )
    )
    if source is None:
        return _json(start_response, {"ok": False, "error": "source_not_found"}, "404 Not Found")
    return _json(
        start_response,
        {
            "ok": True,
            "source": {
                "mode": source.mode,
                "session_key": source.session_key,
                "label": source.label,
                "project": source.project,
                "started_at": source.started_at,
                "ended_at": source.ended_at,
                "score": source.score,
                "reason": source.reason,
                "preview": source.preview,
            },
        },
    )


def _handle_pick_alarm_slot_folder(start_response):
    if not sys.platform.startswith("win"):
        return _json(start_response, {"error": "unsupported_platform", "detail": "Native folder picker is currently Windows-only."}, "400 Bad Request")
    script = r'''
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = "Select your session-to-song alarm sync folder"
$dialog.ShowNewFolderButton = $true
$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
  Write-Output $dialog.SelectedPath
}
'''.strip()
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return _json(start_response, {"error": "picker_timeout", "detail": "Folder picker timed out."}, "408 Request Timeout")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "Folder picker failed.").strip()
        return _json(start_response, {"error": "picker_failed", "detail": detail}, "500 Internal Server Error")
    selected = completed.stdout.strip().splitlines()[-1].strip() if completed.stdout.strip() else ""
    if not selected:
        return _json(start_response, {"cancelled": True})
    return _json(start_response, {"path": selected})


def _latest_audio_path() -> Path:
    return LATEST_AUDIO_PATH or WEB_OUTPUT_DIR / "generated_audio.mp3"


def _handle_publish_alarm_slot(start_response, payload: dict):
    name = (payload.get("name") or "audio").strip()
    if name != "audio" or payload.get("path"):
        return _json(start_response, {"error": "bad_file", "detail": "Web publish can only use the latest generated audio."}, "400 Bad Request")
    path = _latest_audio_path()
    try:
        result = publish_alarm_slot(
            path,
            slot=(payload.get("slot") or "morning"),
            target_dir=(payload.get("target_dir") or None),
            create=False,
        )
    except AlarmSlotError as exc:
        return _json(start_response, {"error": "alarm_slot_failed", "detail": str(exc)}, "500 Internal Server Error")
    append_audio_to_openclaw_memory(LATEST_MEMORY_PATH, alarm_slot=result)
    return _json(start_response, result.to_dict())


def _handle_play_audio(start_response, payload: dict):
    name = (payload.get("name") or "audio").strip()
    if name != "audio" or payload.get("path"):
        return _json(start_response, {"error": "bad_file", "detail": "Web playback can only use the latest generated audio."}, "400 Bad Request")
    path = _latest_audio_path()
    try:
        result = play_audio(
            path,
            backend=(payload.get("backend") or "auto"),
            volume=_bounded_int(payload.get("volume"), 100, minimum=0, maximum=100),
            block=bool(payload.get("block") or False),
            timeout_seconds=_bounded_int(payload.get("timeout_seconds"), 600, minimum=1, maximum=3600),
        )
    except PlaybackError as exc:
        return _json(start_response, {"error": "playback_failed", "detail": str(exc)}, "500 Internal Server Error")
    return _json(start_response, result.to_dict())


def _handle_generate_audio(start_response, payload: dict):
    prompt = (payload.get("music_prompt") or "").strip()
    if not prompt:
        return _json(start_response, {"error": "music_prompt_required"}, "400 Bad Request")

    duration_seconds = _bounded_int(payload.get("duration_seconds"), 45, minimum=15, maximum=600)
    preferred_model = payload.get("music_model") or None
    preferred_provider = payload.get("music_provider") or None
    user_config = load_user_config(payload.get("config") or None)

    try:
        generated = generate_music_audio(
            prompt=prompt,
            out_dir=WEB_OUTPUT_DIR,
            duration_seconds=duration_seconds,
            user_config=user_config,
            preferred_model=preferred_model,
            preferred_provider=preferred_provider,
        )
    except MusicGenerationError as exc:
        return _json(start_response, {"error": "audio_generation_failed", "detail": str(exc)}, "500 Internal Server Error")

    global LATEST_AUDIO_PATH
    LATEST_AUDIO_PATH = generated.path
    append_audio_to_openclaw_memory(LATEST_MEMORY_PATH, audio=generated)

    return _json(
        start_response,
        {
            "audio_url": "/api/files?name=audio",
            "audio_path": str(generated.path),
            "mime_type": generated.mime_type,
            "provider": generated.provider,
            "model": generated.model,
            "notes": generated.prompt_notes,
        },
    )


def app(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()

    if path == "/api/health":
        return _json(start_response, {"ok": True})

    if path == "/api/bootstrap":
        user_config = load_user_config()
        provider_status = detect_provider_status(
            llm_provider=user_config.llm_provider,
            llm_model=user_config.llm_model,
            music_provider=user_config.music_provider,
            music_model=user_config.music_model,
        )
        return _json(
            start_response,
            {
                "genres": [
                    {"key": preset.key, "label": preset.label}
                    for preset in STYLE_PRESETS.values()
                ],
                "defaults": {
                    "use": "celebrate",
                    "genre": user_config.genre_by_use.get("celebrate", user_config.default_genre),
                    "delivery": user_config.delivery,
                    "duration_seconds": user_config.duration_seconds,
                    "input_source": "text",
                    "source_mode": "auto",
                    "lookback_hours": 36,
                    "focus": "what shipped and why it matters",
                    "music_model": provider_status.music.model or user_config.music_model,
                    "configured_llm_provider": user_config.llm_provider,
                    "configured_llm_model": user_config.llm_model,
                    "active_llm_provider": provider_status.llm.provider,
                    "active_llm_model": provider_status.llm.model,
                },
                "uses": USES,
                "source_modes": ["auto", "current_session", "recent_session", "manual"],
                "durations": [30, 45, 60, 90, 180, 240],
                "deliveries": ["save", "immediate", "scheduled", "milestone"],
                "write_token": WRITE_TOKEN,
                "audio_generation": {
                    "available": music_generation_available(user_config),
                    "provider": provider_status.music.provider,
                    "model": provider_status.music.model,
                    "message": provider_status.music.message,
                },
                "music_providers": [
                    {
                        "provider": opt.name,
                        "model": opt.default_model,
                        "available": opt.available,
                        "runtime_supported": opt.runtime_supported,
                    }
                    for opt in provider_status.music_options
                    if opt.runtime_supported
                ],
                "llm_providers": [
                    {
                        "provider": opt.name,
                        "model": opt.default_model,
                        "available": opt.available,
                        "runtime_supported": opt.runtime_supported,
                    }
                    for opt in provider_status.llm_options
                ],
                "llm_models": _llm_model_rows(provider_status.llm_options),
            },
        )

    if path == "/api/generate" and method == "POST":
        blocked = _guard_write_endpoint(environ, start_response)
        if blocked is not None:
            return blocked
        try:
            return _handle_generate(start_response, _read_json_body(environ))
        except Exception as exc:  # pragma: no cover - debug path
            return _json(start_response, {"error": "generation_failed", "detail": str(exc)}, "500 Internal Server Error")

    if path == "/api/sources/resolve" and method == "GET":
        return _handle_resolve_source(start_response, parse_qs(environ.get("QUERY_STRING", "")))

    if path == "/api/alarm-slot/suggestions" and method == "GET":
        return _json(start_response, {"suggestions": alarm_slot_suggestions()})

    if path == "/api/generate-audio" and method == "POST":
        blocked = _guard_write_endpoint(environ, start_response)
        if blocked is not None:
            return blocked
        try:
            return _handle_generate_audio(start_response, _read_json_body(environ))
        except Exception as exc:  # pragma: no cover - debug path
            return _json(start_response, {"error": "audio_generation_failed", "detail": str(exc)}, "500 Internal Server Error")

    if path == "/api/play-audio" and method == "POST":
        blocked = _guard_write_endpoint(environ, start_response)
        if blocked is not None:
            return blocked
        try:
            return _handle_play_audio(start_response, _read_json_body(environ))
        except Exception as exc:  # pragma: no cover - debug path
            return _json(start_response, {"error": "playback_failed", "detail": str(exc)}, "500 Internal Server Error")

    if path == "/api/alarm-slot/pick-folder" and method == "POST":
        blocked = _guard_write_endpoint(environ, start_response)
        if blocked is not None:
            return blocked
        return _handle_pick_alarm_slot_folder(start_response)

    if path == "/api/alarm-slot" and method == "POST":
        blocked = _guard_write_endpoint(environ, start_response)
        if blocked is not None:
            return blocked
        try:
            return _handle_publish_alarm_slot(start_response, _read_json_body(environ))
        except Exception as exc:  # pragma: no cover - debug path
            return _json(start_response, {"error": "alarm_slot_failed", "detail": str(exc)}, "500 Internal Server Error")

    if path.startswith("/api/files"):
        params = parse_qs(environ.get("QUERY_STRING", ""))
        name = (params.get("name") or [""])[0]
        allowed = {
            "pulse": WEB_OUTPUT_DIR / "pulse.txt",
            "lyrics": WEB_OUTPUT_DIR / "lyrics.txt",
            "music_prompt": WEB_OUTPUT_DIR / "music_prompt.txt",
            "manifest": WEB_OUTPUT_DIR / "run_manifest.json",
            "audio": _latest_audio_path(),
        }
        target = allowed.get(name)
        if not target:
            return _json(start_response, {"error": "bad_file"}, "400 Bad Request")
        return _serve_file(start_response, target)

    if path == "/":
        return _serve_file(start_response, WEB_DIR / "index.html")

    return _serve_web_asset(start_response, path)


def run(host: str = "127.0.0.1", port: int = 8311):
    with make_server(host, port, app) as server:
        print(f"session-to-song web UI running at http://{host}:{port}")
        server.serve_forever()


if __name__ == "__main__":
    run()
