from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LLMProvider:
    provider: str
    model: str

    def summarize(self, text: str) -> str:
        return text

    def write_lyrics(self, prompt: str) -> str:
        return prompt


@dataclass
class MusicProvider:
    provider: str
    model: str

    def render_prompt(self, prompt: str) -> str:
        return prompt
