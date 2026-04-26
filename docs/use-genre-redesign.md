# session-to-song: Use + Genre Redesign

## Why this redesign exists

The current product model is too muddy.

Right now the app mixes together:
- mode
- style
- angle
- prompt intent

That causes two failures:
1. the generator does not reliably know **what job the artifact is supposed to do**
2. the music/lyric layer does not cleanly know **what sound it should aim for**

Result:
- strategy questions get forced into song-shaped output
- wake-up outputs can become soft instead of energizing
- recap/reminder outputs can miss the actual accomplishments
- UI controls feel redundant and confusing

The fix is to separate:
- **Use** = what this artifact is for
- **Genre** = what it should sound like

---

## New product model

### 1. Use
This is the job.

Supported values:
- `alarm` — wake up / pump up
- `reminder` — where the project is at and where it’s going
- `celebrate` — what you just built
- `next_steps` — pump-up anthem explaining what’s next

### 2. Genre
This is the sound.

Supported values:
- `rap`
- `country`
- `heavy_metal`
- `pop`
- `rock`
- `alternative`
- `folk`

### 3. Source
This is the factual material.

Supported values:
- pasted text
- project summary
- session transcript
- worklog / notes
- future connectors (OpenClaw session, Claude Code, Perplexity, etc.)

### 4. Focus
This is optional emphasis.

Examples:
- what matters today
- what we accomplished yesterday
- what shipped
- where the project is going
- what must happen next

### 5. Length
Duration in seconds.

---

## UI model

Replace current mental model:
- mode
- style
- angle

with:
- **What do you need this for?** → Use
- **What genre should it be?** → Genre
- **What should I use?** → Source
- **What should it focus on?** → Focus
- **How long should it be?** → Length

### Proposed UI labels

#### Primary controls
- **Use**
- **Genre**
- **Source material**
- **Focus**
- **Length**

#### Use card helper copy
- **Alarm** — wake me up with energy and momentum
- **Reminder** — remind me where the project stands and where it’s going
- **Celebrate** — turn what I just built into a win track
- **Next steps** — explain what happens next and make me want to move

#### Genre helper copy
- **Rap** — bars, punch, swagger, momentum
- **Country** — narrative, grounded, plainspoken
- **Heavy Metal** — aggression, urgency, force
- **Pop** — hook-first, bright, memorable
- **Rock** — driving, anthemic, guitar-forward
- **Alternative** — textured, modern, moody
- **Folk** — human, reflective, simple

---

## Generator contract

Generation should become:

`artifact = Use + Genre + Source + Focus + Duration`

Not:

`artifact = ambiguous mode/style/question blend`

---

## Use-specific content rules

## `alarm`
### Goal
Wake the listener up with real momentum.

### Must do
- include **real accomplishments from yesterday** when source supports it
- convert recap into forward motion
- feel energetic from line 1
- prioritize punch over nuance

### Should avoid
- vague affirmations
- soft wellness lyrics with no project facts
- sleepy intros

### Structure
- hard opening hook
- 2–4 concrete accomplishments
- why that matters now
- strong forward-facing ending

### Example output intent
"Yesterday we fixed X, found Y, and now today we push Z."

---

## `reminder`
### Goal
Explain where the project stands and where it is going.

### Must do
- summarize current state
- include direction of travel
- mention blocker / tension if present
- feel clarifying, not random

### Should avoid
- victory framing when nothing shipped
- generic inspiration without state

### Structure
- where things are
- what changed
- where this is headed
- what to keep in mind

---

## `celebrate`
### Goal
Turn completed work into a satisfying win artifact.

### Must do
- name what was built
- name what changed
- explain why it matters
- sound like a payoff

### Should avoid
- future planning dominating the track
- vague "we did great" filler

### Structure
- what shipped
- what got solved
- why it matters
- triumphant payoff

---

## `next_steps`
### Goal
Make the next move feel obvious and energizing.

### Must do
- name the next concrete moves
- connect current progress to next action
- create urgency and forward pull

### Should avoid
- getting stuck in recap only
- abstract motivation with no next action

### Structure
- where we are now
- what comes next
- what matters most today
- closing push

---

## Genre-specific writing rules

## `rap`
- short lines
- stronger internal rhythm
- more direct phrasing
- confidence > prettiness
- hooks should hit early

## `country`
- plain language
- narrative continuity
- concrete details
- grounded emotional tone

## `heavy_metal`
- intense verbs
- sharper imagery
- higher urgency
- fewer soft filler lines
- choruses should feel explosive

## `pop`
- immediate hook
- repeated memorable phrase
- cleaner, simpler wording
- emotional clarity

## `rock`
- anthemic cadence
- strong momentum
- shoutable chorus
- bigger lift into refrain

## `alternative`
- moodier texture
- modern phrasing
- restrained but distinct imagery

## `folk`
- human-scale details
- reflective but concrete
- simple memorable lines

---

## Prompting architecture

