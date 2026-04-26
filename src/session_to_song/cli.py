from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adapters import load_hermes_material, load_openclaw_material, load_text_file_material
from .alarm_slots import AlarmSlotError, publish_alarm_slot
from .connectors.openclaw_sessions import SourceRequest, resolve_best_session_source
from .config_loader import (
    USER_CONFIG_PATH,
    load_config_data,
    load_user_config,
    resolve_run_request,
    save_user_config_data,
)
from .domain import LEGACY_MODE_TO_USE, LEGACY_STYLE_TO_GENRE, RunRequest
from .pipeline import build_from_material
from .pipeline.session_material import extract_material_from_session, load_recent_dream_context
from .playback import PlaybackError, play_audio
from .providers import detect_provider_status, generate_music_audio
from .storage import write_artifacts
from .styles import STYLE_PRESETS

USES = ["alarm", "reminder", "celebrate", "next_steps"]
GENRES = ["rap", "country", "heavy_metal", "pop", "rock", "alternative", "folk"]
DELIVERIES = ["save", "immediate", "scheduled", "milestone"]
INPUT_SOURCES = ["text", "openclaw", "hermes"]
SOURCE_MODES = ["manual", "auto", "current-session", "recent-session"]
LEGACY_MODES = ["alarm", "recap", "milestone", "memory", "build"]
LEGACY_STYLES = list(LEGACY_STYLE_TO_GENRE.keys())


def _validate_duration(value: str) -> int:
    duration = int(value)
    if duration < 15 or duration > 600:
        raise argparse.ArgumentTypeError("duration must be between 15 and 600 seconds")
    return duration


def _resolve_use_arg(args: argparse.Namespace, default: str = "alarm") -> str:
    if getattr(args, "use", None):
        return args.use
    if getattr(args, "mode", None):
        return LEGACY_MODE_TO_USE.get(args.mode, default)
    return default


def _resolve_genre_arg(args: argparse.Namespace) -> str | None:
    if getattr(args, "genre", None):
        return args.genre
    if getattr(args, "style", None):
        return LEGACY_STYLE_TO_GENRE.get(args.style)
    return None


def _resolve_focus_arg(args: argparse.Namespace) -> str | None:
    return (getattr(args, "focus", None) or getattr(args, "question", None) or None)


