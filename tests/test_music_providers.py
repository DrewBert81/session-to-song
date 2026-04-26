import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from session_to_song.providers.comfy_music import generate_comfy_music
from session_to_song.providers.minimax_music import generate_minimax_music


class _FakeResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None):
        self._body = body
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class MusicProviderRuntimeTests(unittest.TestCase):
    def test_minimax_runtime_handles_generation_and_download(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout=0):
            if hasattr(request, "full_url") and str(request.full_url).endswith("/v1/music_generation"):
                captured["auth"] = request.headers.get("Authorization")
                captured["payload"] = json.loads(request.data.decode("utf-8"))
                return _FakeResponse(
                    json.dumps(
                        {
                            "base_resp": {"status_code": 0},
                            "audio_url": "https://cdn.example.com/track.mp3",
                            "lyrics": "Hook line",
                            "task_id": "job-123",
                        }
                    ).encode("utf-8")
                )
            return _FakeResponse(b"FAKE-MP3", {"Content-Type": "audio/mpeg"})

        def fake_trim(input_path: Path, output_path: Path, duration_seconds: int) -> Path:
            shutil.copyfile(input_path, output_path)
            return output_path

        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"MINIMAX_API_KEY": "secret"}, clear=True), patch(
            "session_to_song.providers.minimax_music.urllib_request.urlopen", side_effect=fake_urlopen
        ), patch("session_to_song.providers.minimax_music.trim_audio_to_mp3", side_effect=fake_trim):
            generated = generate_minimax_music(
                prompt="Wake-up anthem",
                out_dir=Path(tmp),
                duration_seconds=30,
                preferred_model="minimax/music-2.5+",
            )
            self.assertEqual(generated.provider, "minimax")
            self.assertEqual(generated.model, "music-2.5+")
            self.assertTrue(generated.path.exists())
            self.assertEqual(captured["auth"], "Bearer secret")
            self.assertEqual(captured["payload"]["model"], "music-2.5+")
            self.assertIn("Target duration: about 30 seconds.", captured["payload"]["prompt"])
            self.assertIn("task_id=job-123", generated.prompt_notes or "")
            self.assertIn("Hook line", generated.prompt_notes or "")

    def test_comfy_local_runtime_submits_workflow_and_downloads_audio(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout=0):
            url = request.full_url if hasattr(request, "full_url") else request
            if str(url).endswith("/prompt"):
                payload = json.loads(request.data.decode("utf-8"))
                captured["payload"] = payload
                return _FakeResponse(json.dumps({"prompt_id": "prompt-1"}).encode("utf-8"))
            if str(url).endswith("/history/prompt-1"):
                return _FakeResponse(
                    json.dumps(
                        {
                            "prompt-1": {
                                "outputs": {
                                    "99": {
                                        "audio": [
                                            {"filename": "track.wav", "subfolder": "", "type": "output"}
                                        ]
                                    }
                                }
                            }
                        }
                    ).encode("utf-8")
                )
            if "/view?" in str(url):
                return _FakeResponse(b"RIFF....WAVE", {"Content-Type": "audio/wav"})
            raise AssertionError(f"Unexpected URL: {url}")

        def fake_trim(input_path: Path, output_path: Path, duration_seconds: int) -> Path:
            shutil.copyfile(input_path, output_path)
            return output_path

        with tempfile.TemporaryDirectory() as tmp:
            workflow_path = Path(tmp) / "music_workflow.json"
            workflow_path.write_text(json.dumps({"12": {"inputs": {"text": "old value"}}}), encoding="utf-8")
            with patch.dict(
                "os.environ",
                {
                    "COMFY_MODE": "local",
                    "COMFY_MUSIC_WORKFLOW_PATH": str(workflow_path),
                    "COMFY_MUSIC_PROMPT_NODE_ID": "12",
                    "COMFY_MUSIC_OUTPUT_NODE_ID": "99",
                },
                clear=True,
            ), patch("session_to_song.providers.comfy_music.urllib_request.urlopen", side_effect=fake_urlopen), patch(
                "session_to_song.providers.comfy_music.trim_audio_to_mp3", side_effect=fake_trim
            ), patch("session_to_song.providers.comfy_music.time.sleep", return_value=None):
                generated = generate_comfy_music(
                    prompt="Ship the next milestone",
                    out_dir=Path(tmp),
                    duration_seconds=45,
                    preferred_model="workflow",
                )
                prompt_workflow = captured["payload"]["prompt"]
                self.assertEqual(prompt_workflow["12"]["inputs"]["text"], "Ship the next milestone")
                self.assertEqual(generated.provider, "comfy")
                self.assertEqual(generated.model, "workflow")
                self.assertTrue(generated.path.exists())
                self.assertIn("prompt_id=prompt-1", generated.prompt_notes or "")


if __name__ == "__main__":
    unittest.main()
