// Onglet Discover de l'Atelier. Aucune chaîne venue d'un podcast n'est injectée comme HTML (textContent seulement).
import { openReview, reviews } from './discover_review.js';

const $ = (id) => document.getElementById(id);

// Étapes affichées, dans l'ordre réel de la préparation (discover_source puis discover_preparation).
const STEPS = [
  ['download', 'Téléchargement', ['download']],
  ['normalize', 'Audio', ['normalize']],
  ['transcribe', 'Transcription', ['transcribe', 'source_ready']],
  ['plan', 'Plan', ['plan']],
  ['extract', 'Extraction', ['extract']],
  ['adapt', 'Écriture', ['adapt', 'translate']],
  ['evaluate', 'Contrôle', ['evaluate', 'review']],
  ['tts', 'Audio anglais', ['tts']],
  ['publish', 'Publication', ['publish']],
];
const STAGE_TEXT = {
  download: 'Téléchargement de l’épisode', normalize: 'Préparation de l’audio', transcribe: 'Transcription (MacWhisper ou transcription de l’émission)',
  source_ready: 'Source prête', plan: 'Plan de l’épisode (Gemini)', extract: 'Extraction des faits et arguments (Gemini)',
  adapt: 'Écriture de la version anglaise (Gemini)', translate: 'Traduction fidèle (Gemini)', evaluate: 'Contrôle de fidélité',
  review: 'En attente de relecture (mode manuel)', tts: 'Création de l’audio anglais (Deepgram ou Heart)', publish: 'Publication dans Discover',
};
const COVERAGE = { full: 'Intégral', condensed: 'Condensé', essentials: 'L’essentiel' };
const KINDS = { episode: 'Podcast', youtube: 'YouTube', reflection: 'Texte · My Mind' };
// Un texte n'a ni téléchargement ni audio source : ses étapes commencent au découpage.
const stepsFor = (kind) => (kind === 'reflection' ? STEPS.filter(([key]) => !['download', 'normalize'].includes(key)) : STEPS);
const LEVELS = ['A2', 'B1', 'B2', 'C1', 'original'];

let categories = {};
let queueByRef = new Map();
let items = [];
let episodes = [];
let cursor = null;
let openPrep = null; // épisode dont le panneau de préparation est ouvert
let lastQueueSignature = '';
let lastEngineMessage = ''; // un message d'erreur n'est affiché qu'une fois (on peut le fermer)

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function api(path, body) {
  const options = body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Discover-Atelier': '1' }, body: JSON.stringify(body),
  };
  let response;
  try {
    response = await fetch('/api/discover/' + path, options);
  } catch {
    throw new Error('L’Atelier ne répond plus : vérifier que la fenêtre Terminal de l’Atelier est toujours ouverte.');
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.erreur || 'Action impossible.');
  return data;
}

/** Bandeau d'alerte : un titre, une explication et éventuellement une action. */
function banner(kind, title, detail, action) {
  const box = $('banner');
  box.replaceChildren();
  if (!title) { box.className = ''; return; }
  const alert = el('div', null, 'alert ' + kind);
  const text = el('div', null, 'grow');
  text.append(el('strong', title));
  if (detail) text.append(el('span', detail));
  alert.append(text);
  if (action) {
    const b = el('button', action.label);
    b.onclick = action.run;
    alert.append(b);
  }
  const close = el('button', '×', 'link');
  close.setAttribute('aria-label', 'Fermer');
  close.onclick = () => banner();
  alert.append(close);
  box.append(alert);
  box.className = 'show';
}

const durationText = (sec) => (sec ? (sec >= 3600 ? `${Math.floor(sec / 3600)} h ${String(Math.round(sec % 3600 / 60)).padStart(2, '0')}` : `${Math.round(sec / 60)} min`) : '');
const dateText = (iso) => (iso ? new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'short' }).format(new Date(iso)) : '');
const optionsText = (o) => `${COVERAGE[o.coverage]} · ${o.level === 'original' ? 'anglais non simplifié' : o.level}${o.targetMinutes ? ` · ${o.targetMinutes} min` : ''}${o.faithful ? ' · + fidèle' : ''}`;

