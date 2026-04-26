import asyncio
import os
import re
import wave
from pathlib import Path

from google import genai
from google.genai import types

OUT = Path(__file__).resolve().parents[1] / 'content' / 'output' / 'webui-latest' / 'test_live_music.wav'

if os.getenv('SESSION_TO_SONG_ALLOW_DEV_SCRIPTS', '').strip().lower() not in {'1', 'true', 'yes'}:
    raise SystemExit(
        'test_music_live.py is a developer-only live smoke test. '
        'Use the web UI audio flow or set SESSION_TO_SONG_ALLOW_DEV_SCRIPTS=1 if you really want this script.'
    )


def pcm_to_wav(raw: bytes, mime_type: str, out_path: Path):
    sample_rate = 44100
    channels = 2
    bits = 16
    m = re.search(r'rate=(\d+)', mime_type or '')
    if m:
        sample_rate = int(m.group(1))
    m = re.search(r'channels=(\d+)', mime_type or '')
    if m:
        channels = int(m.group(1))
    if 'L16' in (mime_type or '') or 'pcm' in (mime_type or '').lower():
        bits = 16
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(bits // 8)
        wf.setframerate(sample_rate)
        wf.writeframes(raw)


async def main():
    client = genai.Client()
    chunks = []
    mime_type = None
    async with client.aio.live.music.connect(model='models/lyria-3-pro-preview') as session:
        await session.set_weighted_prompts([
            types.WeightedPrompt(text='bright cinematic sunrise, hopeful synths, gentle drums', weight=1.0)
        ])
        await session.set_music_generation_config(
            types.LiveMusicGenerationConfig(temperature=1.0, guidance=4.0)
        )
        await session.play()
        async for msg in session.receive():
            if msg.server_content and msg.server_content.audio_chunks:
                for chunk in msg.server_content.audio_chunks:
                    if chunk.data:
                        chunks.append(chunk.data)
                        mime_type = chunk.mime_type or mime_type
            if sum(len(c) for c in chunks) > 48000 * 2 * 2 * 4:
                break
        await session.stop()
    raw = b''.join(chunks)
    print('bytes', len(raw), 'mime', mime_type)
    pcm_to_wav(raw, mime_type or 'audio/pcm;rate=48000;channels=2', OUT)
    print(OUT)


if __name__ == '__main__':
    asyncio.run(main())
