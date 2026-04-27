import json
import tempfile
import unittest
from pathlib import Path

from session_to_song.domain import SongArtifacts
from session_to_song.openclaw_memory import append_audio_to_openclaw_memory, export_artifacts_to_openclaw_memory


class OpenClawMemoryExportTests(unittest.TestCase):
    def _artifacts(self) -> SongArtifacts:
        return SongArtifacts(
            pulse="Pulse line",
            lyrics="Lyrics line",
            music_prompt="Music prompt line",
            manifest={
                "use": "celebrate",
                "genre": "rock",
                "focus": "what shipped",
                "duration_seconds": 30,
                "project": "ExampleProject",
            },
        )

    def _files(self, root: Path) -> dict[str, Path]:
        files = {
            "pulse": root / "pulse.txt",
            "lyrics": root / "lyrics.txt",
            "music_prompt": root / "music_prompt.txt",
            "manifest": root / "run_manifest.json",
        }
        for key, path in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"key": key}) if key == "manifest" else key, encoding="utf-8")
        return files

    def test_disabled_export_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            result = export_artifacts_to_openclaw_memory(self._artifacts(), self._files(Path(tmp) / "out"), enabled=False, workspace=workspace)
            self.assertIsNone(result)
            self.assertFalse((workspace / "memory").exists())

    def test_enabled_export_writes_text_artifacts_to_custom_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            result = export_artifacts_to_openclaw_memory(self._artifacts(), self._files(Path(tmp) / "out"), enabled=True, workspace=workspace)
            self.assertIsNotNone(result)
            assert result is not None
            self.assertTrue(str(result).startswith(str(workspace)))
            content = result.read_text(encoding="utf-8")
            self.assertIn("Session-to-song artifact", content)
            self.assertIn("Pulse line", content)
            self.assertIn("Lyrics line", content)
            self.assertIn("Music prompt line", content)
            self.assertIn("lyrics.txt", content)

    def test_export_can_include_generated_audio_and_alarm_slot_pointers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audio = type("Audio", (), {
                "path": Path(tmp) / "generated_audio.mp3",
                "provider": "google",
                "model": "models/lyria-3-pro-preview",
                "mime_type": "audio/mpeg",
                "prompt_notes": None,
            })()
            slot = {"slot": "morning", "filename": "S2S-morning.mp3", "target_path": str(Path(tmp) / "S2S-morning.mp3"), "bytes_written": 123}
            result = export_artifacts_to_openclaw_memory(self._artifacts(), self._files(Path(tmp) / "out"), enabled=True, workspace=Path(tmp) / "workspace", audio=audio, alarm_slot=slot)
            assert result is not None
            content = result.read_text(encoding="utf-8")
            self.assertIn("### Audio output", content)
            self.assertIn("generated_audio.mp3", content)
            self.assertIn("provider: google", content)
            self.assertIn("models/lyria-3-pro-preview", content)
            self.assertIn("S2S-morning.mp3", content)

    def test_audio_can_be_appended_after_text_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = export_artifacts_to_openclaw_memory(self._artifacts(), self._files(Path(tmp) / "out"), enabled=True, workspace=Path(tmp) / "workspace")
            audio = {"path": str(Path(tmp) / "generated_audio.mp3"), "provider": "minimax", "model": "music-2.5+", "mime_type": "audio/mpeg"}
            appended = append_audio_to_openclaw_memory(result, audio=audio)
            self.assertEqual(appended, result)
            content = result.read_text(encoding="utf-8")  # type: ignore[union-attr]
            self.assertIn("generated_audio.mp3", content)
            self.assertIn("provider: minimax", content)


if __name__ == "__main__":
    unittest.main()