/** État d'un épisode, d'après sa dernière demande et sa publication. */
function episodeStatus(ep) {
  const item = queueByRef.get(ep.id);
  if (item && item.status === 'leased') return ['run', 'En préparation · ' + (STEPS.find((s) => s[2].includes(item.stage))?.[1] || '…')];
  if (item && item.status === 'pending') return ['wait', item.stage === 'review' ? 'À relire' : 'En file'];
  if (item && item.status === 'failed') return ['fail', 'Échec'];
  if (ep.contentId) return ['done', 'Publié'];
  return null;
}

// ── Préparateur (consommateur local) ─────────────────────────────────────────
function renderEngine(state) {
  $('engine').className = 'card' + (state.running ? ' running' : '');
  const current = state.item;
  $('engine-state').textContent = !state.running ? 'Préparateur arrêté'
    : current ? `Prépare : ${current.title || 'épisode'}` : 'Préparateur prêt';
  $('engine-msg').textContent = current ? (STAGE_TEXT[state.stage] || state.message || '') : (state.message || (state.running
    ? 'En attente : choisis un épisode dans l’onglet Podcasts, ou depuis l’app.' : 'Démarre-le pour traiter les préparations sur ce Mac.'));
  // Gemini bloqué (quota, panne…) : l'Atelier prépare avec OpenAI en attendant.
  const ai = $('engine-ai');
  ai.hidden = !state.ai;
  ai.textContent = state.ai || '';
  $('start').disabled = state.running;
  $('stop').disabled = !state.running;
  // Une erreur locale (Gemini, Kokoro, MacWhisper, réseau) remonte ici avec son détail.
  if (state.message && state.message !== lastEngineMessage && /interrompue|impossible|Quota|Connexion/i.test(state.message)) {
    lastEngineMessage = state.message;
    const quota = /Quota/i.test(state.message);
    banner(quota ? 'warn' : 'error', quota ? 'Quota IA atteint (Gemini et OpenAI)' : 'La dernière préparation s’est interrompue', state.message,
      quota ? null : { label: 'Voir les préparations', run: () => selectTab('queue') });
  }
}

// ── Réglages d'une préparation (épisode, vidéo, texte) ───────────────────────
/** Éditeur couverture / niveau / durée / fidèle ; `value()` rend les options à envoyer. */
function optionsEditor({ long = false, faithfulAllowed = false } = {}) {
  const opts = { coverage: long ? 'condensed' : 'full', level: 'B1', targetMinutes: long ? 12 : null, faithful: false };
  const box = el('div');
  box.style.display = 'grid';
  box.style.gap = '10px';
  const seg = (label, values, key, names) => {
    const wrap = el('div', null, 'row');
    wrap.append(el('label', label));
    const group = el('div', null, 'seg');
    group.setAttribute('role', 'radiogroup');
    for (const v of values) {
      const b = el('button', names ? names[v] : v);
      b.type = 'button';
      b.setAttribute('role', 'radio');
      b.setAttribute('aria-checked', String(opts[key] === v));
      b.onclick = () => {
        opts[key] = v;
        if (key === 'coverage') opts.targetMinutes = v === 'condensed' ? 12 : v === 'essentials' ? 4 : null;
        render();
      };
      group.append(b);
    }
    wrap.append(group);
    return wrap;
  };
  const render = () => {
    box.replaceChildren();
    box.append(seg('Couverture', ['full', 'condensed', 'essentials'], 'coverage', COVERAGE));
    box.append(seg('Niveau', LEVELS, 'level', { A2: 'A2', B1: 'B1', B2: 'B2', C1: 'C1', original: 'Non simplifié' }));
    const row = el('div', null, 'row');
    if (opts.coverage !== 'full') {
      const [min, max] = opts.coverage === 'condensed' ? [8, 20] : [3, 6];
      row.append(el('label', 'Durée cible'));
      const input = el('input');
      Object.assign(input, { type: 'number', min, max, value: opts.targetMinutes });
      input.style.width = '80px';
      input.oninput = () => { opts.targetMinutes = Math.max(min, Math.min(max, Number(input.value) || min)); };
      row.append(input, el('span', `min (${min} à ${max})`, 'small muted'));
    }
    if (faithfulAllowed) {
      const label = el('label');
      const check = el('input');
      check.type = 'checkbox';
      check.checked = opts.faithful;
      check.onchange = () => { opts.faithful = check.checked; };
      label.append(check, document.createTextNode(' Ajouter la traduction fidèle intégrale (source en français)'));
      row.append(label);
    }
    if (row.childElementCount) box.append(row);
  };
  render();
  return {
    element: box,
    value: () => {
      const body = { coverage: opts.coverage, level: opts.level, faithful: opts.faithful };
      if (opts.coverage !== 'full') body.targetMinutes = opts.targetMinutes;
      return body;
    },
    coverage: () => opts.coverage,
  };
}

