import {reviews} from './discover_review.js';
const $ = (id) => document.getElementById(id);
const stages = {download:'Téléchargement',normalize:'Préparation audio',transcribe:'Transcription',source_ready:'Source prête',plan:'Plan',extract:'Extraction des sources',evaluate:'Contrôle de fidélité',review:'À relire dans l’Atelier',translate:'Traduction',adapt:'Adaptation',tts:'Création audio',publish:'Publication'};
const coverages = {full:'Intégral',condensed:'Condensé',essentials:'L’essentiel'};
let busy = false;
async function api(path, method = 'GET') {
  const response = await fetch('/api/discover/' + path, {method,headers:method==='POST' ? {'Content-Type':'application/json','X-Discover-Atelier':'1'} : {},body:method==='POST' ? '{}' : undefined});
  const data = await response.json();
  if (!response.ok) throw new Error(data.erreur || 'Discover indisponible.');
  return data;
}
function text(tag, value, className) {
  const element = document.createElement(tag);
  element.textContent = value;
  if (className) element.className = className;
  return element;
}
async function refresh() {
  if (busy) return;
  busy = true;
  try {
    const {items,state} = await api('queue');
    $('error').textContent = '';
    $('running').textContent = state.running ? 'En cours sur ce Mac' : 'Arrêté';
    $('start').disabled = state.running;
    $('stop').disabled = !state.running;
    $('message').textContent = state.message || '';
    const nodes = items.filter((item) => item.status!=='cancelled').map((item) => {
      const card = text('section','','card');
      card.append(text('h2',item.title));
      const options = item.options;
      card.append(text('p',`${coverages[options.coverage]} · ${options.level}${options.targetMinutes ? ` · ${options.targetMinutes} min` : ''}`,'small muted'));
      const label = item.status==='pending' ? (stages[item.stage] || 'En file') : item.status==='leased' ? (stages[item.stage] || 'En préparation') : item.status==='done' ? 'Prêt dans Discover' : 'Échec';
      card.append(text('p',label,'status'));
      if (item.status==='leased') card.append(text('p',`Tentative ${item.attempts}/${item.maxAttempts}`,'small muted'));
      if (item.error && item.status==='failed') card.append(text('p',item.error,'error'));
      return card;
    });
    $('items').replaceChildren(...(nodes.length ? nodes : [text('p','Aucune demande. Choisis « Préparer en anglais » sur un épisode dans Discover.','muted')]));
  } catch (error) {
    $('error').textContent = error.message;
    if ($('items').querySelector('.loading')) $('items').replaceChildren();
  } finally { busy = false; }
}
for (const action of ['start','stop']) $(''+action).addEventListener('click',async () => {
  $(action).disabled = true;
  try { await api(action,'POST'); await refresh(); } catch(error) { $('error').textContent=error.message; }
});
$('refresh').addEventListener('click',()=>{void refresh();void reviews();});
void refresh();
void reviews();
setInterval(refresh,5000);
setInterval(reviews,15000);
