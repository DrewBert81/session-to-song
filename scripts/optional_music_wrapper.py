from __future__ import annotations

from pathlib import Path
import subprocess


def run_music_command(command_template: str, prompt_file: Path) -> int:
    command = command_template.format(prompt_file=str(prompt_file))
    print(f"Running music command: {command}")
    completed = subprocess.run(command, shell=True, check=False)
    if completed.returncode != 0:
        print("Music command failed, but text artifacts are still usable.")
    return completed.returncode