// ── Podcasts ─────────────────────────────────────────────────────────────────
function prepPanel(ep) {
  const long = (ep.durationSec || 0) > 25 * 60;
  const editor = optionsEditor({ long, faithfulAllowed: ep.language === 'fr' });
  const box = el('div', null, 'prep');
  box.append(editor.element);
  const hint = el('p', '', 'small muted');
  const updateHint = () => {
    hint.textContent = long && editor.coverage() === 'full'
      ? 'Épisode long : l’intégral demandera beaucoup de temps de traduction et d’audio. Le condensé est conseillé.'
      : 'La préparation démarre aussitôt sur ce Mac et se publie automatiquement dans l’app.';
  };
  editor.element.addEventListener('click', updateHint);
  updateHint();
  box.append(hint);
  const actions = el('div', null, 'actions');
  const go = el('button', 'Lancer la préparation', 'primary');
  go.onclick = async () => {
    go.disabled = true;
    try {
      await api('prepare', { episodeId: ep.id, options: editor.value() });
      openPrep = null;
      banner('ok', 'Préparation lancée', `« ${ep.title} » — suis son avancement dans l’onglet Préparations.`, { label: 'Voir', run: () => selectTab('queue') });
      await refreshQueue(true);
    } catch (error) {
      banner('error', 'Préparation refusée', error.message);
      go.disabled = false;
    }
  };
  const cancel = el('button', 'Fermer');
  cancel.onclick = () => { openPrep = null; renderEpisodes(); };
  actions.append(go, cancel);
  if (ep.contentId) {
    // L'épisode a déjà des versions dans l'app : on peut les supprimer d'ici.
    const del = el('button', 'Supprimer la version publiée', 'danger');
    del.onclick = async () => {
      if (!confirm(`Supprimer les versions préparées de « ${ep.title} » ?\n\nElles disparaissent de l’app (audio et transcription) et de ce Mac. L’épisode reste.`)) return;
      del.disabled = true;
      try {
        await api('delete-content', { contentId: ep.contentId, kind: 'episode', ref: ep.id });
        ep.contentId = null;
        openPrep = null;
        banner('ok', 'Version supprimée', `« ${ep.title} » n’a plus de version préparée dans l’app.`);
        renderEpisodes();
        await refreshQueue(true);
      } catch (error) {
        banner('error', 'Impossible de supprimer', error.message);
        del.disabled = false;
      }
    };
    actions.append(del);
  }
  box.append(actions);
  return box;
}

