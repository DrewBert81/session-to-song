from __future__ import annotations

import argparse
import math
import random
import shutil
import subprocess
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:  # pragma: no cover - friendly runtime error
    raise SystemExit("Pillow is required: python -m pip install Pillow") from exc

SLIDES = [
    ("WORK STOPS\nDISAPPEARING", "Session to Song"),
    ("EFFORT YOU CAN\nHEAR AGAIN", "not just another repo"),
    ("NOT NOTES.\nNOT LOGS.", "a pulse / a memory / a wake-up call"),
    ("THE BLUR OF THE DAY\nBECOMES SIGNAL", "turn raw sessions into something alive"),
    ("REPLAY THE MISSION", "bring the work back into the room"),
    ("LOOK AT WHAT\nYOU BUILT", "proof that the work happened"),
    ("MOMENTUM\nWITH A VOICE", "memory with rhythm"),
    ("FOR BUILDERS WHO\nSHIP REAL THINGS", "do not let the best work vanish into the scroll"),
    ("KEEP BUILDING.\nKEEP SHIPPING.", "raw sessions become something alive"),
    ("SESSION TO SONG", "work you can hear again"),
]

ACCENT_COLORS = [(255, 87, 51), (255, 190, 60), (97, 218, 251), (146, 94, 255)]


def _run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def _probe_duration(audio: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise SystemExit("ffprobe is required and was not found on PATH.")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return float(result.stdout.strip())


def _font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _default_font(name: str, size: int):
    candidates = [
        f"C:/Windows/Fonts/{name}",
        f"/System/Library/Fonts/{name}",
        f"/usr/share/fonts/truetype/dejavu/{name}",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return _font(str(path), size)
    return ImageFont.load_default()


def _render_slide(path: Path, idx: int, title: str, subtitle: str, footer: str, width: int = 1280, height: int = 720) -> None:
    img = Image.new("RGB", (width, height), (6, 8, 15))
    px = img.load()
    for y in range(height):
        for x in range(width):
            dx = (x - width * 0.35) / (width * 0.9)
            dy = (y - height * 0.35) / (height * 0.9)
            glow = max(0, 1 - (dx * dx + dy * dy))
            r = int(6 + 28 * glow + 16 * y / height)
            g = int(8 + 14 * glow + 5 * y / height)
            b = int(15 + 65 * glow + 30 * y / height)
            px[x, y] = (r, g, b)

    draw = ImageDraw.Draw(img, "RGBA")
    random.seed(idx)
    for _ in range(80):
        x = random.randint(0, width)
        y = random.randint(0, height)
        radius = random.randint(1, 3)
        color = random.choice(ACCENT_COLORS)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*color, random.randint(35, 90)))

    for i, color in enumerate(ACCENT_COLORS):
        x0 = 82 + i * 22
        draw.rounded_rectangle((x0, 92, x0 + 10, 628), radius=6, fill=(*color, 210))

    base = 590
    points = []
    for x in range(180, 1120, 8):
        amp = 18 + 12 * math.sin((x / 45) + idx)
        y = base + math.sin((x / 23) + idx * 0.7) * amp
        points.append((x, y))
    draw.line(points, fill=(97, 218, 251, 150), width=3)

    title_font = _default_font("arialbd.ttf", 78)
    subtitle_font = _default_font("arial.ttf", 34)
    footer_font = _default_font("arial.ttf", 24)
    bbox = draw.multiline_textbbox((0, 0), title, font=title_font, spacing=8)
    title_height = bbox[3] - bbox[1]
    tx = 170
    ty = 185 if "\n" in title else 245
    draw.multiline_text((tx + 4, ty + 4), title, font=title_font, fill=(0, 0, 0, 130), spacing=8)
    draw.multiline_text((tx, ty), title, font=title_font, fill=(255, 255, 255, 255), spacing=8)
    draw.text((tx, ty + title_height + 38), subtitle, font=subtitle_font, fill=(220, 230, 245, 230))
    draw.text((170, 650), footer, font=footer_font, fill=(180, 200, 230, 180))
    img.save(path)


def build_manifesto_slideshow(audio: Path, outdir: Path, output_name: str, footer: str, slides: list[tuple[str, str]]) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is required and was not found on PATH.")
    if not audio.exists():
        raise SystemExit(f"Audio file not found: {audio}")

    outdir.mkdir(parents=True, exist_ok=True)
    slides_dir = outdir / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)
    duration = _probe_duration(audio)
    segment_duration = math.ceil((duration / len(slides)) * 100) / 100

    segment_paths: list[Path] = []
    for idx, (title, subtitle) in enumerate(slides):
        slide_path = slides_dir / f"slide_{idx:02d}.png"
        segment_path = outdir / f"seg_{idx:02d}.mp4"
        _render_slide(slide_path, idx, title, subtitle, footer)
        if idx % 2 == 0:
            zoom = "zoompan=z='min(zoom+0.0008,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1280x720:fps=25"
        else:
            zoom = "zoompan=z='1.08-min(on*0.0008,0.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1280x720:fps=25"
        fade_out_start = max(segment_duration - 0.45, 0.1)
        _run([
            ffmpeg,
            "-y",
            "-loop",
            "1",
            "-t",
            str(segment_duration),
            "-i",
            str(slide_path),
            "-vf",
            f"{zoom},fade=t=in:st=0:d=0.4,fade=t=out:st={fade_out_start}:d=0.4,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-an",
            str(segment_path),
        ])
        segment_paths.append(segment_path)

    list_path = outdir / "segments.txt"
    list_path.write_text("\n".join(f"file '{path.resolve().as_posix()}'" for path in segment_paths), encoding="utf-8")
    silent_path = outdir / "slideshow_silent.mp4"
    output_path = outdir / output_name
    _run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path), "-c", "copy", str(silent_path)])
    _run([
        ffmpeg,
        "-y",
        "-i",
        str(silent_path),
        "-i",
        str(audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_path),
    ])
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an X-ready cinematic manifesto slideshow from a voiceover MP3.")
    parser.add_argument("--audio", required=True, help="Voiceover/audio file to use")
    parser.add_argument("--outdir", default="content/output/x-post-manifesto", help="Output directory")
    parser.add_argument("--output", default="session-to-song-work-you-can-hear-again.mp4", help="Output MP4 filename")
    parser.add_argument("--footer", default="session-to-song", help="Small footer text on each slide")
    args = parser.parse_args()

    output = build_manifesto_slideshow(Path(args.audio), Path(args.outdir), args.output, args.footer, SLIDES)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
