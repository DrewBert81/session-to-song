/* ─── session-to-song · app.js ─────────────────── */

const USE_META = {
  alarm:      { icon: '⏰', label: 'Alarm',      desc: 'Wake up with energy and momentum' },
  reminder:   { icon: '📍', label: 'Reminder',   desc: 'Where the project stands and what is next' },
  celebrate:  { icon: '🏆', label: 'Celebrate',  desc: 'Turn what shipped into a win track' },
};

const GENRE_DESC = {
  rap:          'Bars, punch, swagger',
  country:      'Narrative, grounded',
  heavy_metal:  'Aggression, urgency',
  pop:          'Hook-first, bright',
  rock:         'Driving, anthemic',
  alternative:  'Textured, moody',
  folk:         'Human, reflective',
};

const GENRE_FOR_USE = { alarm: 'rap', reminder: 'rock', celebrate: 'rap', next_steps: 'heavy_metal' };
const FOCUS_FOR_USE = {
  alarm: 'wake me back into the mission: yesterday, today, and why it matters',
  reminder: 'state check: where the project stands, what is unresolved, and what to remember',
  celebrate: 'payoff: what landed, what changed, and the win worth replaying',
  next_steps: 'next move: the concrete action to take now and why it matters',
};

/* ─── STATE ─────────────────────────────────── */
const state = {
  use: 'celebrate',
  genre: 'rap',
  duration_seconds: 45,
  project: '',
  music_model: '',
  lastMusicPrompt: '',
  audioAvailable: false,
  genres: [],
  uses: ['alarm', 'reminder', 'celebrate'],
  durations: [30, 45, 60, 90],
};

/* ─── DOM REFS ──────────────────────────────── */
const $ = (id) => document.getElementById(id);
const els = {
  heroGenerateBtn:   $('heroGenerateBtn'),
  heroCustomizeBtn:  $('heroCustomizeBtn'),
  mainLayout:        $('mainLayout'),
  providerBadge:     $('providerBadge'),
  useList:           $('useList'),
  genreList:         $('genreList'),
  durationList:      $('durationList'),
  llmSelect:         $('llmSelect'),
  modelSelect:       $('modelSelect'),
  artistInput:       $('artistInput'),
  projectInput:      $('projectInput'),
  generateBtn:       $('generateBtn'),
  generateAudioBtn:  $('generateAudioBtn'),
  statusBox:         $('statusBox'),
  pulsePreview:      $('pulsePreview'),
  lyricsPreview:     $('lyricsPreview'),
  musicPreview:      $('musicPreview'),
  fileLinks:         $('fileLinks'),
  durationBadge:     $('durationBadge'),
  cfgUse:            $('cfgUse'),
  cfgGenre:          $('cfgGenre'),
  cfgProject:        $('cfgProject'),
  audioPlayer:       $('audioPlayer'),
  playLocalBtn:      $('playLocalBtn'),
  publishMorningBtn: $('publishMorningBtn'),
  downloadAudioLink: $('downloadAudioLink'),
  alarmSlotDirInput: $('alarmSlotDirInput'),
  audioMeta:         $('audioMeta'),
  audioCanvas:       $('audioCanvas'),
  heroCanvas:        $('heroCanvas'),
};

