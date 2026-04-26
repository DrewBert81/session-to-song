from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from .audio_utils import trim_audio_to_mp3
from .music_common import GeneratedAudio, MusicGenerationError

DEFAULT_COMFY_LOCAL_BASE_URL = "http://127.0.0.1:8188"
DEFAULT_COMFY_CLOUD_BASE_URL = "https://cloud.comfy.org"
DEFAULT_PROMPT_INPUT_NAME = "text"
DEFAULT_POLL_INTERVAL_MS = 1500
DEFAULT_TIMEOUT_MS = 300000
DEFAULT_COMFY_MODEL = "workflow"


@dataclass(frozen=True)
class ComfyMusicRuntimeStatus:
    mode: str
    workflow_path: str | None
    prompt_node_id: str | None
    output_node_id: str | None
    api_key_present: bool
    available: bool
    runtime_supported: bool
    message: str = ""


@dataclass(frozen=True)
class ComfyMusicConfig:
    mode: str
    base_url: str
    workflow_path: Path
    prompt_node_id: str
    prompt_input_name: str
    output_node_id: str | None
    timeout_ms: int
    poll_interval_ms: int
    api_key: str | None = None


@dataclass(frozen=True)
class _DownloadedAsset:
    file_name: str
    mime_type: str
    data: bytes
    node_id: str


def _normalize_mode(value: str | None) -> str:
    return "cloud" if (value or "").strip().lower() == "cloud" else "local"


def _resolve_base_url(mode: str, environ: dict[str, str]) -> str:
    default = DEFAULT_COMFY_CLOUD_BASE_URL if mode == "cloud" else DEFAULT_COMFY_LOCAL_BASE_URL
    candidate = (environ.get("COMFY_BASE_URL") or "").strip()
    if not candidate:
        return default
    parsed = urllib_parse.urlparse(candidate)
    if parsed.scheme and parsed.netloc:
        return candidate.rstrip("/")
    return default


def describe_comfy_music_runtime(environ: dict[str, str] | None = None) -> ComfyMusicRuntimeStatus:
    env = dict(os.environ if environ is None else environ)
    mode = _normalize_mode(env.get("COMFY_MODE"))
    workflow_path = (env.get("COMFY_MUSIC_WORKFLOW_PATH") or "").strip() or None
    prompt_node_id = (env.get("COMFY_MUSIC_PROMPT_NODE_ID") or "").strip() or None
    output_node_id = (env.get("COMFY_MUSIC_OUTPUT_NODE_ID") or "").strip() or None
    api_key_present = bool((env.get("COMFY_API_KEY") or env.get("COMFY_CLOUD_API_KEY") or "").strip())

    missing: list[str] = []
    if not workflow_path:
        missing.append("COMFY_MUSIC_WORKFLOW_PATH")
    if not prompt_node_id:
        missing.append("COMFY_MUSIC_PROMPT_NODE_ID")
    if mode == "cloud" and not api_key_present:
        missing.append("COMFY_API_KEY or COMFY_CLOUD_API_KEY")

    if missing:
        qualifier = " and auth" if mode == "cloud" else ""
        return ComfyMusicRuntimeStatus(
            mode=mode,
            workflow_path=workflow_path,
            prompt_node_id=prompt_node_id,
            output_node_id=output_node_id,
            api_key_present=api_key_present,
            available=False,
            runtime_supported=True,
            message=(
                "Comfy music runtime is not configured. "
                f"Set {', '.join(missing)} and provide a workflow JSON path plus prompt node id"
                f" for the {mode} runtime{qualifier}."
            ),
        )

    return ComfyMusicRuntimeStatus(
        mode=mode,
        workflow_path=workflow_path,
        prompt_node_id=prompt_node_id,
        output_node_id=output_node_id,
        api_key_present=api_key_present,
        available=True,
        runtime_supported=True,
        message=(
            f"Comfy {mode} music workflow ready"
            + (f" via node {prompt_node_id}" if prompt_node_id else "")
            + (f", output node {output_node_id}" if output_node_id else "")
            + "."
        ),
    )