def _add_generate_fields(parser: argparse.ArgumentParser, *, include_input_file: bool) -> None:
    if include_input_file:
        parser.add_argument("input_file", nargs="?", default="content/input/sample_day.txt", help="Path to input text/session export")
    parser.add_argument("--config", default="", help="Optional path to user config JSON")
    parser.add_argument("--outdir", default="content/output/generated", help="Directory for generated artifacts")
    parser.add_argument("--use", choices=USES, default="", help="What the artifact is for")
    parser.add_argument("--genre", choices=GENRES, default="", help="What it should sound like")
    parser.add_argument("--focus", default="", help="Optional emphasis for the generated artifact")
    parser.add_argument("--mode", choices=LEGACY_MODES, default="", help=argparse.SUPPRESS)
    parser.add_argument("--style", choices=LEGACY_STYLES, default="", help=argparse.SUPPRESS)
    parser.add_argument("--question", default="", help=argparse.SUPPRESS)
    parser.add_argument("--delivery", choices=DELIVERIES, default="")
    parser.add_argument("--duration", type=_validate_duration, default=None, help="Target duration in seconds")
    parser.add_argument("--input-source", choices=INPUT_SOURCES, default="text")
    parser.add_argument("--source", choices=SOURCE_MODES, default="manual", help="Where to pull source material from")
    parser.add_argument("--session", default="", help="Optional explicit session key for session-based source modes")
    parser.add_argument("--lookback", type=int, default=36, help="Lookback window for auto session sourcing")
    parser.add_argument("--project", default="", help="Optional project label")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Turn sessions into use-driven lyrics, music prompts, and short replayable artifacts.")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Create or refresh local user config")
    init_parser.add_argument("--config", default="", help="Optional user config path")
    init_parser.add_argument("--llm-provider", default="", help="LLM provider label")
    init_parser.add_argument("--llm-model", default="", help="LLM model identifier")
    init_parser.add_argument("--music-provider", default="", help="Music provider label")
    init_parser.add_argument("--music-model", default="", help="Music model identifier")
    init_parser.add_argument("--genre", choices=GENRES, default="", help="Default genre")
    init_parser.add_argument("--style", choices=LEGACY_STYLES, default="", help=argparse.SUPPRESS)
    init_parser.add_argument("--delivery", choices=DELIVERIES, default="")
    init_parser.add_argument("--duration", type=_validate_duration, default=None, help="Default target duration in seconds")

    config_parser = subparsers.add_parser("config", help="Show effective config")
    config_parser.add_argument("show", nargs="?", default="show")
    config_parser.add_argument("--config", default="", help="Optional user config path")

    genre_parser = subparsers.add_parser("genre", help="Manage sticky genre defaults")
    genre_sub = genre_parser.add_subparsers(dest="genre_command", required=True)
    genre_set = genre_sub.add_parser("set", help="Set default/use/project genre")
    genre_set.add_argument("scope", choices=["default", "use", "project"])
    genre_set.add_argument("target", nargs="?", default="")
    genre_set.add_argument("genre", choices=GENRES, help="Genre key")
    genre_set.add_argument("--config", default="", help="Optional user config path")

    style_parser = subparsers.add_parser("style", help="Deprecated alias for genre management")
    style_sub = style_parser.add_subparsers(dest="style_command", required=True)
    style_set = style_sub.add_parser("set", help="Deprecated alias for genre set")
    style_set.add_argument("scope", choices=["default", "mode", "project"])
    style_set.add_argument("target", nargs="?", default="")
    style_set.add_argument("style", choices=LEGACY_STYLES, help="Legacy style preset key")
    style_set.add_argument("--config", default="", help="Optional user config path")

    test_parser = subparsers.add_parser("test", help="Generate a sample run using current config")
    _add_generate_fields(test_parser, include_input_file=False)
    test_parser.set_defaults(outdir="content/output/test-run")

    generate_parser = subparsers.add_parser("generate", help="Generate artifacts from an input file")
    _add_generate_fields(generate_parser, include_input_file=True)

    play_parser = subparsers.add_parser("play", help="Play a generated MP3 on this computer")
    play_parser.add_argument("file", nargs="?", default="content/output/webui-latest/generated_audio.mp3", help="MP3/audio file to play")
    play_parser.add_argument("--backend", choices=["auto", "powershell", "ffplay", "vlc", "open"], default="auto")
    play_parser.add_argument("--volume", type=int, default=100, help="Playback volume 0-100 when supported")
    play_parser.add_argument("--no-block", action="store_true", help="Start playback and return immediately")
    play_parser.add_argument("--timeout", type=int, default=600, help="Maximum playback seconds for blocking backends")

    slot_parser = subparsers.add_parser("alarm-slot", help="Publish an MP3 to a stable phone/Drive alarm slot")
    slot_parser.add_argument("slot", nargs="?", default="morning", help="Slot name, e.g. morning, break, reminder")
    slot_parser.add_argument("--file", default="content/output/webui-latest/generated_audio.mp3", help="Source MP3/audio file")
    slot_parser.add_argument("--target-dir", default="", help="Folder synced to phone/Drive, e.g. My Drive/sessiontosong/alarms")

    morning_parser = subparsers.add_parser("morning-alarm", help="Generate and publish the nightly S2S-morning.mp3 alarm slot")
    morning_parser.add_argument("--config", default="", help="Optional path to user config JSON")
    morning_parser.add_argument("--outdir", default="content/output/morning-alarm", help="Directory for generated artifacts")
    morning_parser.add_argument("--project", default="", help="Optional project label for the morning alarm")
    morning_parser.add_argument("--genre", choices=GENRES, default="rap")
    morning_parser.add_argument("--duration", type=_validate_duration, default=60)
    morning_parser.add_argument("--focus", default="wake me back into the mission: yesterday, today, and why it matters")
    morning_parser.add_argument("--sound-reference", default="energetic wake-up rap alarm, hard drums, bright synth pulse, deep bass, motivational but not cheesy")
    morning_parser.add_argument("--target-dir", default="", help="Folder synced to phone/Drive, e.g. G:\\My Drive\\sessiontosong alarms")
    morning_parser.add_argument("--llm-provider", default="", help="Optional one-run text writer provider")
    morning_parser.add_argument("--llm-model", default="", help="Optional one-run text writer model")
    morning_parser.add_argument("--music-provider", default="", help="Optional one-run music provider")
    morning_parser.add_argument("--music-model", default="", help="Optional one-run music model")

    doctor_parser = subparsers.add_parser("doctor", help="Inspect provider/env setup and show what will be used")
    doctor_parser.add_argument("--config", default="", help="Optional user config path")

    return parser