Split generation into two distinct branches:

### Branch A: content planner
Inputs:
- use
- source
- focus
- duration

Outputs:
- extracted facts
- emotional objective
- structure plan
- line priorities

This branch answers:
- what actually happened?
- what should be included?
- what is the artifact trying to accomplish?

### Branch B: genre renderer
Inputs:
- genre
- content plan
- duration

Outputs:
- lyrics / script draft
- music prompt
- energy instructions

This branch answers:
- how should it sound?
- how aggressive / catchy / grounded should it feel?
- what instrumentation/cadence should be implied?

This is the core separation that fixes the product bug.

---

## Data model changes

## Current
- `mode`
- `style`
- `question`

## New
- `use`
- `genre`
- `focus`

### Proposed config shape

```json
{
  "providers": {
    "llm": { "provider": "openrouter", "model": "anthropic/claude-3.7-sonnet" },
    "music": { "provider": "google", "model": "models/lyria-3-pro-preview" }
  },
  "defaults": {
    "use": "alarm",
    "genre": "rap",
    "delivery": "save",
    "duration_seconds": 45
  },
  "preferences": {
    "genre_by_use": {
      "alarm": "rap",
      "reminder": "rock",
      "celebrate": "rap",
      "next_steps": "heavy_metal"
    },
    "genre_by_project": {}
  }
}
```

---

## Domain model changes

### Replace
- `RunMode`
- style-first resolution model

### With
- `ArtifactUse`
- `Genre`
- `Focus`

### Proposed enums

```python
ArtifactUse = Literal["alarm", "reminder", "celebrate", "next_steps"]
Genre = Literal["rap", "country", "heavy_metal", "pop", "rock", "alternative", "folk"]
```

### Proposed request model

```python
@dataclass
class RunRequest:
    use: ArtifactUse = "alarm"
    genre: Genre | None = None
    focus: str | None = None
    delivery: DeliveryMode | None = None
    duration_seconds: int | None = None
    input_source: str = "text"
    project: str | None = None
```

---

## Backward compatibility / migration

Map old values into the new model during transition.

### Old mode -> new use
- `alarm` -> `alarm`
- `memory` -> `reminder`
- `recap` -> `reminder`
- `milestone` -> `celebrate`
- `build` -> `celebrate`

### Old style -> default genre suggestion
Temporary only:
- `boom_bap_alarm` -> `rap`
- `metalcore_wake` -> `heavy_metal`
- `ambient_memory` -> `alternative` or `folk` depending on use
- `victory_anthem` -> `rock`
- `build_reflection` -> `alternative`

Important:
old style presets should not remain the user-facing primary control.

---

## CLI changes

### New arguments
- `--use`
- `--genre`
- `--focus`

### Deprecate
- `--mode`
- `--style`
- `--question`

### Example

```bash
session-to-song generate notes.txt \
  --use alarm \
  --genre rap \
  --focus "what did we accomplish yesterday and what matters today" \
  --duration 45
```

---

## Web UI changes

## Current problem
The web app still behaves like a builder console.

## New flow
1. pick **Use**
2. pick **Genre**
3. provide **Source material**
4. set **Focus**
5. set **Length**
6. generate draft
7. generate audio

## Specific implementation changes
- replace current mode pills with **Use** pills
- replace current style chips with **Genre** chips
- rename question field to **Focus**
- update preview panel to show:
  - Use
  - Genre
  - Focus
  - Length
- ensure the backend manifest writes `use` and `genre`

---

## Success criteria

The redesign is successful when:

1. **Alarm** outputs actually mention yesterday’s accomplishments
2. **Alarm** outputs feel energizing, not soft
3. **Reminder** outputs explain project state + direction
4. **Celebrate** outputs feel like payoff, not recap soup
5. **Next steps** outputs clearly state what comes next
6. genre choice changes phrasing and energy in obvious ways
7. the user no longer feels like they are picking the same thing twice

---

## Recommended implementation order

### Phase 1 — model cleanup
- add `use` + `genre` enums/types
- add migration from old mode/style
- update manifest schema

### Phase 2 — generator branching
- create use-based planner branch
- create genre-based renderer branch
- make content extraction depend on use, not genre

### Phase 3 — UI cleanup
- replace mode/style with use/genre in web UI
- rename question -> focus
- update labels and preview

### Phase 4 — CLI cleanup
- add `--use`, `--genre`, `--focus`
- keep old flags as deprecated aliases temporarily

### Phase 5 — quality pass
- test all 4 uses x 7 genres
- specifically validate:
  - `alarm + rap`
  - `alarm + heavy_metal`
  - `reminder + rock`
  - `celebrate + rap`
  - `next_steps + heavy_metal`

---

## Recommendation

This redesign should be treated as a **product correction**, not a cosmetic copy tweak.

The core rule going forward:

- **Use decides content**
- **Genre decides sound**

If the code follows that rule consistently, the app will stop producing confused artifacts.
