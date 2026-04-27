import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from session_to_song.adapters import load_text_file_material
from session_to_song.cli import _handle_video, build_parser
from session_to_song.video import build_video_prompt_pack, scrub_public_text


PRIVATE_SAMPLE = r"""
Drew built a repo-to-trailer flow for ExampleProject.
C:\Users\dbagl\.openclaw\workspace\secret\notes.md contained draft context.
OPENAI_API_KEY=sk-privateprivate1234567890 should never appear.
phone id: Pixel-ABC-1234567890 was mentioned in operational notes.
Next step is making a public-safe prompt pack for launch.
""".strip()


class VideoPromptPackTests(unittest.TestCase):
    def test_video_pack_contains_required_sections_and_scrubs_private_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.txt"
            path.write_text(PRIVATE_SAMPLE, encoding="utf-8")
            material = load_text_file_material(path, project="ExampleProject")
            artifacts = build_video_prompt_pack(material, project="ExampleProject", style="launch", duration_seconds=30)
            pack = artifacts.prompt_pack

        for heading in [
            "## Trailer Concept",
            "## Logline",
            "## 30-Second Script / Voiceover",
            "## Shot List / Storyboard",
            "## Image Keyframe Prompts",
            "## Video Model Prompt",
            "## Safety / Redaction Notes",
        ]:
            self.assertIn(heading, pack)
        self.assertNotIn("Drew", pack)
        self.assertNotIn("C:\\Users", pack)
        self.assertNotIn("dbagl", pack)
        self.assertNotIn("sk-private", pack)
        self.assertNotIn("Pixel-ABC", pack)
        self.assertFalse(artifacts.manifest["render_invoked"])
        self.assertEqual(artifacts.manifest["render_provider"], "none")

    def test_cli_video_alias_writes_text_only_artifacts_without_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sample_path = Path(tmp) / "sample.txt"
            outdir = Path(tmp) / "out"
            sample_path.write_text(PRIVATE_SAMPLE, encoding="utf-8")
            args = argparse.Namespace(
                input_file=str(sample_path),
                outdir=str(outdir),
                input_source="text",
                source="manual",
                session="",
                lookback=36,
                project="ExampleProject",
                style="founder-update",
                duration=30,
                render_provider="none",
            )
            with patch("session_to_song.cli.generate_music_audio", side_effect=AssertionError("render/audio should not run")):
                self.assertEqual(_handle_video(args), 0)

            self.assertTrue((outdir / "trailer_prompt_pack.md").exists())
            self.assertTrue((outdir / "video_model_prompt.txt").exists())
            manifest = json.loads((outdir / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["kind"], "session-to-video")
            self.assertEqual(manifest["style"], "founder-update")
            self.assertFalse(manifest["render_invoked"])

    def test_parser_accepts_video_and_trailer_modes(self) -> None:
        parser = build_parser()
        video_args = parser.parse_args(["video", "input.txt", "--project", "PublicProject"])
        trailer_args = parser.parse_args(["trailer", "input.txt", "--style", "gritty-battle"])
        self.assertEqual(video_args.command, "video")
        self.assertEqual(video_args.project, "PublicProject")
        self.assertEqual(trailer_args.command, "trailer")
        self.assertEqual(trailer_args.style, "gritty-battle")

    def test_scrub_public_text_removes_secret_shapes(self) -> None:
        scrubbed = scrub_public_text(r"token=abc123456789 C:\Users\dbagl\file.env person@example.com")
        self.assertNotIn("abc123456789", scrubbed)
        self.assertNotIn("C:\\Users", scrubbed)
        self.assertNotIn("person@example.com", scrubbed)


if __name__ == "__main__":
    unittest.main()