def _load_material(input_source: str, input_file: str, project: str | None):
    if input_source == "openclaw":
        return load_openclaw_material(input_file, project=project)
    if input_source == "hermes":
        return load_hermes_material(input_file, project=project)
    return load_text_file_material(input_file, project=project)


def _emit_run_summary(user_config, request, files: dict[str, Path]) -> int:
    provider_status = detect_provider_status(
        llm_provider=user_config.llm_provider,
        llm_model=user_config.llm_model,
        music_provider=user_config.music_provider,
        music_model=user_config.music_model,
    )
    for _, path in files.items():
        print(f"Wrote {path}")
    print(
        f"LLM provider: {provider_status.llm.provider} [{provider_status.llm.model}] "
        f"source={provider_status.llm.source} configured={provider_status.llm.available}"
    )
    if provider_status.llm.message:
        print(f"LLM note: {provider_status.llm.message}")
    print(
        f"Music provider: {provider_status.music.provider} [{provider_status.music.model or 'n/a'}] "
        f"source={provider_status.music.source} configured={provider_status.music.available}"
    )
    if provider_status.music.message:
        print(f"Music note: {provider_status.music.message}")
    print(f"Use: {request.use}")
    print(f"Genre: {request.genre}")
    print(f"Focus: {request.focus or '(none)'}")
    print(f"Delivery: {request.delivery}")
    print(f"Duration: {request.duration_seconds}s")
    return 0


def _handle_generate(args: argparse.Namespace) -> int:
    user_config = load_user_config(args.config or None)
    request = resolve_run_request(
        user_config,
        RunRequest(
            use=_resolve_use_arg(args),
            genre=_resolve_genre_arg(args),
            focus=_resolve_focus_arg(args),
            delivery=args.delivery or None,
            duration_seconds=args.duration,
            input_source=args.input_source,
            source_mode=(args.source or "manual").replace("-", "_"),
            source_session_key=args.session or None,
            lookback_hours=args.lookback,
            project=args.project or None,
            mode=args.mode or None,
            style=args.style or None,
            question=args.question or None,
        ),
    )
    if request.source_mode == "manual":
        material = _load_material(args.input_source, args.input_file, args.project or None)
    else:
        source = resolve_best_session_source(
            SourceRequest(
                mode=request.source_mode,
                session_key=request.source_session_key,
                project=request.project,
                lookback_hours=request.lookback_hours or 36,
                use=request.resolved_use,
            )
        )
        if source is None:
            raise SystemExit("No recent session source found.")
        material = extract_material_from_session(source, title=source.label, use=request.resolved_use)
    artifacts = build_from_material(material, user_config, request)
    files = write_artifacts(Path(args.outdir), artifacts)
    return _emit_run_summary(user_config, request, files)


def _handle_init(args: argparse.Namespace) -> int:
    data = load_config_data(args.config or None)
    if args.llm_provider:
        data["providers"]["llm"]["provider"] = args.llm_provider
    if args.llm_model:
        data["providers"]["llm"]["model"] = args.llm_model
    if args.music_provider:
        data["providers"]["music"]["provider"] = args.music_provider
    if args.music_model:
        data["providers"]["music"]["model"] = args.music_model
    genre = args.genre or LEGACY_STYLE_TO_GENRE.get(args.style, "")
    if genre:
        data["defaults"]["genre"] = genre
    if args.delivery:
        data["defaults"]["delivery"] = args.delivery
    if args.duration is not None:
        data["defaults"]["duration_seconds"] = args.duration
    target = save_user_config_data(data, args.config or None)
    print(f"Wrote user config: {target}")
    print("Use `session-to-song config show` to inspect it.")
    return 0


def _handle_config_show(args: argparse.Namespace) -> int:
    data = load_config_data(args.config or None)
    effective = Path(args.config) if args.config else USER_CONFIG_PATH
    print(f"User config path: {effective}")
    print(json.dumps(data, indent=2))
    return 0


def _handle_genre_set(args: argparse.Namespace) -> int:
    data = load_config_data(args.config or None)
    data.setdefault("preferences", {}).setdefault("genre_by_use", {})
    data.setdefault("preferences", {}).setdefault("genre_by_project", {})

    if args.scope == "default":
        data["defaults"]["genre"] = args.genre
    elif args.scope == "use":
        if not args.target:
            raise SystemExit("Use target required. Example: genre set use alarm rap")
        data["preferences"]["genre_by_use"][args.target] = args.genre
    elif args.scope == "project":
        if not args.target:
            raise SystemExit("Project target required. Example: genre set project ClientPortal rock")
        data["preferences"]["genre_by_project"][args.target] = args.genre

    target = save_user_config_data(data, args.config or None)
    print(f"Updated genre config: {target}")
    return 0


