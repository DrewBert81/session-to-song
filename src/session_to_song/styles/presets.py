from __future__ import annotations

from ..domain import GenrePreset

STYLE_PRESETS: dict[str, GenrePreset] = {
    "rap": GenrePreset(
        key="rap",
        label="Rap",
        music_prompt_seed="bars-forward rap with punch, swagger, crisp drums, strong internal rhythm, and immediate momentum",
        intro_seed="Wake up, lock in, yesterday turned into fuel",
        hook_seed="Wake up, stack wins, turn the signal into momentum",
    ),
    "country": GenrePreset(
        key="country",
        label="Country",
        music_prompt_seed="grounded country storytelling with plainspoken lines, steady groove, warm acoustic detail, and narrative continuity",
        intro_seed="Morning light, boots on, here's what really happened",
        hook_seed="Sing it plain, sing it true, carry the work on through",
    ),
    "heavy_metal": GenrePreset(
        key="heavy_metal",
        label="Heavy Metal",
        music_prompt_seed="high-urgency heavy metal with driving drums, aggressive guitars, explosive choruses, and forceful forward motion",
        intro_seed="Lights hit hard, the room shakes, and the mission is live",
        hook_seed="Rise now, hit hard, take the fight into the day",
    ),
    "pop": GenrePreset(
        key="pop",
        label="Pop",
        music_prompt_seed="hook-first pop with bright lift, clean phrasing, catchy repetition, and emotional clarity",
        intro_seed="Hit the hook early, make the point impossible to miss",
        hook_seed="This is the moment, this is the move, sing it and go",
    ),
    "rock": GenrePreset(
        key="rock",
        label="Rock",
        music_prompt_seed="anthemic rock with driving guitars, shoutable chorus, strong momentum, and a big lift into the refrain",
        intro_seed="Turn it up, feel the push, and carry the signal forward",
        hook_seed="Raise it up, drive it home, we know what comes next",
    ),
    "alternative": GenrePreset(
        key="alternative",
        label="Alternative",
        music_prompt_seed="modern alternative with textured mood, restrained but distinct imagery, and focused emotional movement",
        intro_seed="Hold the thread, stay sharp, let the meaning surface",
        hook_seed="Keep the thread alive, keep the pressure pointed right",
    ),
    "folk": GenrePreset(
        key="folk",
        label="Folk",
        music_prompt_seed="human-scale folk with reflective concrete details, simple memorable lines, and an intimate grounded tone",
        intro_seed="Let's keep it human, simple, and honest about the work",
        hook_seed="Name what mattered, carry it forward, don't let it fade",
    ),
}


def get_style_preset(key: str) -> GenrePreset:
    return STYLE_PRESETS.get(key, STYLE_PRESETS["rap"])
