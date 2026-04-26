from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


class PlaybackError(RuntimeError):
    pass


@dataclass
class PlaybackResult:
    ok: bool
    backend: str
    path: str
    pid: int | None = None
    blocked: bool = False
    message: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _require_file(path: str | Path) -> Path:
    target = Path(path).expanduser().resolve()
    if not target.exists() or not target.is_file():
        raise PlaybackError(f"Audio file not found: {target}")
    return target


def _powershell_exe() -> str | None:
    return shutil.which("powershell.exe") or shutil.which("powershell")


def _ffplay_exe() -> str | None:
    return shutil.which("ffplay")


def _vlc_exe() -> str | None:
    candidates = [
        shutil.which("vlc"),
        shutil.which("vlc.exe"),
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None


def resolve_backend(backend: str = "auto") -> str:
    requested = (backend or "auto").lower()
    if requested != "auto":
        return requested
    if sys.platform.startswith("win") and _powershell_exe():
        return "powershell"
    if _ffplay_exe():
        return "ffplay"
    if _vlc_exe():
        return "vlc"
    return "open"


def _powershell_script(path: Path, volume: int, timeout_seconds: int) -> str:
    safe_path = str(path).replace("'", "''")
    vol = max(0.0, min(float(volume) / 100.0, 1.0))
    timeout_ms = max(1, int(timeout_seconds)) * 1000
    return f"""
Add-Type -AssemblyName PresentationCore
$ErrorActionPreference = 'Stop'
$player = New-Object System.Windows.Media.MediaPlayer
$done = New-Object System.Threading.ManualResetEvent($false)
Register-ObjectEvent -InputObject $player -EventName MediaEnded -Action {{ $done.Set() | Out-Null }} | Out-Null
Register-ObjectEvent -InputObject $player -EventName MediaFailed -Action {{ $done.Set() | Out-Null }} | Out-Null
$player.Open([System.Uri]::new('{safe_path}'))
$player.Volume = {vol}
Start-Sleep -Milliseconds 300
$player.Play()
$done.WaitOne({timeout_ms}) | Out-Null
$player.Stop()
$player.Close()
""".strip()


def _run_or_spawn(command: list[str], *, block: bool, timeout_seconds: int) -> PlaybackResult:
    if block:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds + 5)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "playback failed").strip()
            raise PlaybackError(detail)
        return PlaybackResult(ok=True, backend="", path="", blocked=True, message="played")
    proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return PlaybackResult(ok=True, backend="", path="", pid=proc.pid, blocked=False, message="playback started")


def play_audio(
    path: str | Path,
    *,
    backend: str = "auto",
    volume: int = 100,
    block: bool = True,
    timeout_seconds: int = 600,
) -> PlaybackResult:
    target = _require_file(path)
    selected = resolve_backend(backend)
    volume = max(0, min(int(volume), 100))
    timeout_seconds = max(1, int(timeout_seconds))

    if selected == "powershell":
        exe = _powershell_exe()
        if not exe:
            raise PlaybackError("powershell.exe is not available for local playback")
        command = [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _powershell_script(target, volume, timeout_seconds)]
        result = _run_or_spawn(command, block=block, timeout_seconds=timeout_seconds)
    elif selected == "ffplay":
        exe = _ffplay_exe()
        if not exe:
            raise PlaybackError("ffplay is not available for local playback")
        command = [exe, "-nodisp", "-autoexit", "-loglevel", "error", "-volume", str(volume), str(target)]
        result = _run_or_spawn(command, block=block, timeout_seconds=timeout_seconds)
    elif selected == "vlc":
        exe = _vlc_exe()
        if not exe:
            raise PlaybackError("VLC is not available for local playback")
        command = [exe, "--intf", "dummy", "--play-and-exit", str(target)]
        result = _run_or_spawn(command, block=block, timeout_seconds=timeout_seconds)
    elif selected == "open":
        if not sys.platform.startswith("win"):
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            command = [opener, str(target)]
            result = _run_or_spawn(command, block=False, timeout_seconds=timeout_seconds)
        else:
            os.startfile(str(target))  # type: ignore[attr-defined]
            result = PlaybackResult(ok=True, backend="open", path=str(target), blocked=False, message="opened in default player")
    else:
        raise PlaybackError(f"Unsupported playback backend: {selected}")

    result.backend = selected
    result.path = str(target)
    if not result.message:
        result.message = "playback started" if not block else "played"
    return result
