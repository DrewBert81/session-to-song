from __future__ import annotations

import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path


class AlarmSlotError(RuntimeError):
    pass


SLOT_FILENAMES = {
    "morning": "S2S-morning.mp3",
    "break": "S2S-break.mp3",
    "reminder": "S2S-reminder.mp3",
    "celebrate": "S2S-celebrate.mp3",
}


@dataclass
class AlarmSlotResult:
    ok: bool
    slot: str
    filename: str
    source_path: str
    target_path: str
    bytes_written: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def slot_filename(slot: str) -> str:
    key = (slot or "morning").strip().lower()
    return SLOT_FILENAMES.get(key, f"S2S-{key}.mp3")


def default_alarm_slot_dirs() -> list[Path]:
    configured = os.getenv("SESSION_TO_SONG_ALARM_SLOT_DIR") or os.getenv("S2S_ALARM_SLOT_DIR")
    dirs: list[Path] = []
    if configured:
        dirs.append(Path(configured))
    userprofile = Path(os.getenv("USERPROFILE", str(Path.home())))
    dirs.extend([
        userprofile / "My Drive" / "sessiontosong" / "alarms",
        userprofile / "Google Drive" / "My Drive" / "sessiontosong" / "alarms",
        userprofile / "Google Drive" / "sessiontosong" / "alarms",
        userprofile / "Drive" / "sessiontosong" / "alarms",
    ])
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        dirs.append(Path(f"{letter}:\\My Drive\\sessiontosong\\alarms"))
    seen: set[str] = set()
    unique: list[Path] = []
    for directory in dirs:
        key = str(directory)
        if key in seen:
            continue
        seen.add(key)
        unique.append(directory)
    return unique


def resolve_alarm_slot_dir(target_dir: str | Path | None = None, *, create: bool = True) -> Path:
    if target_dir:
        directory = Path(target_dir).expanduser()
        if create:
            directory.mkdir(parents=True, exist_ok=True)
        if not directory.exists() or not directory.is_dir():
            raise AlarmSlotError(f"Alarm slot directory is not available: {directory}")
        return directory.resolve()

    for directory in default_alarm_slot_dirs():
        if directory.exists() and directory.is_dir():
            return directory.resolve()

    configured = os.getenv("SESSION_TO_SONG_ALARM_SLOT_DIR") or os.getenv("S2S_ALARM_SLOT_DIR")
    if configured and create:
        directory = Path(configured).expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        return directory.resolve()

    raise AlarmSlotError(
        "No alarm slot directory found. Pass --target-dir or set SESSION_TO_SONG_ALARM_SLOT_DIR "
        "to your Drive folder, e.g. My Drive\\sessiontosong\\alarms."
    )


def publish_alarm_slot(
    source_path: str | Path,
    *,
    slot: str = "morning",
    target_dir: str | Path | None = None,
) -> AlarmSlotResult:
    source = Path(source_path).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise AlarmSlotError(f"Source audio file not found: {source}")
    directory = resolve_alarm_slot_dir(target_dir)
    filename = slot_filename(slot)
    target = directory / filename
    tmp_target = directory / f".{filename}.tmp"
    shutil.copyfile(source, tmp_target)
    tmp_target.replace(target)
    return AlarmSlotResult(
        ok=True,
        slot=(slot or "morning"),
        filename=filename,
        source_path=str(source),
        target_path=str(target.resolve()),
        bytes_written=target.stat().st_size,
    )