/* ─── BOOTSTRAP ─────────────────────────────── */
async function bootstrap() {
  try {
    const res = await fetch('/api/bootstrap');
    const data = await res.json();
    Object.assign(state, {
      use:              data.defaults.use || 'celebrate',
      genre:            data.defaults.genre || 'rap',
      focus:            FOCUS_FOR_USE[data.defaults.use || 'celebrate'] || data.defaults.focus || '',
      duration_seconds: data.defaults.duration_seconds || 45,
      music_model:      data.defaults.music_model || '',
      audioAvailable:   Boolean(data.audio_generation?.available),
      genres:           data.genres || [],
      uses:             data.uses || Object.keys(USE_META),
      durations:        data.durations || [30, 45, 60, 90],
      sourceModes:      data.source_modes || state.sourceModes,
    });

    if (data.llm_models || data.llm_providers) {
      const configuredLlm = data.defaults?.configured_llm_provider || 'auto';
      const configuredModel = data.defaults?.configured_llm_model || '';
      const activeLlm = data.defaults?.active_llm_provider;
      const activeModel = data.defaults?.active_llm_model;
      const usingAuto = !configuredLlm || ['auto', 'default', 'byok'].includes(configuredLlm);
      const selectedProvider = usingAuto ? activeLlm : configuredLlm;
      const selectedModel = usingAuto ? activeModel : configuredModel;
      const llmRows = data.llm_models || data.llm_providers;
      els.llmSelect.innerHTML = '';
      const autoOpt = document.createElement('option');
      autoOpt.value = '';
      autoOpt.textContent = `Auto-detect / template fallback${activeLlm && activeLlm !== 'template' ? ` (currently ${capitalize(activeLlm)} ${activeModel})` : ''}`;
      autoOpt.selected = usingAuto || !activeLlm || activeLlm === 'template';
      els.llmSelect.appendChild(autoOpt);
      llmRows.forEach(p => {
        const opt = document.createElement('option');
        opt.value = JSON.stringify({ provider: p.provider, model: p.model });
        const runtimeSupported = p.runtime_supported !== false;
        const status = !runtimeSupported ? ' - Not supported yet' : (!p.available ? ' - Missing API key' : '');
        const profile = p.profile ? ` · ${p.profile}` : '';
        opt.textContent = `${p.label || capitalize(p.provider)} (${p.model})${profile}${status}`;
        opt.disabled = !p.available || !runtimeSupported;
        if (!usingAuto && p.provider === selectedProvider && p.model === selectedModel) {
          opt.selected = true;
        }
        els.llmSelect.appendChild(opt);
      });
    }

    if (data.music_providers) {
      els.modelSelect.innerHTML = '';
      data.music_providers.forEach(p => {
        const opt = document.createElement('option');
        opt.value = JSON.stringify({provider: p.provider, model: p.model});
        const runtimeSupported = p.runtime_supported !== false;
        const status = !runtimeSupported ? ' - Not supported yet' : (!p.available ? ' - Missing API key' : '');
        opt.textContent = `${capitalize(p.provider)} (${p.model})${status}`;
        opt.disabled = !p.available || !runtimeSupported;
        if (p.available && runtimeSupported && (state.music_model === p.model || (data.audio_generation && p.provider === data.audio_generation.provider && p.model === data.audio_generation.model))) {
          opt.selected = true;
        }
        els.modelSelect.appendChild(opt);
      });
      // Add a fallback Lyria Clip option manually if Google is available but not listing clip explicitly
      const hasGoogle = data.music_providers.find(p => p.provider === 'google');
      if (hasGoogle && !data.music_providers.find(p => p.model === 'models/lyria-3-clip-preview')) {
        const opt = document.createElement('option');
        opt.value = JSON.stringify({provider: 'google', model: 'models/lyria-3-clip-preview'});
        opt.textContent = `Google (models/lyria-3-clip-preview)${!hasGoogle.available ? ' - Missing API Key' : ''}`;
        opt.disabled = !hasGoogle.available;
        els.modelSelect.appendChild(opt);
      }
    }

    // Provider badge
    const badge = els.providerBadge;
    if (data.audio_generation?.available) {
      badge.textContent = `♪ ${data.audio_generation.provider} ready`;
      badge.classList.add('ready');
    } else if (data.audio_generation?.provider && data.audio_generation.provider !== 'unconfigured') {
      badge.textContent = `${data.audio_generation.provider} (no audio)`;
      badge.classList.add('partial');
    } else {
      badge.textContent = 'Template mode';
    }

    renderAll();
    updateAudioState();
  } catch (err) {
    els.providerBadge.textContent = 'Offline';
    setStatus('Could not reach the server. Is the web app running?', 'error');
  }
}

/* ─── RENDER ────────────────────────────────── */
function renderAll() {
  renderUses();
  renderGenres();
  renderDurations();
  updateConfig();
}

function renderUses() {
  els.useList.innerHTML = '';
  state.uses.forEach((use) => {
    const meta = USE_META[use] || { icon: '🎵', label: capitalize(use), desc: '' };
    const card = document.createElement('button');
    card.className = `use-card${state.use === use ? ' active' : ''}`;
    card.innerHTML = `
      <span class="use-card__icon">${meta.icon}</span>
      <span class="use-card__name">${meta.label}</span>
      <span class="use-card__desc">${meta.desc}</span>`;
    card.onclick = () => {
      state.use = use;
      state.genre = GENRE_FOR_USE[use] || 'rap';
      syncFocusToUse();
      renderUses();
      renderGenres();
      updateConfig();
    };
    els.useList.appendChild(card);
  });
}



