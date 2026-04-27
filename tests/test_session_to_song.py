import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from session_to_song.adapters import load_hermes_material, load_text_file_material
from session_to_song.alarm_slots import publish_alarm_slot, slot_filename
from session_to_song.cli import _handle_doctor
from session_to_song.config_loader import load_config_data, load_user_config, resolve_genre, resolve_run_request, resolve_style, save_user_config_data
from session_to_song.connectors.openclaw_sessions import SourceRequest, fetch_session_text, resolve_best_session_source
from session_to_song.domain import RunRequest
from session_to_song.providers import detect_provider_status
from session_to_song.providers.google_music import MusicGenerationError
from session_to_song.providers.music_runtime import generate_music_audio, music_generation_available
from session_to_song.pipeline import build_from_material
from session_to_song.pipeline.orchestrator import sanitize_lyrics_for_vocals
from session_to_song.pipeline.session_material import extract_material_from_session, load_recent_dream_context, load_recent_memory_context
from session_to_song.openclaw_memory import export_artifacts_to_openclaw_memory
from session_to_song.playback import play_audio, resolve_backend
from session_to_song.project_filter import filter_text_for_project
from session_to_song.storage import write_artifacts
from session_to_song import web_app as web_app_module
from session_to_song.web_app import app as web_app

SAMPLE = """
Built the daily pulse draft.
Fixed the naming for the wake-up track.
Blocked on polishing the final web flow.
Next step is validating the redesign end to end.
""".strip()