def _load_workflow(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MusicGenerationError(f"Comfy workflow file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise MusicGenerationError(f"Comfy workflow JSON is invalid: {path}") from exc
    if not isinstance(payload, dict):
        raise MusicGenerationError(f"Comfy workflow at {path} must be a JSON object.")
    return payload


def _resolve_config() -> ComfyMusicConfig:
    status = describe_comfy_music_runtime()
    if not status.runtime_supported or not status.workflow_path or not status.prompt_node_id:
        raise MusicGenerationError(status.message or "Comfy music runtime is not configured.")

    api_key = (os.getenv("COMFY_API_KEY") or os.getenv("COMFY_CLOUD_API_KEY") or "").strip() or None
    timeout_ms = int((os.getenv("COMFY_MUSIC_TIMEOUT_MS") or str(DEFAULT_TIMEOUT_MS)).strip() or DEFAULT_TIMEOUT_MS)
    poll_interval_ms = int((os.getenv("COMFY_MUSIC_POLL_INTERVAL_MS") or str(DEFAULT_POLL_INTERVAL_MS)).strip() or DEFAULT_POLL_INTERVAL_MS)

    return ComfyMusicConfig(
        mode=status.mode,
        base_url=_resolve_base_url(status.mode, os.environ),
        workflow_path=Path(status.workflow_path),
        prompt_node_id=status.prompt_node_id,
        prompt_input_name=(os.getenv("COMFY_MUSIC_PROMPT_INPUT_NAME") or DEFAULT_PROMPT_INPUT_NAME).strip() or DEFAULT_PROMPT_INPUT_NAME,
        output_node_id=status.output_node_id,
        timeout_ms=timeout_ms,
        poll_interval_ms=poll_interval_ms,
        api_key=api_key,
    )


def _json_request(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, payload: dict | None = None, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib_request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib_request.urlopen(request, timeout=max(1, int(timeout_ms / 1000))) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # pragma: no cover - network failure path
        raise MusicGenerationError(f"Comfy request failed for {url}: {exc}") from exc


def _download_bytes(url: str, headers: dict[str, str], timeout_ms: int) -> tuple[bytes, str]:
    request = urllib_request.Request(url, headers=headers, method="GET")
    try:
        with urllib_request.urlopen(request, timeout=max(1, int(timeout_ms / 1000))) as response:
            return response.read(), response.headers.get("Content-Type") or "application/octet-stream"
    except Exception as exc:  # pragma: no cover - network failure path
        raise MusicGenerationError(f"Comfy output download failed: {exc}") from exc


def _set_workflow_input(workflow: dict, node_id: str, input_name: str, value: str) -> None:
    node = workflow.get(node_id)
    if not isinstance(node, dict):
        raise MusicGenerationError(f'Comfy workflow missing node "{node_id}".')
    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        raise MusicGenerationError(f'Comfy workflow node "{node_id}" is missing an inputs object.')
    inputs[input_name] = value


def _extract_history_entry(history: dict, prompt_id: str) -> dict | None:
    if not isinstance(history, dict):
        return None
    if isinstance(history.get("outputs"), dict):
        return history
    nested = history.get(prompt_id)
    return nested if isinstance(nested, dict) else None


def _wait_for_local_history(config: ComfyMusicConfig, headers: dict[str, str], prompt_id: str) -> dict:
    deadline = time.time() + (config.timeout_ms / 1000)
    while time.time() <= deadline:
        entry = _extract_history_entry(
            _json_request(f"{config.base_url}/history/{prompt_id}", headers=headers, timeout_ms=config.timeout_ms),
            prompt_id,
        )
        if isinstance(entry, dict) and isinstance(entry.get("outputs"), dict) and entry.get("outputs"):
            return entry
        time.sleep(config.poll_interval_ms / 1000)
    raise MusicGenerationError(f"Comfy workflow did not finish within {int(config.timeout_ms / 1000)}s.")


def _wait_for_cloud_history(config: ComfyMusicConfig, headers: dict[str, str], prompt_id: str) -> dict:
    deadline = time.time() + (config.timeout_ms / 1000)
    while time.time() <= deadline:
        status = _json_request(f"{config.base_url}/api/job/{prompt_id}/status", headers=headers, timeout_ms=config.timeout_ms)
        state = str(status.get("status") or "").strip().lower()
        if state == "completed":
            history = _json_request(f"{config.base_url}/api/history_v2/{prompt_id}", headers=headers, timeout_ms=config.timeout_ms)
            entry = _extract_history_entry(history, prompt_id)
            if entry:
                return entry
            raise MusicGenerationError(f"Comfy history response missing outputs for prompt {prompt_id}.")
        if state in {"failed", "cancelled"}:
            raise MusicGenerationError(
                f"Comfy workflow {state}: {status.get('error') or status.get('message') or prompt_id}"
            )
        time.sleep(config.poll_interval_ms / 1000)
    raise MusicGenerationError(f"Comfy workflow did not finish within {int(config.timeout_ms / 1000)}s.")


def _collect_output_assets(config: ComfyMusicConfig, history_entry: dict, headers: dict[str, str]) -> list[_DownloadedAsset]:
    outputs = history_entry.get("outputs")
    if not isinstance(outputs, dict):
        return []
    node_ids = [config.output_node_id] if config.output_node_id else list(outputs.keys())
    assets: list[_DownloadedAsset] = []
    for node_id in node_ids:
        if not node_id:
            continue
        entry = outputs.get(node_id)
        if not isinstance(entry, dict):
            continue
        bucket = entry.get("audio")
        if not isinstance(bucket, list):
            continue
        for item in bucket:
            if not isinstance(item, dict):
                continue
            file_name = str(item.get("filename") or item.get("name") or "").strip()
            if not file_name:
                raise MusicGenerationError("Comfy output entry missing filename.")
            query = urllib_parse.urlencode(
                {
                    "filename": file_name,
                    "subfolder": str(item.get("subfolder") or ""),
                    "type": str(item.get("type") or "output"),
                }
            )
            view_path = "/api/view" if config.mode == "cloud" else "/view"
            data, mime_type = _download_bytes(f"{config.base_url}{view_path}?{query}", headers, config.timeout_ms)
            assets.append(_DownloadedAsset(file_name=file_name, mime_type=mime_type, data=data, node_id=node_id))
    return assets


def generate_comfy_music(*, prompt: str, out_dir: Path, duration_seconds: int, preferred_model: str | None = None) -> GeneratedAudio:
    config = _resolve_config()
    workflow = _load_workflow(config.workflow_path)
    _set_workflow_input(workflow, config.prompt_node_id, config.prompt_input_name, prompt.strip())

    headers = {"Content-Type": "application/json"}
    if config.mode == "cloud":
        if not config.api_key:
            raise MusicGenerationError("Comfy Cloud API key missing.")
        headers["X-API-Key"] = config.api_key

    payload = {"prompt": workflow}
    if config.mode == "cloud" and config.api_key:
        payload["extra_data"] = {"api_key_comfy_org": config.api_key}

    submit_path = "/api/prompt" if config.mode == "cloud" else "/prompt"
    submit_response = _json_request(
        f"{config.base_url}{submit_path}",
        method="POST",
        headers=headers,
        payload=payload,
        timeout_ms=config.timeout_ms,
    )
    prompt_id = str(submit_response.get("prompt_id") or "").strip()
    if not prompt_id:
        raise MusicGenerationError("Comfy workflow submit response missing prompt_id.")

    history_entry = (
        _wait_for_cloud_history(config, headers, prompt_id)
        if config.mode == "cloud"
        else _wait_for_local_history(config, headers, prompt_id)
    )
    assets = _collect_output_assets(config, history_entry, headers)
    if not assets:
        raise MusicGenerationError(f"Comfy workflow {prompt_id} completed without music outputs.")

    first = assets[0]
    out_dir.mkdir(parents=True, exist_ok=True)
    extension = Path(first.file_name).suffix or ".bin"
    raw_path = out_dir / f"generated_audio_raw{extension}"
    final_path = out_dir / "generated_audio.mp3"
    raw_path.write_bytes(first.data)
    trim_audio_to_mp3(raw_path, final_path, duration_seconds)
    return GeneratedAudio(
        provider="comfy",
        model=(preferred_model or DEFAULT_COMFY_MODEL).strip() or DEFAULT_COMFY_MODEL,
        mime_type="audio/mpeg",
        path=final_path,
        prompt_notes=f"prompt_id={prompt_id}; output_nodes={','.join(sorted({asset.node_id for asset in assets}))}",
    )