function renderEpisodes() {
  const q = $('q').value.trim().toLowerCase();
  const list = episodes.filter((e) => !q || `${e.title} ${e.showTitle}`.toLowerCase().includes(q));
  const nodes = list.map((ep) => {
    const card = el('article', null, 'card episode');
    if (ep.imageUrl) {
      const img = el('img');
      img.alt = '';
      img.loading = 'lazy';
      img.src = ep.imageUrl.replace(/^http:/, 'https:');
      card.append(img);
    } else card.append(el('div', null, 'ph'));
    const body = el('div');
    body.append(el('div', ep.showTitle, 'show'), el('div', ep.title, 'title'));
    const meta = el('div', null, 'meta');
    meta.append(el('span', [dateText(ep.publishedAt), durationText(ep.durationSec), ep.language === 'fr' ? 'Français' : 'Anglais', categories[ep.category]].filter(Boolean).join(' · ')));
    if (ep.transcriptType) meta.append(el('span', '· transcription fournie'));
    const status = episodeStatus(ep);
    if (status) meta.append(el('span', status[1], 'pill ' + status[0]));
    body.append(meta);
    card.append(body);
    const item = queueByRef.get(ep.id);
    const busy = item && (item.status === 'pending' || item.status === 'leased');
    const btn = el('button', ep.contentId ? 'Autre version' : 'Préparer', busy ? '' : 'primary');
    btn.disabled = busy;
    btn.title = busy ? 'Une préparation est déjà en cours pour cet épisode.' : '';
    btn.onclick = () => { openPrep = openPrep === ep.id ? null : ep.id; renderEpisodes(); };
    card.append(btn);
    if (openPrep === ep.id) card.append(prepPanel(ep));
    return card;
  });
  $('episodes').replaceChildren(...(nodes.length ? nodes : [el('p', q ? 'Aucun épisode ne correspond.' : 'Aucun épisode pour ces filtres.', 'empty')]));
  $('more').hidden = !cursor;
}

async function loadEpisodes(append = false) {
  const params = new URLSearchParams();
  for (const id of ['show', 'category', 'lang']) if ($(id).value) params.set(id, $(id).value);
  if (append && cursor) params.set('cursor', cursor);
  try {
    const data = await api('episodes?' + params);
    episodes = append ? [...episodes, ...data.episodes] : data.episodes;
    cursor = data.nextCursor;
    renderEpisodes();
  } catch (error) {
    $('episodes').replaceChildren(el('p', null, 'empty'));
    banner('error', 'Impossible de charger les podcasts', error.message, { label: 'Réessayer', run: () => loadEpisodes() });
  }
}

async function loadShows() {
  try {
    const data = await api('shows');
    categories = { tech: 'Tech', science: 'Sciences', economy: 'Économie', news: 'Actualité', football: 'Football', stories: 'Histoires' };
    for (const c of data.categories || []) if (!categories[c]) categories[c] = c;
    $('category').append(...Object.entries(categories).map(([v, l]) => Object.assign(el('option', l), { value: v })));
    $('show').append(...data.shows.filter((s) => s.enabled).map((s) => Object.assign(el('option', s.title), { value: s.id })));
  } catch { /* le bandeau des épisodes signalera l'erreur */ }
}

// ── Préparations ─────────────────────────────────────────────────────────────
function steps(item) {
  const wrap = el('div', null, 'steps');
  const list = stepsFor(item.kind);
  const index = list.findIndex((s) => s[2].includes(item.stage));
  list.forEach(([key, label], i) => {
    if (key === 'transcribe' && item.kind === 'reflection') label = 'Découpage';
    const done = item.status === 'done' || (index >= 0 && i < index);
    const now = item.status === 'leased' && i === index;
    const fail = item.status === 'failed' && (index >= 0 ? i === index : i === 0);
    const step = el('div', null, 'step' + (done ? ' done' : now ? ' now' : fail ? ' fail' : ''));
    step.append(el('div', null, 'bar'), el('div', label, 'lbl'));
    wrap.append(step);
  });
  return wrap;
}