def _handle_style_set(args: argparse.Namespace) -> int:
    translated_scope = "use" if args.scope == "mode" else args.scope
    translated_args = argparse.Namespace(
        scope=translated_scope,
        target=args.target,
        genre=LEGACY_STYLE_TO_GENRE[args.style],
        config=args.config,
    )
    return _handle_genre_set(translated_args)


def _handle_test(args: argparse.Namespace) -> int:
    generate_args = argparse.Namespace(**vars(args), input_file="content/input/sample_day.txt")
    return _handle_generate(generate_args)


def _format_env_line(name: str, present: bool) -> str:
    return f"- {name}: {'set' if present else 'missing'}"


def _format_provider_line(option) -> str:
    env_names = "/".join(option.env_vars)
    runtime = "runtime-ready" if option.runtime_supported else "metadata-only"
    return f"- {option.name}: {'available' if option.available else 'missing'} via {env_names} | default model={option.default_model} | {runtime}"


def _doctor_status_lines(status) -> list[str]:
    lines = ["Text artifacts: ready (offline template mode always works)."]
    if status.llm.available and status.llm.runtime_supported:
        lines.append(f"Live LLM artifacts: ready via {status.llm.provider} [{status.llm.model}].")
    elif status.llm.provider == "template":
        lines.append("Live LLM artifacts: optional. No key found, so the repo will stay in built-in template mode.")
    else:
        lines.append(f"Live LLM artifacts: not ready. {status.llm.message}")

    if status.music.available and status.music.runtime_supported:
        lines.append(f"Live audio: ready via {status.music.provider} [{status.music.model}].")
    elif status.music.provider == "unconfigured":
        lines.append("Live audio: optional. No music key found, so audio stays disabled and text artifacts still work.")
    else:
        lines.append(f"Live audio: not ready. {status.music.message}")
    return lines


def _doctor_next_steps(status) -> list[str]:
    help_lines: list[str] = []
    if status.llm.provider == "template":
        help_lines.append("For live LLM synthesis, set OPENROUTER_API_KEY or OPENAI_API_KEY. Otherwise you can keep using template mode.")
    elif status.llm.source == "explicit" and not status.llm.available:
        help_lines.append(status.llm.message)
    elif status.llm.source == "explicit" and status.llm.available and not status.llm.runtime_supported:
        help_lines.append(status.llm.message)
    elif status.llm.source == "env" and status.llm.available and not status.llm.runtime_supported:
        help_lines.append(status.llm.message)

    if status.music.provider == "unconfigured":
        help_lines.append("For browser-playable audio, set GOOGLE_API_KEY or GEMINI_API_KEY. Google/Gemini is the supported live audio path in this repo today.")
    elif status.music.source == "explicit" and not status.music.available:
        help_lines.append(status.music.message)
    elif status.music.available and not status.music.runtime_supported:
        help_lines.append(status.music.message)

    if help_lines:
        help_lines.append("Copy .env.example to .env, add only the keys you plan to use, then rerun `session-to-song doctor`.")
    return help_lines


def _handle_play(args: argparse.Namespace) -> int:
    try:
        result = play_audio(
            args.file,
            backend=args.backend,
            volume=args.volume,
            block=not args.no_block,
            timeout_seconds=args.timeout,
        )
    except PlaybackError as exc:
        raise SystemExit(f"Playback failed: {exc}")
    print(json.dumps(result.to_dict(), indent=2))
    return 0


def _handle_alarm_slot(args: argparse.Namespace) -> int:
    try:
        result = publish_alarm_slot(args.file, slot=args.slot, target_dir=args.target_dir or None)
    except AlarmSlotError as exc:
        raise SystemExit(f"Alarm slot publish failed: {exc}")
    print(json.dumps(result.to_dict(), indent=2))
    return 0