class SessionToSongTests(unittest.TestCase):
    def _call_wsgi(self, path: str, method: str = "GET", body: bytes = b"", headers: dict[str, str] | None = None) -> tuple[str, dict[str, str], dict]:
        captured: dict[str, object] = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "QUERY_STRING": "",
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": io.BytesIO(body),
        }
        for key, value in (headers or {}).items():
            environ[key] = value
        if "?" in path:
            clean_path, query = path.split("?", 1)
            environ["PATH_INFO"] = clean_path
            environ["QUERY_STRING"] = query
        payload = b"".join(web_app(environ, start_response))
        return str(captured.get("status", "")), captured.get("headers", {}), json.loads(payload.decode("utf-8"))

    def test_web_app_blocks_static_path_traversal(self) -> None:
        status, _, payload = self._call_wsgi("/../README.md")
        self.assertTrue(status.startswith("404"))
        self.assertEqual(payload["error"], "not_found")

    def test_text_adapter_extracts_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.txt"
            path.write_text(SAMPLE, encoding="utf-8")
            material = load_text_file_material(path, project="Demo")
            self.assertEqual(material.source, "text")
            self.assertEqual(material.project, "Demo")
            self.assertTrue(material.wins)
            self.assertTrue(material.blockers)
            self.assertTrue(material.next_actions)

    def test_text_adapter_filters_to_project_when_project_lines_match(self) -> None:
        sample = """
ExampleProject built the alarm source filter.
OtherProject fixed an unrelated dashboard issue.
Next ExampleProject step is validating the generated alarm artifact.
""".strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.txt"
            path.write_text(sample, encoding="utf-8")
            material = load_text_file_material(path, project="ExampleProject")
            self.assertIn("ExampleProject built", material.raw_text)
            self.assertIn("Next ExampleProject", material.raw_text)
            self.assertNotIn("OtherProject", material.raw_text)
            self.assertTrue(material.metadata["project_filter_matched"])

    def test_hermes_adapter_extracts_sections_and_builds_artifacts(self) -> None:
        sample_path = ROOT / "content" / "examples" / "hermes_session_sample.txt"
        material = load_hermes_material(sample_path, project="ExampleProject")
        self.assertEqual(material.source, "hermes")
        self.assertIn("Hermes session", material.title)
        self.assertIn("onboarding flow", material.raw_text)
        self.assertTrue(material.wins)
        self.assertTrue(material.blockers)
        self.assertTrue(material.next_actions)
        user_config = load_user_config()
        user_config.llm_provider = "byok"
        request = resolve_run_request(user_config, RunRequest(use="celebrate", genre="rock", focus="what shipped"))
        with patch.dict(os.environ, {}, clear=True):
            artifacts = build_from_material(material, user_config, request)
        self.assertIn("[Celebrate Track", artifacts.lyrics)
        self.assertIn("ExampleProject", artifacts.manifest.get("project") or "")
        self.assertIn("celebrate track", artifacts.music_prompt)

    def test_cli_generate_supports_hermes_input_source(self) -> None:
        from session_to_song.cli import _handle_generate
        with tempfile.TemporaryDirectory() as tmp:
            sample_path = ROOT / "content" / "examples" / "hermes_session_sample.txt"
            args = argparse.Namespace(
                config="",
                outdir=str(Path(tmp) / "out"),
                use="celebrate",
                genre="rock",
                focus="what shipped",
                delivery="save",
                duration=30,
                input_source="hermes",
                source="manual",
                session="",
                lookback=36,
                project="ExampleProject",
                mode="",
                style="",
                question="",
                input_file=str(sample_path),
            )
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(_handle_generate(args), 0)
            lyrics = (Path(tmp) / "out" / "lyrics.txt").read_text(encoding="utf-8")
            self.assertIn("[Celebrate Track", lyrics)

    def test_pipeline_builds_reminder_use(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.txt"
            path.write_text(SAMPLE, encoding="utf-8")
            material = load_text_file_material(path)
            user_config = load_user_config()
            user_config.llm_provider = "byok"
            request = resolve_run_request(user_config, RunRequest(use="reminder", focus="where the project stands and where it is going"))
            with patch.dict(os.environ, {}, clear=True):
                artifacts = build_from_material(material, user_config, request)
            self.assertIn("[Reminder Track", artifacts.lyrics)
            self.assertIn("State check", artifacts.lyrics)
            self.assertIn("Current state", artifacts.pulse)
            self.assertNotIn("what shipped", artifacts.pulse.lower())
            self.assertEqual(artifacts.manifest["genre"], "rock")
            self.assertEqual(artifacts.manifest["focus"], "where the project stands and where it is going")
            self.assertEqual(artifacts.manifest["duration_seconds"], 45)

    def test_pipeline_builds_celebrate_use(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.txt"
            path.write_text(SAMPLE, encoding="utf-8")
            material = load_text_file_material(path, project="SessionToSong")
            user_config = load_user_config()
            user_config.llm_provider = "byok"
            request = resolve_run_request(user_config, RunRequest(use="celebrate", focus="what shipped and why it matters", duration_seconds=30))
            with patch.dict(os.environ, {}, clear=True):
                artifacts = build_from_material(material, user_config, request)
            self.assertIn("[Celebrate Track", artifacts.lyrics)
            self.assertIn("~30s", artifacts.lyrics)
            self.assertEqual(artifacts.manifest["genre"], "rap")
            self.assertEqual(artifacts.manifest["duration_seconds"], 30)
            self.assertIn("Win:", artifacts.pulse)
            self.assertIn("Replay cue", artifacts.pulse)
            self.assertIn("30-second celebrate track", artifacts.music_prompt)
            self.assertIn("do not deliver a full-length song", artifacts.music_prompt)

    def test_use_changes_narrative_theme(self) -> None:
        material = load_text_file_material(Path(__file__).resolve().parents[1] / "content" / "input" / "sample_day.txt")
        user_config = load_user_config()
        user_config.llm_provider = "byok"
        with patch.dict(os.environ, {}, clear=True):
            alarm = build_from_material(material, user_config, resolve_run_request(user_config, RunRequest(use="alarm")))
            reminder = build_from_material(material, user_config, resolve_run_request(user_config, RunRequest(use="reminder")))
            celebrate = build_from_material(material, user_config, resolve_run_request(user_config, RunRequest(use="celebrate")))
        self.assertIn("Wake cue", alarm.pulse)
        self.assertIn("Reminder cue", reminder.pulse)
        self.assertIn("Replay cue", celebrate.pulse)
        self.assertNotEqual(alarm.pulse, reminder.pulse)
        self.assertNotEqual(reminder.pulse, celebrate.pulse)

    def test_template_path_strips_dev_jargon_from_lyrics(self) -> None:
        sample = """
Built the setup flow for session-to-song.
Added init, config show, genre set, test, and generate.
Need to keep validating the new flow and tightening edge cases.
""".strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.txt"
            path.write_text(sample, encoding="utf-8")
            material = load_text_file_material(path)
            user_config = load_user_config()
            user_config.llm_provider = "byok"
            request = resolve_run_request(user_config, RunRequest(use="alarm", genre="rap", focus="what did we accomplish yesterday and what matters today"))
            with patch.dict(os.environ, {}, clear=True):
                artifacts = build_from_material(material, user_config, request)
            lowered = artifacts.lyrics.lower()
            self.assertNotIn("config show", lowered)
            self.assertNotIn("genre set", lowered)
            self.assertNotIn("edge cases", lowered)

    def test_pipeline_strips_file_paths_from_alarm_lyrics(self) -> None:
        sample = """
src/components/sidebar.tsx: renamed chat framing toward rooms / ai boardroom and added one-click room templates.
release-checklist.md marked startup smoke and audit export smoke checked.
Next move is making the morning alarm play through the phone slot.
""".strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.txt"
            path.write_text(sample, encoding="utf-8")
            material = load_text_file_material(path)
            user_config = load_user_config()
            user_config.llm_provider = "byok"
            request = resolve_run_request(user_config, RunRequest(use="alarm", genre="rap"))
            with patch.dict(os.environ, {}, clear=True):
                artifacts = build_from_material(material, user_config, request)
            lowered = artifacts.lyrics.lower()
            self.assertNotIn("src/components", lowered)
            self.assertNotIn("sidebar.tsx", lowered)
            self.assertNotIn("release-checklist.md", lowered)
            self.assertIn("rooms", lowered)

    def test_vocal_sanitizer_removes_tokens_codes_and_metadata(self) -> None:
        lyrics = """
[Alarm Track | genre=rap | ~60s]
Wake back in: EhmeMVP OAuth connector, Nango flow, token refresh, GPT-5.4.
First move: ReEmber slice #1/#2, runtime card, PID 1234 and SHA abc1234.
[Reference Pulse]
• token token API junk
""".strip()
        cleaned = sanitize_lyrics_for_vocals(lyrics).lower()
        for banned in ["token", "oauth", "nango", "gpt", "pid", "sha", "#1", "reference pulse", "genre=rap"]:
            self.assertNotIn(banned, cleaned)
        self.assertIn("secure connection flow", cleaned)
        self.assertIn("status card", cleaned)

    def test_genre_resolution_honors_project_then_use_then_default(self) -> None:
        user_config = load_user_config()
        user_config.genre_by_project["HeavyProject"] = "folk"
        self.assertEqual(resolve_genre(user_config, RunRequest(use="reminder", project="HeavyProject")), "folk")
        self.assertEqual(resolve_style(user_config, RunRequest(use="reminder")), "rock")
        self.assertEqual(resolve_genre(user_config, RunRequest(use="celebrate")), "rap")
        self.assertEqual(resolve_genre(user_config, RunRequest(use="alarm", genre="pop")), "pop")

    def test_storage_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.txt"
            path.write_text(SAMPLE, encoding="utf-8")
            material = load_text_file_material(path)
            user_config = load_user_config()
            user_config.llm_provider = "byok"
            request = resolve_run_request(user_config, RunRequest(use="alarm"))
            with patch.dict(os.environ, {}, clear=True):
                artifacts = build_from_material(material, user_config, request)
            outdir = Path(tmp) / "out"
            files = write_artifacts(outdir, artifacts)
            manifest = json.loads(files["manifest"].read_text(encoding="utf-8"))
            self.assertEqual(manifest["use"], "alarm")
            self.assertEqual(manifest["genre"], "rap")
            self.assertIn("llm", manifest)
            self.assertIn("music", manifest)

    def test_openclaw_memory_export_appends_artifacts_to_daily_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.txt"
            path.write_text(SAMPLE, encoding="utf-8")
            material = load_text_file_material(path)
            user_config = load_user_config()
            user_config.llm_provider = "byok"
            request = resolve_run_request(user_config, RunRequest(use="celebrate", focus="what shipped"))
            with patch.dict(os.environ, {}, clear=True):
                artifacts = build_from_material(material, user_config, request)
            outdir = Path(tmp) / "out"
            files = write_artifacts(outdir, artifacts)
            memory_file = export_artifacts_to_openclaw_memory(artifacts, files, enabled=True, workspace=Path(tmp) / "openclaw-workspace")
            self.assertIsNotNone(memory_file)
            assert memory_file is not None
            content = memory_file.read_text(encoding="utf-8")
            self.assertIn("Session-to-song artifact", content)
            self.assertIn("### Lyrics", content)
            self.assertIn("### Music prompt", content)
            self.assertIn("lyrics.txt", content)

    def test_user_config_can_be_saved_and_reloaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "user.json"
            data = load_config_data()
            data["defaults"]["genre"] = "heavy_metal"
            data["preferences"]["genre_by_project"]["ProjectX"] = "folk"
            data["defaults"]["duration_seconds"] = 60
            save_user_config_data(data, config_path)
            config = load_user_config(config_path)
            self.assertEqual(config.default_genre, "heavy_metal")
            self.assertEqual(config.genre_by_project["ProjectX"], "folk")
            self.assertEqual(config.duration_seconds, 60)

    def test_provider_resolution_uses_explicit_provider_when_configured(self) -> None:
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-openrouter", "OPENAI_API_KEY": "test-openai"}, clear=True):
            status = detect_provider_status(
                llm_provider="openai",
                llm_model="gpt-4.1-mini",
                music_provider="auto",
                music_model="",
            )
        self.assertEqual(status.llm.provider, "openai")
        self.assertEqual(status.llm.model, "gpt-4.1-mini")
        self.assertEqual(status.llm.source, "explicit")
        self.assertTrue(status.llm.available)

    def test_provider_resolution_falls_back_from_env_when_auto(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai", "MINIMAX_API_KEY": "test-minimax"}, clear=True):
            status = detect_provider_status(
                llm_provider="auto",
                llm_model="",
                music_provider="auto",
                music_model="",
            )
        self.assertEqual(status.llm.provider, "openai")
        self.assertEqual(status.llm.model, "gpt-4o-mini")
        self.assertEqual(status.llm.source, "env")
        self.assertEqual(status.music.provider, "minimax")
        self.assertEqual(status.music.model, "minimax/music-2.5+")
        self.assertEqual(status.music.source, "env")
        self.assertTrue(status.music.runtime_supported)
        self.assertEqual(status.music.message, "")

    def test_provider_resolution_falls_back_to_template_without_llm_keys(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            status = detect_provider_status(
                llm_provider="auto",
                llm_model="",
                music_provider="auto",
                music_model="",
            )
        self.assertEqual(status.llm.provider, "template")
        self.assertEqual(status.llm.model, "builtin-template")
        self.assertEqual(status.music.provider, "unconfigured")
        self.assertIn("Template generation will be used", status.llm.message)

    def test_provider_resolution_reads_local_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("OPENAI_API_KEY=from-dotenv\n", encoding="utf-8")
            current = Path.cwd()
            os.chdir(tmp)
            try:
                with patch.dict(os.environ, {}, clear=True):
                    status = detect_provider_status(
                        llm_provider="auto",
                        llm_model="",
                        music_provider="auto",
                        music_model="",
                    )
            finally:
                os.chdir(current)
        self.assertEqual(status.llm.provider, "openai")
        self.assertEqual(status.llm.source, "env")

    def test_doctor_reports_missing_env_help_for_explicit_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "user.json"
            save_user_config_data(
                {
                    "providers": {
                        "llm": {"provider": "openrouter", "model": "anthropic/claude-3.7-sonnet"},
                        "music": {"provider": "minimax", "model": "minimax/music-2.5+"},
                    },
                    "defaults": load_config_data()["defaults"],
                    "preferences": load_config_data()["preferences"],
                },
                config_path,
            )
            buffer = io.StringIO()
            with patch.dict(os.environ, {}, clear=True), redirect_stdout(buffer):
                exit_code = _handle_doctor(argparse.Namespace(config=str(config_path)))
        output = buffer.getvalue()
        self.assertEqual(exit_code, 1)
        self.assertIn("Resolved LLM: openrouter [anthropic/claude-3.7-sonnet] via explicit", output)
        self.assertIn("Configured llm provider 'openrouter' is missing credentials", output)
        self.assertIn("Copy .env.example to .env", output)

    def test_doctor_passes_for_explicit_minimax_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "user.json"
            save_user_config_data(
                {
                    "providers": {
                        "llm": {"provider": "auto", "model": ""},
                        "music": {"provider": "minimax", "model": "minimax/music-2.5+"},
                    },
                    "defaults": load_config_data()["defaults"],
                    "preferences": load_config_data()["preferences"],
                },
                config_path,
            )
            buffer = io.StringIO()
            with patch.dict(os.environ, {"MINIMAX_API_KEY": "test-minimax"}, clear=True), patch("session_to_song.cli.ffmpeg_available", return_value=True), redirect_stdout(buffer):
                exit_code = _handle_doctor(argparse.Namespace(config=str(config_path)))
        output = buffer.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("Setup status:", output)
        self.assertIn("Live audio: ready via minimax", output)

    def test_music_runtime_dispatches_minimax_provider(self) -> None:
        user_config = load_user_config()
        user_config.music_provider = "minimax"
        user_config.music_model = "minimax/music-2.5+"
        fake_audio = Path("C:/tmp/fake.mp3")
        with patch("session_to_song.providers.music_runtime.generate_minimax_music") as mock_generate, patch.dict(os.environ, {"MINIMAX_API_KEY": "test-minimax"}, clear=True):
            mock_generate.return_value = type("Audio", (), {"path": fake_audio, "mime_type": "audio/mpeg", "provider": "minimax", "model": "music-2.5+", "prompt_notes": None})()
            generated = generate_music_audio(
                prompt="Short hype track",
                out_dir=Path("content/output/test-run"),
                duration_seconds=30,
                user_config=user_config,
            )
        self.assertEqual(generated.provider, "minimax")
        mock_generate.assert_called_once()

    def test_music_runtime_reports_google_as_available(self) -> None:
        user_config = load_user_config()
        user_config.music_provider = "auto"
        user_config.music_model = ""
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-google"}, clear=True):
            self.assertTrue(music_generation_available(user_config))

    def test_web_bootstrap_enables_audio_when_auto_resolves_minimax(self) -> None:
        with patch.dict(os.environ, {"MINIMAX_API_KEY": "test-minimax"}, clear=True):
            status, _, payload = self._call_wsgi("/api/bootstrap")
        self.assertEqual(status, "200 OK")
        self.assertTrue(payload["audio_generation"]["available"])
        self.assertEqual(payload["audio_generation"]["provider"], "minimax")

    def test_web_bootstrap_lists_unsupported_llm_options(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-anthropic"}, clear=True):
            status, _, payload = self._call_wsgi("/api/bootstrap")
        self.assertEqual(status, "200 OK")
        providers = {row["provider"]: row for row in payload["llm_providers"]}
        self.assertIn("anthropic", providers)
        self.assertTrue(providers["anthropic"]["available"])
        self.assertFalse(providers["anthropic"]["runtime_supported"])

    def test_web_bootstrap_lists_quality_and_fast_llm_model_presets(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai", "GOOGLE_API_KEY": "test-google"}, clear=True):
            status, _, payload = self._call_wsgi("/api/bootstrap")
        self.assertEqual(status, "200 OK")
        models = {(row["provider"], row["model"]): row for row in payload["llm_models"]}
        self.assertIn(("openai", "gpt-5.5"), models)
        self.assertIn(("openai", "gpt-4o-mini"), models)
        self.assertIn(("google", "gemini-3.1-pro"), models)
        self.assertIn(("google", "gemini-2.5-flash"), models)
        self.assertEqual(models[("openai", "gpt-5.5")]["profile"], "quality/latest")
        self.assertEqual(models[("google", "gemini-2.5-flash")]["profile"], "fast/cheap")

    def test_web_bootstrap_includes_live_discovered_llm_models(self) -> None:
        discovered = [{"provider": "openai", "model": "gpt-6-preview", "label": "OpenAI gpt-6-preview", "profile": "detected"}]
        with patch.dict(os.environ, {"OPENAI_API_KEY": "real-looking-key"}, clear=True), patch("session_to_song.web_app._discover_provider_models", return_value=discovered):
            status, _, payload = self._call_wsgi("/api/bootstrap")
        self.assertEqual(status, "200 OK")
        models = {(row["provider"], row["model"]): row for row in payload["llm_models"]}
        self.assertIn(("openai", "gpt-6-preview"), models)
        self.assertEqual(models[("openai", "gpt-6-preview")]["profile"], "detected")

    def test_celebrate_push_skips_audio_by_default(self) -> None:
        from session_to_song.cli import _handle_celebrate_push
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(
                config="",
                outdir=str(Path(tmp) / "out"),
                project="session-to-song",
                genre="rock",
                duration=30,
                focus="celebrate the push",
                sound_reference="short anthem",
                summary="Successful push",
                audio=False,
                play=False,
                backend="auto",
                no_block=True,
                llm_provider="byok",
                llm_model="",
                music_provider="",
                music_model="",
            )
            with patch("session_to_song.cli.generate_music_audio", side_effect=AssertionError("audio should not run")), patch("session_to_song.cli.export_artifacts_to_openclaw_memory", return_value=None):
                self.assertEqual(_handle_celebrate_push(args), 0)
            self.assertTrue((Path(tmp) / "out" / "lyrics.txt").exists())

    def test_celebrate_push_play_requires_audio(self) -> None:
        from session_to_song.cli import _handle_celebrate_push
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(
                config="",
                outdir=str(Path(tmp) / "out"),
                project="session-to-song",
                genre="rock",
                duration=30,
                focus="celebrate the push",
                sound_reference="short anthem",
                summary="Successful push",
                audio=False,
                play=True,
                backend="auto",
                no_block=True,
                llm_provider="byok",
                llm_model="",
                music_provider="",
                music_model="",
            )
            with self.assertRaises(SystemExit):
                _handle_celebrate_push(args)

    def test_morning_alarm_cli_generates_audio_and_publishes_slot(self) -> None:
        from session_to_song.cli import _handle_morning_alarm
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp) / "out"
            target_dir = Path(tmp) / "alarms"
            generated_audio = Path(tmp) / "generated.mp3"
            generated_audio.write_bytes(b"audio")
            args = argparse.Namespace(
                config="",
                outdir=str(outdir),
                project="",
                genre="rap",
                duration=30,
                focus="wake me back into the mission",
                sound_reference="hard drums",
                target_dir=str(target_dir),
                llm_provider="",
                llm_model="",
                music_provider="",
                music_model="",
            )
            fake_source = type("Source", (), {
                "mode": "curated_daily_dreams",
                "label": "memory/2026-04-25.md",
                "reason": "dated wiki/memory plus dreams",
                "score": 1.0,
            })()
            fake_generated = type("Generated", (), {
                "path": generated_audio,
                "provider": "google",
                "model": "models/lyria-3-pro-preview",
            })()
            with patch("session_to_song.cli.resolve_best_session_source", return_value=fake_source), patch(
                "session_to_song.cli.extract_material_from_session", return_value=load_text_file_material(Path(__file__).resolve().parents[1] / "content" / "input" / "sample_day.txt")
            ), patch("session_to_song.cli.generate_music_audio", return_value=fake_generated) as mock_generate:
                self.assertEqual(_handle_morning_alarm(args), 0)
            prompt = mock_generate.call_args.kwargs["prompt"]
            self.assertIn("MANDATORY VOCAL CONTENT", prompt)
            self.assertIn("workflow", prompt)
            self.assertNotIn("[Alarm Track", prompt)
            self.assertEqual((target_dir / "S2S-morning.mp3").read_bytes(), b"audio")

    def test_alarm_slot_publishes_stable_morning_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "generated_audio.mp3"
            target_dir = Path(tmp) / "My Drive" / "sessiontosong" / "alarms"
            source.write_bytes(b"new alarm audio")
            result = publish_alarm_slot(source, slot="morning", target_dir=target_dir)
            self.assertTrue(result.ok)
            self.assertEqual(result.filename, "S2S-morning.mp3")
            self.assertEqual((target_dir / "S2S-morning.mp3").read_bytes(), b"new alarm audio")

    def test_alarm_slot_rejects_unsafe_slot_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "generated_audio.mp3"
            target_dir = Path(tmp) / "alarms"
            source.write_bytes(b"new alarm audio")
            with self.assertRaises(Exception):
                publish_alarm_slot(source, slot="../../bad", target_dir=target_dir)

    def test_alarm_slot_reports_locked_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "generated_audio.mp3"
            target_dir = Path(tmp) / "alarms"
            target_dir.mkdir()
            source.write_bytes(b"new alarm audio")
            target = target_dir / "S2S-morning.mp3"
            target.write_bytes(b"old")
            original_replace = Path.replace

            def fake_replace(self, target_path):
                if Path(target_path) == target:
                    raise PermissionError("locked")
                return original_replace(self, target_path)

            with patch("pathlib.Path.replace", fake_replace):
                with self.assertRaises(Exception):
                    publish_alarm_slot(source, slot="morning", target_dir=target_dir, retries=2)
            self.assertEqual(target.read_bytes(), b"old")

    def test_web_alarm_slot_native_picker_endpoint_returns_selected_path(self) -> None:
        completed = type("Completed", (), {"returncode": 0, "stdout": "C:\\Users\\Owner\\My Drive\\sessiontosong\\alarms\n", "stderr": ""})()
        with patch("session_to_song.web_app.sys.platform", "win32"), patch("session_to_song.web_app.subprocess.run", return_value=completed):
            status, _, payload = self._call_wsgi("/api/alarm-slot/pick-folder", method="POST", headers={"HTTP_X_S2S_TOKEN": web_app_module.WRITE_TOKEN})
        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["path"], "C:\\Users\\Owner\\My Drive\\sessiontosong\\alarms")

    def test_web_write_endpoints_require_token(self) -> None:
        status, _, payload = self._call_wsgi("/api/play-audio", method="POST", body=json.dumps({"name": "audio"}).encode("utf-8"))
        self.assertEqual(status, "403 Forbidden")
        self.assertEqual(payload["error"], "forbidden")

    def test_web_play_audio_rejects_arbitrary_path(self) -> None:
        status, _, payload = self._call_wsgi(
            "/api/play-audio",
            method="POST",
            body=json.dumps({"path": "C:/Windows/win.ini"}).encode("utf-8"),
            headers={"HTTP_X_S2S_TOKEN": web_app_module.WRITE_TOKEN},
        )
        self.assertEqual(status, "400 Bad Request")
        self.assertEqual(payload["error"], "bad_file")

    def test_web_alarm_slot_suggestions_endpoint_lists_drive_targets(self) -> None:
        status, _, payload = self._call_wsgi("/api/alarm-slot/suggestions")
        self.assertEqual(status, "200 OK")
        labels = [item["label"] for item in payload["suggestions"]]
        paths = [item["path"] for item in payload["suggestions"]]
        self.assertIn("Google Drive", labels)
        self.assertIn("iCloud Drive", labels)
        self.assertTrue(any("G:\\My Drive\\sessiontosong alarms" in path for path in paths))

    def test_web_alarm_slot_endpoint_publishes_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            latest_audio = Path(tmp) / "generated_audio.mp3"
            latest_audio.write_bytes(b"fake mp3")
            with patch("session_to_song.web_app.LATEST_AUDIO_PATH", latest_audio), patch("session_to_song.web_app.publish_alarm_slot") as mocked:
                mocked.return_value.to_dict.return_value = {"ok": True, "slot": "morning", "target_path": str(Path(tmp) / "S2S-morning.mp3")}
                status, _, payload = self._call_wsgi("/api/alarm-slot", method="POST", body=json.dumps({"name": "audio", "slot": "morning", "target_dir": tmp}).encode("utf-8"), headers={"HTTP_X_S2S_TOKEN": web_app_module.WRITE_TOKEN})
            self.assertEqual(status, "200 OK")
            self.assertTrue(payload["ok"])

    def test_playback_open_backend_opens_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "song.mp3"
            audio.write_bytes(b"fake mp3")
            with patch("session_to_song.playback.sys.platform", "win32"), patch("session_to_song.playback.os.startfile", create=True) as startfile:
                result = play_audio(audio, backend="open", block=False)
            self.assertTrue(result.ok)
            self.assertEqual(result.backend, "open")
            startfile.assert_called_once()

    def test_web_play_audio_endpoint_uses_local_playback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            latest_audio = Path(tmp) / "generated_audio.mp3"
            latest_audio.write_bytes(b"fake mp3")
            with patch("session_to_song.web_app.LATEST_AUDIO_PATH", latest_audio), patch("session_to_song.web_app.play_audio") as mocked:
                mocked.return_value.to_dict.return_value = {"ok": True, "backend": "powershell", "path": "audio.mp3"}
                status, _, payload = self._call_wsgi("/api/play-audio", method="POST", body=json.dumps({"name": "audio"}).encode("utf-8"), headers={"HTTP_X_S2S_TOKEN": web_app_module.WRITE_TOKEN})
        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["backend"], "powershell")

    def test_web_generate_audio_returns_clear_error_for_comfy_when_workflow_missing(self) -> None:
        body = json.dumps({"music_prompt": "Short hype track", "duration_seconds": 30}).encode("utf-8")
        comfy_config = load_user_config()
        comfy_config.music_provider = "comfy"
        comfy_config.music_model = "workflow"
        with patch("session_to_song.web_app.load_user_config", return_value=comfy_config), patch.dict(os.environ, {"COMFY_API_KEY": "test-comfy"}, clear=True):
            status, _, payload = self._call_wsgi("/api/generate-audio", method="POST", body=body, headers={"HTTP_X_S2S_TOKEN": web_app_module.WRITE_TOKEN})
        self.assertEqual(status, "500 Internal Server Error")
        self.assertEqual(payload["error"], "audio_generation_failed")
        self.assertIn("COMFY_MUSIC_WORKFLOW_PATH", payload["detail"])

    def test_legacy_mode_and_style_aliases_still_map(self) -> None:
        user_config = load_user_config()
        request = resolve_run_request(user_config, RunRequest(mode="memory", style="ambient_memory", question="what did we do yesterday?"))
        self.assertEqual(request.use, "reminder")
        self.assertEqual(request.genre, "alternative")
        self.assertEqual(request.focus, "what did we do yesterday?")

    def test_auto_source_resolves_recent_session_and_extracts_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".openclaw"
            sessions_dir = root / "agents" / "founders" / "sessions"
            sessions_dir.mkdir(parents=True)
            session_file = sessions_dir / "demo.jsonl"
            session_file.write_text(
                "\n".join(
                    [
                        json.dumps({"type": "session", "id": "demo"}),
                        json.dumps({"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "Session-to-song built the automatic session source."}]}}),
                        json.dumps({"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "Next session-to-song step is wiring the preview and removing manual paste."}]}}),
                    ]
                ),
                encoding="utf-8",
            )
            registry = {
                "agent:main:demo": {
                    "updatedAt": 9999999999999,
                    "startedAt": "2026-04-23T18:00:00Z",
                    "label": "session-to-song auto source",
                    "sessionFile": str(session_file),
                    "lastChannel": "telegram",
                }
            }
            (sessions_dir / "sessions.json").write_text(json.dumps(registry), encoding="utf-8")
            with patch.dict(os.environ, {"OPENCLAW_HOME": str(root), "SESSION_TO_SONG_OPENCLAW_WORKSPACE": "", "OPENCLAW_WORKSPACE": ""}, clear=False):
                source = resolve_best_session_source(SourceRequest(mode="auto", project="session-to-song"))
                self.assertIsNotNone(source)
                assert source is not None
                self.assertEqual(source.session_id, "demo")
                material = extract_material_from_session(source)
                self.assertIn("built the automatic session source", material.raw_text.lower())
                self.assertTrue(material.wins)

    def test_alarm_auto_source_prefers_dated_memory_and_dreams(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True)
            (memory_dir / "2026-04-25.md").write_text(
                "# 2026-04-25\n\n- Session-to-song fixed the alarm source ladder.\n- Next session-to-song move is validating yesterday plus dreams.\n",
                encoding="utf-8",
            )
            (workspace / "DREAMS.md").write_text(
                "# Dream Diary\n\n<!-- openclaw:dreaming:diary:start -->\n---\n\n*April 25, 2026 at 3:02 AM CST*\n\nA gateway opened beside a boardroom full of lanterns.\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"SESSION_TO_SONG_OPENCLAW_WORKSPACE": str(workspace)}, clear=False):
                source = resolve_best_session_source(SourceRequest(mode="auto", project="session-to-song", use="alarm", target_date="2026-04-25"))
            self.assertIsNotNone(source)
            assert source is not None
            self.assertEqual(source.mode, "curated_daily_dreams")
            self.assertIn("alarm source ladder", source.raw_text.lower())
            self.assertIn("boardroom full of lanterns", source.raw_text.lower())

    def test_auto_source_prefers_curated_openclaw_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".openclaw"
            workspace = root / "workspace"
            wiki_dir = workspace / "knowledge-base" / "wiki" / "daily"
            wiki_dir.mkdir(parents=True)
            (wiki_dir / "2026-04-23.md").write_text(
                "# Daily\n\nExampleProject shipped the curated session summary path.\nNext ExampleProject step is validating the memory-first source ladder.\n",
                encoding="utf-8",
            )
            sessions_dir = root / "agents" / "founders" / "sessions"
            sessions_dir.mkdir(parents=True)
            session_file = sessions_dir / "demo.jsonl"
            session_file.write_text(
                json.dumps({"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "ExampleProject raw transcript was noisier."}]}}),
                encoding="utf-8",
            )
            (sessions_dir / "sessions.json").write_text(json.dumps({"demo": {"updatedAt": 9999999999999, "sessionFile": str(session_file)}}), encoding="utf-8")
            with patch.dict(os.environ, {"OPENCLAW_HOME": str(root)}, clear=False):
                source = resolve_best_session_source(SourceRequest(mode="auto", project="ExampleProject"))
            self.assertIsNotNone(source)
            assert source is not None
            self.assertEqual(source.mode, "curated_context")
            self.assertIn("curated session summary", source.raw_text.lower())
            self.assertNotIn("raw transcript was noisier", source.raw_text.lower())

    def test_session_fetch_prefers_meaningful_lines_over_tail_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".openclaw"
            sessions_dir = root / "agents" / "founders" / "sessions"
            sessions_dir.mkdir(parents=True)
            session_file = sessions_dir / "demo.jsonl"
            rows = [
                {"type": "session", "id": "demo"},
                {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "We built auto session sourcing and fixed the vocal track bug."}]}},
                {"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "Next step is improving excerpt selection across the whole session."}]}},
                {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "Conversation info (untrusted metadata): chat_id example message_id 1 sender_id 2 timestamp now"}]}},
                {"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "NO_REPLY"}]}},
            ]
            session_file.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            (sessions_dir / "sessions.json").write_text(json.dumps({"demo": {"updatedAt": 9999999999999, "sessionFile": str(session_file)}}), encoding="utf-8")
            old = os.environ.get("OPENCLAW_HOME")
            os.environ["OPENCLAW_HOME"] = str(root)
            try:
                text = fetch_session_text("demo")
                self.assertIn("built auto session sourcing", text.lower())
                self.assertIn("improving excerpt selection", text.lower())
                self.assertNotIn("untrusted metadata", text.lower())
                self.assertNotIn("no_reply", text.lower())
            finally:
                if old is None:
                    os.environ.pop("OPENCLAW_HOME", None)
                else:
                    os.environ["OPENCLAW_HOME"] = old

    def test_auto_source_project_label_does_not_grab_whole_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".openclaw"
            sessions_dir = root / "agents" / "founders" / "sessions"
            sessions_dir.mkdir(parents=True)
            session_file = sessions_dir / "demo.jsonl"
            rows = [
                {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "Session-to-song shipped the celebrate source filter."}]}},
                {"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "OtherProject launched unrelated dashboard cleanup."}]}},
                {"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "Next Session-to-song step is testing project-only celebration material."}]}},
            ]
            session_file.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            (sessions_dir / "sessions.json").write_text(json.dumps({"demo": {"updatedAt": 9999999999999, "label": "session-to-song working room", "sessionFile": str(session_file)}}), encoding="utf-8")
            with patch.dict(os.environ, {"OPENCLAW_HOME": str(root)}, clear=False):
                source = resolve_best_session_source(SourceRequest(mode="auto", project="session-to-song", use="celebrate"))
            self.assertIsNotNone(source)
            assert source is not None
            self.assertIn("session-to-song", source.raw_text.lower())
            self.assertNotIn("otherproject", source.raw_text.lower())

    def test_session_fetch_filters_lines_by_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".openclaw"
            sessions_dir = root / "agents" / "founders" / "sessions"
            sessions_dir.mkdir(parents=True)
            session_file = sessions_dir / "demo.jsonl"
            rows = [
                {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "ExampleProject built project-scoped alarm sourcing."}]}},
                {"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "OtherProject fixed a separate dashboard issue."}]}},
                {"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "Next ExampleProject step is validating the alarm artifact."}]}},
            ]
            session_file.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            (sessions_dir / "sessions.json").write_text(json.dumps({"demo": {"updatedAt": 9999999999999, "sessionFile": str(session_file)}}), encoding="utf-8")
            old = os.environ.get("OPENCLAW_HOME")
            os.environ["OPENCLAW_HOME"] = str(root)
            try:
                text = fetch_session_text("demo", project="ExampleProject")
                self.assertIn("exampleproject built", text.lower())
                self.assertIn("next exampleproject", text.lower())
                self.assertNotIn("otherproject", text.lower())
            finally:
                if old is None:
                    os.environ.pop("OPENCLAW_HOME", None)
                else:
                    os.environ["OPENCLAW_HOME"] = old

    def test_recent_dream_context_reads_latest_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            dreams = workspace / "DREAMS.md"
            dreams.write_text(
                "# Dream Diary\n\n<!-- openclaw:dreaming:diary:start -->\n---\nold\n---\nnewer direction\n---\nlatest mission thread\n",
                encoding="utf-8",
            )
            text = load_recent_dream_context(dreams_path=dreams)
            self.assertIn("newer direction", text)
            self.assertIn("latest mission thread", text)
            self.assertNotIn("# Dream Diary", text)

    def test_recent_memory_context_reads_durable_bullets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True)
            (memory_dir / "2026-04-23.md").write_text(
                "# 2026-04-23\n\n- **Decision:** Auto-source should use session plus memory.\n- **Status:** Fixed the generic lyrics path.\nnoise\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"SESSION_TO_SONG_OPENCLAW_WORKSPACE": str(workspace)}, clear=False):
                text = load_recent_memory_context()
            self.assertIn("Auto-source should use session plus memory", text)
            self.assertIn("Fixed the generic lyrics path", text)

    def test_session_material_uses_archived_session_excerpt_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            kb_dir = workspace / "knowledge-base" / "raw" / "sessions"
            kb_dir.mkdir(parents=True)
            (kb_dir / "2026-04-23_main.md").write_text(
                """# Daily Sessions — main — 2026-04-23

# Session: main / demo

**Started:** 2026-04-23 18:00 UTC
**Session ID:** demo

---

### [18:01 UTC] USER

Session-to-song cut the long intro and added a fact-lock.

---

### [18:02 UTC] ASSISTANT

Next session-to-song step is fixing source-to-facts extraction so the wake-up track names what actually shipped.
""",
                encoding="utf-8",
            )
            source = type("Source", (), {
                "raw_text": "assistant: latest song was still too vague\nassistant: we restarted the app after the fix",
                "label": "demo",
                "project": "session-to-song",
                "session_key": "agent:main:demo",
                "session_id": "demo",
                "mode": "auto",
                "reason": "recent",
                "score": 1.0,
                "preview": "demo preview",
                "started_at": "2026-04-23T18:00:00Z",
            })()
            with patch.dict(os.environ, {"SESSION_TO_SONG_OPENCLAW_WORKSPACE": str(workspace)}, clear=False):
                material = extract_material_from_session(source)
            self.assertIn("Structured session facts", material.raw_text)
            self.assertIn("cut the long intro", material.raw_text.lower())
            self.assertIn("fact-lock", material.raw_text.lower())
            self.assertIn("source-to-facts extraction", material.raw_text.lower())
            self.assertTrue(material.next_actions)
            self.assertTrue(material.wins)

    def test_project_text_filter_does_not_leak_other_facts_from_mixed_lines(self) -> None:
        text = "Session-to-song added project scoping. OtherProject shipped unrelated protect work. OtherProject fixed dashboard noise."
        filtered = filter_text_for_project(text, "Session-to-song")
        self.assertIn("Session-to-song", filtered)
        self.assertNotIn("OtherProject", filtered)
        self.assertNotIn("OtherProject", filtered)

    def test_session_material_filters_archived_excerpt_by_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            kb_dir = workspace / "knowledge-base" / "raw" / "sessions"
            kb_dir.mkdir(parents=True)
            (kb_dir / "2026-04-23_main.md").write_text(
                """# Daily Sessions — main — 2026-04-23

# Session: main / demo

**Started:** 2026-04-23 18:00 UTC
**Session ID:** demo

---

### [18:01 UTC] USER

OtherProject shipped unrelated insurance upload polish.

---

### [18:02 UTC] ASSISTANT

Session-to-song added project-scoped alarm sourcing.
""",
                encoding="utf-8",
            )
            source = type("Source", (), {
                "raw_text": "assistant: Session-to-song should only sing about the selected project",
                "label": "demo",
                "project": "session-to-song",
                "session_key": "agent:main:demo",
                "session_id": "demo",
                "mode": "auto",
                "reason": "recent",
                "score": 1.0,
                "preview": "demo preview",
                "started_at": "2026-04-23T18:00:00Z",
            })()
            with patch.dict(os.environ, {"SESSION_TO_SONG_OPENCLAW_WORKSPACE": str(workspace)}, clear=False):
                material = extract_material_from_session(source)
            self.assertIn("session-to-song", material.raw_text.lower())
            self.assertNotIn("otherproject", material.raw_text.lower())


if __name__ == "__main__":
    unittest.main()
