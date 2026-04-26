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

from session_to_song.adapters import load_text_file_material
from session_to_song.cli import _handle_doctor
from session_to_song.config_loader import load_config_data, load_user_config, resolve_genre, resolve_run_request, resolve_style, save_user_config_data
from session_to_song.connectors.openclaw_sessions import SourceRequest, fetch_session_text, resolve_best_session_source
from session_to_song.domain import RunRequest
from session_to_song.providers import detect_provider_status
from session_to_song.providers.google_music import MusicGenerationError
from session_to_song.providers.music_runtime import generate_music_audio, music_generation_available
from session_to_song.pipeline import build_from_material
from session_to_song.pipeline.session_material import extract_material_from_session, load_recent_dream_context, load_recent_memory_context
from session_to_song.project_filter import filter_text_for_project
from session_to_song.storage import write_artifacts
from session_to_song.web_app import app as web_app

SAMPLE = """
Built the daily pulse draft.
Fixed the naming for the wake-up track.
Blocked on polishing the final web flow.
Next step is validating the redesign end to end.
""".strip()


class SessionToSongTests(unittest.TestCase):
    def _call_wsgi(self, path: str, method: str = "GET", body: bytes = b"") -> tuple[str, dict[str, str], dict]:
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
            with patch.dict(os.environ, {"MINIMAX_API_KEY": "test-minimax"}, clear=True), redirect_stdout(buffer):
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

    def test_web_generate_audio_returns_clear_error_for_comfy_when_workflow_missing(self) -> None:
        body = json.dumps({"music_prompt": "Short hype track", "duration_seconds": 30}).encode("utf-8")
        comfy_config = load_user_config()
        comfy_config.music_provider = "comfy"
        comfy_config.music_model = "workflow"
        with patch("session_to_song.web_app.load_user_config", return_value=comfy_config), patch.dict(os.environ, {"COMFY_API_KEY": "test-comfy"}, clear=True):
            status, _, payload = self._call_wsgi("/api/generate-audio", method="POST", body=body)
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
                        json.dumps({"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "Built the automatic session source."}]}}),
                        json.dumps({"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "Next step is wiring the preview and removing manual paste."}]}}),
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
                self.assertIn("Built the automatic session source", material.raw_text)
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