function renderQueue() {
  const shown = items.filter((i) => i.status !== 'cancelled').slice(0, 40);
  const active = shown.filter((i) => i.status === 'pending' || i.status === 'leased').length;
  $('count-queue').hidden = !active;
  $('count-queue').textContent = active;
  const nodes = shown.map((item) => {
    const card = el('article', null, 'card');
    const head = el('div', null, 'row');
    head.style.justifyContent = 'space-between';
    const title = el('div');
    const kind = el('div', null, 'meta');
    kind.append(el('span', KINDS[item.kind] || item.kind, 'pill kind'), el('span', optionsText(item.options)));
    title.append(el('h3', item.title), kind);
    const [cls, text] = item.status === 'done' ? ['done', 'Publié dans l’app'] : item.status === 'failed' ? ['fail', 'Échec']
      : item.status === 'leased' ? ['run', 'En cours'] : ['wait', item.stage === 'review' ? 'À relire' : 'En file'];
    head.append(title, el('span', text, 'pill ' + cls));
    card.append(head);
    if (item.status !== 'done') card.append(steps(item));
    if (item.status === 'leased') card.append(el('p', `${STAGE_TEXT[item.stage] || 'Préparation'} · tentative ${item.attempts}/${item.maxAttempts}`, 'small muted'));
    if (item.status === 'pending' && item.stage !== 'review') card.append(el('p', 'En attente du préparateur de ce Mac.', 'small muted'));
    if (item.status === 'failed') {
      const box = el('div', null, 'alert error');
      const t = el('div', null, 'grow');
      t.append(el('strong', 'Ce qui s’est passé'), el('span', item.error || 'Préparation interrompue.'));
      t.append(el('p', 'Les étapes déjà faites sont conservées : réessayer reprend où ça s’est arrêté. Si l’erreur revient, regarde le message du préparateur en haut de page (Gemini, Kokoro, MacWhisper ou réseau).', 'small'));
      box.append(t);
      card.append(box);
    }
    if (item.status === 'done') card.append(el('p', `Terminé le ${new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(item.updatedAt))}.`, 'small muted'));
    const actions = el('div', null, 'actions');
    if (item.status === 'failed') {
      const b = el('button', 'Réessayer', 'primary');
      b.onclick = () => act('retry', item, b);
      actions.append(b);
    }
    if (item.status === 'pending' || item.status === 'leased') {
      const b = el('button', 'Annuler', 'danger');
      b.onclick = () => act('cancel', item, b);
      actions.append(b);
    }
    if (item.status === 'done' && item.contentId) {
      const b = el('button', 'Supprimer la version publiée', 'danger');
      b.onclick = () => {
        if (!confirm(`Supprimer les versions préparées de « ${item.title} » ?\n\nElles disparaissent de l’app (audio et transcription) et de ce Mac. L’épisode ou la note d’origine restent.`)) return;
        act('delete-content', item, b, { contentId: item.contentId, kind: item.kind, ref: item.ref });
      };
      actions.append(b);
    }
    if (item.status === 'done' || item.status === 'failed') {
      const b = el('button', 'Retirer de la liste');
      b.title = item.status === 'done' ? 'La version reste dans l’app ; seule la ligne disparaît d’ici.' : 'Efface cette demande en échec.';
      b.onclick = () => act('remove', item, b);
      actions.append(b);
    }
    if (actions.childElementCount) card.append(actions);
    return card;
  });
  $('items').replaceChildren(...(nodes.length ? nodes : [el('p', 'Aucune préparation. Choisis un épisode dans l’onglet Podcasts.', 'empty')]));
}

const ACT_ERRORS = { retry: 'Impossible de relancer', cancel: 'Impossible d’annuler', remove: 'Impossible de retirer', 'delete-content': 'Impossible de supprimer' };
async function act(action, item, button, body) {
  button.disabled = true;
  try {
    await api(action, body || { id: item.id });
    if (action === 'delete-content') banner('ok', 'Version supprimée', `« ${item.title} » n’est plus dans l’app.`);
    await refreshQueue(true);
  } catch (error) {
    banner('error', ACT_ERRORS[action], error.message);
    button.disabled = false;
  }
}