def _handle_morning_alarm(args: argparse.Namespace) -> int:
    user_config = load_user_config(args.config or None)
    if args.llm_provider:
        user_config.llm_provider = args.llm_provider
    if args.llm_model:
        user_config.llm_model = args.llm_model
    if args.music_provider:
        user_config.music_provider = args.music_provider
    if args.music_model:
        user_config.music_model = args.music_model

    request = resolve_run_request(
        user_config,
        RunRequest(
            use="alarm",
            genre=args.genre,
            focus=args.focus,
            sound_reference=args.sound_reference,
            duration_seconds=args.duration,
            source_mode="auto",
            lookback_hours=72,
            project=args.project or None,
        ),
    )
    source = resolve_best_session_source(
        SourceRequest(
            mode="auto",
            project=request.project,
            lookback_hours=request.lookback_hours or 72,
            use=request.resolved_use,
        )
    )
    if source is None:
        raise SystemExit("No dated memory/wiki/dream/session source found for morning alarm.")
    material = extract_material_from_session(source, title=source.label, use=request.resolved_use)
    artifacts = build_from_material(material, user_config, request)
    outdir = Path(args.outdir)
    files = write_artifacts(outdir, artifacts)
    generated = generate_music_audio(
        prompt=artifacts.music_prompt,
        out_dir=outdir,
        duration_seconds=request.duration_seconds or user_config.duration_seconds,
        user_config=user_config,
        preferred_model=args.music_model or None,
        preferred_provider=args.music_provider or None,
    )
    slot = publish_alarm_slot(generated.path, slot="morning", target_dir=args.target_dir or None)
    result = {
        "source": {
            "mode": source.mode,
            "label": source.label,
            "reason": source.reason,
            "score": source.score,
        },
        "artifacts": {key: str(path) for key, path in files.items()},
        "audio": {
            "path": str(generated.path),
            "provider": generated.provider,
            "model": generated.model,
        },
        "alarm_slot": slot.to_dict(),
    }
    print(json.dumps(result, indent=2))
    return 0


def _handle_doctor(args: argparse.Namespace) -> int:
    user_config = load_user_config(args.config or None)
    status = detect_provider_status(
        llm_provider=user_config.llm_provider,
        llm_model=user_config.llm_model,
        music_provider=user_config.music_provider,
        music_model=user_config.music_model,
    )
    effective = Path(args.config) if args.config else USER_CONFIG_PATH
    print(f"User config path: {effective}")
    print("")
    print("Environment:")
    for name, present in status.env.items():
        print(_format_env_line(name, present))
    print("")
    print("LLM providers:")
    for option in status.llm_options:
        print(_format_provider_line(option))
    print("")
    print("Music providers:")
    for option in status.music_options:
        print(_format_provider_line(option))
    print("")
    print("Setup status:")
    for line in _doctor_status_lines(status):
        print(f"- {line}")
    print("")
    print(
        f"Resolved LLM: {status.llm.provider} [{status.llm.model}] via {status.llm.source} "
        f"(configured={'yes' if status.llm.available else 'no'}, runtime={'yes' if status.llm.runtime_supported and status.llm.available else 'no'})"
    )
    if status.llm.message:
        print(f"LLM note: {status.llm.message}")
    print(
        f"Resolved music: {status.music.provider} [{status.music.model or 'n/a'}] via {status.music.source} "
        f"(configured={'yes' if status.music.available else 'no'})"
    )
    if status.music.message:
        print(f"Music note: {status.music.message}")

    help_lines = _doctor_next_steps(status)

    if help_lines:
        print("")
        print("Next steps:")
        for line in help_lines:
            print(f"- {line}")

    if (status.llm.source == "explicit" and not status.llm.available) or (status.music.source == "explicit" and not status.music.available):
        return 1
    if status.llm.source == "explicit" and status.llm.provider == user_config.llm_provider and not status.llm.runtime_supported:
        return 1
    if status.music.source == "explicit" and status.music.provider == user_config.music_provider and not status.music.runtime_supported:
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        raise SystemExit(1)
    return args


def main() -> int:
    args = parse_args()
    if args.command == "init":
        return _handle_init(args)
    if args.command == "config":
        return _handle_config_show(args)
    if args.command == "genre":
        return _handle_genre_set(args)
    if args.command == "style":
        return _handle_style_set(args)
    if args.command == "test":
        return _handle_test(args)
    if args.command == "generate":
        return _handle_generate(args)
    if args.command == "play":
        return _handle_play(args)
    if args.command == "alarm-slot":
        return _handle_alarm_slot(args)
    if args.command == "morning-alarm":
        return _handle_morning_alarm(args)
    if args.command == "doctor":
        return _handle_doctor(args)
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