function renderGenres() {
  els.genreList.innerHTML = '';
  state.genres.forEach((g) => {
    const chip = document.createElement('button');
    chip.className = `genre-chip${state.genre === g.key ? ' active' : ''}`;
    chip.innerHTML = `<span class="genre-chip__name">${g.label}</span><span class="genre-chip__desc">${GENRE_DESC[g.key] || ''}</span>`;
    chip.onclick = () => {
      state.genre = g.key;
      renderGenres();
      updateConfig();
    };
    els.genreList.appendChild(chip);
  });
}

function renderDurations() {
  els.durationList.innerHTML = '';
  state.durations.forEach((d) => {
    const btn = document.createElement('button');
    btn.className = `duration-btn${state.duration_seconds === d ? ' active' : ''}`;
    btn.textContent = `${d}s`;
    btn.onclick = () => {
      state.duration_seconds = d;
      renderDurations();
      els.durationBadge.textContent = `${d}s`;
      updateConfig();
    };
    els.durationList.appendChild(btn);
  });
  els.durationBadge.textContent = `${state.duration_seconds}s`;
}



function updateConfig() {
  const genreLabel = (state.genres.find((g) => g.key === state.genre) || {}).label || capitalize(state.genre);
  els.cfgUse.textContent = capitalize(state.use);
  els.cfgGenre.textContent = genreLabel;
  els.cfgProject.textContent = (els.projectInput?.value || '').trim() || 'Any recent work';
}

function updateAudioState() {
  els.generateAudioBtn.disabled = !state.audioAvailable;
  if (!state.audioAvailable) {
    els.audioMeta.textContent = 'Audio generation is not configured. Text artifacts still work.';
  }
}

/* ─── STATUS ────────────────────────────────── */
function setStatus(text, type = '') {
  els.statusBox.textContent = text;
  els.statusBox.className = `status-bar${type ? ` ${type}` : ''}`;
}

function setLoading(btn, loading) {
  btn.classList.toggle('loading', loading);
  btn.disabled = loading;
}

/* ─── GENERATE ──────────────────────────────── */
async function generate() {
  let llmProvider;
  let llmModel;
  try {
    const parsed = JSON.parse(els.llmSelect.value || '{}');
    llmProvider = parsed.provider;
    llmModel = parsed.model;
  } catch (e) {}
  const payload = {
    use: state.use,
    genre: state.genre,
    duration_seconds: state.duration_seconds,
    focus: state.focus || '',
    sound_reference: (els.artistInput.value || '').trim(),
    source_mode: 'auto',
    project: (els.projectInput?.value || '').trim(),
    llm_provider: llmProvider,
    llm_model: llmModel,
  };
  setStatus('Generating…');
  setLoading(els.generateBtn, true);
  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || data.error || 'Generation failed');
    els.pulsePreview.textContent = data.pulse;
    els.pulsePreview.classList.add('has-content');
    els.lyricsPreview.textContent = data.lyrics;
    els.lyricsPreview.classList.add('has-content');
    state.lastMusicPrompt = data.music_prompt;
    els.musicPreview.textContent = data.music_prompt;
    els.musicPreview.classList.add('has-content');
    renderFileLinks();
    setStatus(`Done — your ${state.duration_seconds}s ${state.use.replace(/_/g, ' ')} draft is ready.`, 'success');
    els.audioMeta.textContent = state.audioAvailable
      ? 'Draft ready. Hit "Generate audio" for the actual track.'
      : 'Draft ready. Audio generation is not configured.';
    // Scroll to preview on mobile
    if (window.innerWidth <= 1100) {
      document.getElementById('previewPane')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  } catch (err) {
    setStatus(`Error: ${err.message}`, 'error');
  } finally {
    setLoading(els.generateBtn, false);
  }
}

async function generateAudio() {
  if (!state.lastMusicPrompt) {
    setStatus('Generate the draft first so there is something to score.', 'error');
    return;
  }
  setStatus('Generating audio… this can take a moment.');
  setLoading(els.generateAudioBtn, true);
  try {
    let selProvider = state.music_provider;
    let selModel = state.music_model;
    try {
      const parsed = JSON.parse(els.modelSelect.value);
      selProvider = parsed.provider;
      selModel = parsed.model;
    } catch(e) {}

    const res = await fetch('/api/generate-audio', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        music_prompt: state.lastMusicPrompt,
        duration_seconds: state.duration_seconds,
        music_provider: selProvider,
        music_model: selModel,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || data.error || 'Audio generation failed');
    const audioUrl = `${data.audio_url}&v=${Date.now()}`;
    els.audioPlayer.src = audioUrl;
    els.audioPlayer.classList.add('visible');
    els.playLocalBtn.disabled = false;
    els.publishMorningBtn.disabled = false;
    els.downloadAudioLink.setAttribute('aria-disabled', 'false');
    els.audioMeta.textContent = `Audio ready via ${data.provider} (${data.model}).`;
    renderFileLinks(true);
    setStatus(`Done — your ${state.duration_seconds}s track is playing.`, 'success');
    els.audioPlayer.play().catch(() => {});
  } catch (err) {
    setStatus(`Audio error: ${err.message}`, 'error');
    els.audioMeta.textContent = 'Audio generation failed.';
  } finally {
    setLoading(els.generateAudioBtn, false);
    els.generateAudioBtn.disabled = !state.audioAvailable;
  }
}