let busy = false;
async function refreshQueue(force = false) {
  if (busy) return;
  if (force) lastQueueSignature = '';
  busy = true;
  try {
    const data = await api('queue');
    items = data.items;
    queueByRef = new Map();
    for (const i of items) if (i.kind === 'episode' && !queueByRef.has(i.ref)) queueByRef.set(i.ref, i);
    renderEngine(data.state);
    // On ne redessine que si un état a changé : la liste garde ainsi le focus et le panneau ouvert.
    const signature = JSON.stringify(items.map((i) => [i.id, i.status, i.stage, i.attempts, i.error]));
    if (signature !== lastQueueSignature) {
      lastQueueSignature = signature;
      renderQueue();
      if (episodes.length && !openPrep) renderEpisodes();
    }
  } catch (error) {
    $('engine-state').textContent = 'Discover injoignable';
    $('engine-msg').textContent = error.message;
  } finally {
    busy = false;
  }
}

// ── Onglets et démarrage ─────────────────────────────────────────────────────
function selectTab(name) {
  for (const t of ['podcasts', 'import', 'queue', 'checks']) {
    $('tab-' + t).setAttribute('aria-selected', String(t === name));
    $('panel-' + t).hidden = t !== name;
  }
  if (name === 'checks') void reviews((count) => setChecks(count));
  try { localStorage.setItem('discover.tab', name); } catch { /* facultatif */ }
}
function setChecks(count) {
  $('count-checks').hidden = !count;
  $('count-checks').textContent = count;
}
for (const t of ['podcasts', 'import', 'queue', 'checks']) $('tab-' + t).addEventListener('click', () => selectTab(t));

// ── Importer : vidéo YouTube et texte ────────────────────────────────────────
const ytOptions = optionsEditor();
$('yt-options').append(ytOptions.element);
const txOptions = optionsEditor({ faithfulAllowed: true });
$('tx-options').append(txOptions.element);
async function submitImport(form, body, done) {
  const button = form.querySelector('button[type=submit]');
  button.disabled = true;
  try {
    const { item } = await api('import', body);
    banner('ok', 'Préparation lancée', `« ${item.title} » rejoint la file. L’Atelier s’en occupe tout de suite.`, { label: 'Voir', run: () => selectTab('queue') });
    done();
    await refreshQueue(true);
  } catch (error) {
    banner('error', 'Import refusé', error.message);
  } finally {
    button.disabled = false;
  }
}
$('form-youtube').addEventListener('submit', (e) => {
  e.preventDefault();
  void submitImport($('form-youtube'), { kind: 'youtube', url: $('yt-url').value.trim(), options: ytOptions.value() }, () => { $('yt-url').value = ''; });
});
$('form-text').addEventListener('submit', (e) => {
  e.preventDefault();
  void submitImport($('form-text'), { kind: 'text', title: $('tx-title').value.trim(), text: $('tx-text').value, options: txOptions.value() },
    () => { $('tx-title').value = ''; $('tx-text').value = ''; $('tx-file').value = ''; });
});
$('tx-file').addEventListener('change', async () => {
  const file = $('tx-file').files[0];
  if (!file) return;
  if (file.size > 400_000) { banner('error', 'Fichier trop volumineux', 'Un texte de 100 000 caractères au plus.'); return; }
  $('tx-text').value = await file.text();
  if (!$('tx-title').value) $('tx-title').value = file.name.replace(/\.(txt|md)$/i, '');
});
for (const id of ['show', 'category', 'lang']) $(id).addEventListener('change', () => loadEpisodes());
$('q').addEventListener('input', renderEpisodes);
$('more').addEventListener('click', () => loadEpisodes(true));
for (const action of ['start', 'stop']) {
  $(action).addEventListener('click', async () => {
    $(action).disabled = true;
    try { await api(action, {}); await refreshQueue(); } catch (error) { banner('error', 'Préparateur', error.message); }
  });
}
window.discoverOpenReview = openReview;

let initial = 'podcasts';
try { initial = localStorage.getItem('discover.tab') || 'podcasts'; } catch { /* facultatif */ }
selectTab(initial);
void loadShows();
void loadEpisodes();
void refreshQueue();
void reviews((count) => setChecks(count));
setInterval(refreshQueue, 4000);
setInterval(() => reviews((count) => setChecks(count)), 20000);
