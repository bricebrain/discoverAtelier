// Réglages audio locaux : aucune clé API ne quitte le serveur de l'Atelier.
const $ = (id) => document.getElementById(id);
const money = (n) => Number(n).toLocaleString('fr-FR', {minimumFractionDigits: 2, maximumFractionDigits: 4}) + ' $';
let editing = false;

async function request(body) {
  const response = await fetch('/api/discover/tts', body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json', 'X-Discover-Atelier': '1'}, body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.erreur || 'Réglages audio indisponibles.');
  return data;
}
function controls() {
  const remote = $('tts-provider').value === 'deepgram';
  $('tts-voice').disabled = !remote;
  $('tts-speed').disabled = !remote;
}
function render(data, fill) {
  if (fill) {
    $('tts-provider').value = data.settings.provider;
    $('tts-voice').value = data.settings.voice;
    $('tts-budget').value = data.settings.monthlyLimitUsd;
    $('tts-speed').value = data.settings.speed;
    $('tts-fallback').checked = data.settings.fallback;
  }
  controls();
  $('tts-usage').textContent = `${data.budget.month} : ${money(data.budget.engagedUsd)} engagés / ${money(data.settings.monthlyLimitUsd)} · ${money(data.budget.remainingUsd)} disponibles.`;
  $('tts-key').textContent = data.keyConfigured ? 'Clé Deepgram configurée sur ce Mac.' : 'Clé Deepgram absente : les préparations utilisent Kokoro si le secours est activé.';
  $('tts-uncertain').textContent = data.budget.uncertainRequests
    ? `${data.budget.uncertainRequests} appel(s) sans résultat certain : leur coût reste réservé, sans relance payante automatique.` : '';
  $('tts-plans').replaceChildren(...data.preparations.map((plan) => {
    const row = document.createElement('p'); row.className = 'small';
    row.textContent = `${plan.title || 'Préparation'} — ${plan.provider === 'deepgram' ? 'Deepgram' : 'Kokoro'} · estimation Deepgram : ${money(plan.estimatedUsd)} pour ${plan.newCharacters.toLocaleString('fr-FR')} nouveaux caractères${plan.fallbackReason ? ' · ' + plan.fallbackReason : ''}`;
    return row;
  }));
}
async function refresh(fill = false) {
  try { render(await request(), fill && !editing); }
  catch (error) { $('tts-message').textContent = error.message; }
}
$('tts-form').addEventListener('input', () => { editing = true; controls(); });
$('tts-form').addEventListener('submit', async (event) => {
  event.preventDefault(); $('tts-save').disabled = true;
  try {
    const data = await request({provider: $('tts-provider').value, voice: $('tts-voice').value,
      monthlyLimitUsd: Number($('tts-budget').value), speed: Number($('tts-speed').value), fallback: $('tts-fallback').checked});
    editing = false; render(data, true);
    $('tts-message').textContent = 'Réglages enregistrés pour les prochaines préparations. Les audios existants restent inchangés.';
  } catch (error) { $('tts-message').textContent = error.message; }
  finally { $('tts-save').disabled = false; }
});
void refresh(true);
setInterval(refresh, 5000);