/* ─── ONE-CLICK HERO FLOW ───────────────────── */
function syncFocusToUse() {
  state.focus = FOCUS_FOR_USE[state.use] || '';
}

async function publishMorningAlarm() {
  const targetDir = (els.alarmSlotDirInput?.value || '').trim();
  if (targetDir) localStorage.setItem('s2sAlarmSlotDir', targetDir);
  setStatus('Updating S2S-morning.mp3…');
  els.publishMorningBtn.disabled = true;
  try {
    const res = await fetch('/api/alarm-slot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'audio', slot: 'morning', target_dir: targetDir || undefined }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || 'Alarm slot update failed');
    setStatus('Updated phone alarm slot: S2S-morning.mp3', 'success');
    els.audioMeta.textContent = `Updated ${data.target_path}. Android Clock should keep using that stable file.`;
  } catch (err) {
    setStatus(`Alarm slot error: ${err.message}`, 'error');
    els.audioMeta.textContent = 'Could not update the Drive alarm slot. Paste the local Drive alarm folder path and try again.';
  } finally {
    els.publishMorningBtn.disabled = false;
  }
}

async function playLocalAudio() {
  setStatus('Starting playback on this computer…');
  els.playLocalBtn.disabled = true;
  try {
    const res = await fetch('/api/play-audio', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'audio', backend: 'auto', volume: 100, block: false }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || 'Playback failed');
    setStatus(`Playing locally via ${data.backend}.`, 'success');
    els.audioMeta.textContent = `Playing on this computer via ${data.backend}. If BOT63 is the current output, it should hit the speakers.`;
  } catch (err) {
    setStatus(`Playback error: ${err.message}`, 'error');
    els.audioMeta.textContent = 'Local playback failed. The browser player still works for preview.';
  } finally {
    els.playLocalBtn.disabled = false;
  }
}

async function resolveSource() {
  const params = new URLSearchParams({ mode: state.source_mode || 'auto' });
  const project = (els.projectInput?.value || '').trim();
  if (project) params.set('project', project);
  const res = await fetch(`/api/sources/resolve?${params.toString()}`);
  const data = await res.json().catch(() => ({}));
  state.resolvedSource = res.ok ? data.source : null;
}

async function heroGenerate() {
  // Make sure the customize section is visible first
  els.mainLayout.style.display = '';
  setLoading(els.heroGenerateBtn, true);
  els.heroGenerateBtn.querySelector('.btn__label').textContent = 'Finding session…';

  // Use alarm as the default one-click use (most natural for "make my last session a song")
  state.use = 'alarm';
  state.genre = GENRE_FOR_USE['alarm'] || 'rap';
  state.source_mode = 'auto';
  syncFocusToUse();
  renderAll();

  // Resolve source
  await resolveSource();
  if (!state.resolvedSource) {
    els.heroGenerateBtn.querySelector('.btn__label').textContent = 'Make it a song';
    setLoading(els.heroGenerateBtn, false);
    setStatus('No recent session found. Use the CLI with an input file, or run this inside an OpenClaw workspace with recent sessions.', 'error');
    return;
  }

  els.heroGenerateBtn.querySelector('.btn__label').textContent = 'Generating…';
  await generate();

  // If audio is available, generate that too
  if (state.audioAvailable && state.lastMusicPrompt) {
    els.heroGenerateBtn.querySelector('.btn__label').textContent = 'Creating audio…';
    await generateAudio();
  }

  els.heroGenerateBtn.querySelector('.btn__label').textContent = '▶ Make it a song';
  setLoading(els.heroGenerateBtn, false);
}

/* ─── FILE LINKS ────────────────────────────── */
function renderFileLinks(includeAudio = false) {
  const files = [
    ['pulse', 'pulse.txt'],
    ['lyrics', 'lyrics.txt'],
    ['music_prompt', 'music_prompt.txt'],
    ['manifest', 'run_manifest.json'],
  ];
  if (includeAudio) files.push(['audio', 'audio.mp3']);
  els.fileLinks.innerHTML = files
    .map(([name, label]) => `<a href="/api/files?name=${name}" target="_blank" rel="noreferrer">${label}</a>`)
    .join('');
}

/* ─── COPY BUTTONS ──────────────────────────── */
document.querySelectorAll('.copy-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    const target = document.getElementById(btn.dataset.target);
    if (!target) return;
    navigator.clipboard.writeText(target.textContent).then(() => {
      btn.classList.add('copied');
      btn.textContent = '✓';
      setTimeout(() => { btn.classList.remove('copied'); btn.textContent = '⎘'; }, 1500);
    });
  });
});

/* ─── HERO CANVAS WAVEFORM ──────────────────── */
function initHeroViz() {
  const canvas = els.heroCanvas;
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width;
  const h = canvas.height;
  const bars = 32;
  const gap = 3;
  const barW = (w - (bars - 1) * gap) / bars;

  function draw(time) {
    ctx.clearRect(0, 0, w, h);
    for (let i = 0; i < bars; i++) {
      const t = time * 0.002 + i * 0.3;
      const amp = 0.3 + 0.7 * (Math.sin(t) * 0.5 + 0.5) * (Math.cos(t * 0.7) * 0.5 + 0.5);
      const barH = amp * h * 0.8;
      const x = i * (barW + gap);
      const y = (h - barH) / 2;
      const grad = ctx.createLinearGradient(0, y, 0, y + barH);
      grad.addColorStop(0, 'rgba(167, 139, 250, 0.6)');
      grad.addColorStop(1, 'rgba(56, 189, 248, 0.3)');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.roundRect(x, y, barW, barH, 2);
      ctx.fill();
    }
    requestAnimationFrame(draw);
  }
  requestAnimationFrame(draw);
}

/* ─── AUDIO CANVAS WAVEFORM ─────────────────── */
function initAudioViz() {
  const canvas = els.audioCanvas;
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width;
  const h = canvas.height;
  const bars = 48;

  function draw(time) {
    ctx.clearRect(0, 0, w, h);
    const barW = w / bars;
    for (let i = 0; i < bars; i++) {
      const t = time * 0.003 + i * 0.15;
      const amp = 0.15 + 0.85 * Math.abs(Math.sin(t)) * Math.abs(Math.cos(t * 0.4 + i * 0.1));
      const barH = amp * h * 0.75;
      const x = i * barW;
      const y = (h - barH) / 2;
      ctx.fillStyle = `rgba(56, 189, 248, ${0.2 + amp * 0.35})`;
      ctx.fillRect(x + 1, y, barW - 2, barH);
    }
    requestAnimationFrame(draw);
  }
  requestAnimationFrame(draw);
}

/* ─── UTIL ──────────────────────────────────── */
function capitalize(s) {
  return s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, ' ');
}

/* ─── EVENT WIRING ──────────────────────────── */
els.heroGenerateBtn.addEventListener('click', heroGenerate);
els.heroCustomizeBtn.addEventListener('click', () => {
  els.mainLayout.style.display = '';
  els.mainLayout.scrollIntoView({ behavior: 'smooth', block: 'start' });
});
els.generateBtn.addEventListener('click', generate);
els.generateAudioBtn.addEventListener('click', generateAudio);
els.playLocalBtn.addEventListener('click', playLocalAudio);
els.publishMorningBtn.addEventListener('click', publishMorningAlarm);
els.modelSelect.addEventListener('change', () => {});
els.projectInput.addEventListener('input', () => {
  state.lastMusicPrompt = null;
  updateConfig();
});
els.artistInput.addEventListener('input', () => {
  state.lastMusicPrompt = null;
  els.pulsePreview.textContent = '';
  els.lyricsPreview.textContent = '';
  els.musicPreview.textContent = '';
  els.pulsePreview.classList.remove('has-content');
  els.lyricsPreview.classList.remove('has-content');
  els.musicPreview.classList.remove('has-content');
  updateAudioState();
});


/* ─── INIT ──────────────────────────────────── */
initHeroViz();
initAudioViz();
if (els.alarmSlotDirInput) {
  els.alarmSlotDirInput.value = localStorage.getItem('s2sAlarmSlotDir') || '';
  els.alarmSlotDirInput.addEventListener('input', () => localStorage.setItem('s2sAlarmSlotDir', els.alarmSlotDirInput.value.trim()));
}
bootstrap();
