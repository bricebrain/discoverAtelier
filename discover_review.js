// Contrôles de fidélité : versions en attente de relecture (mode manuel) et versions publiées avec des points
// signalés. Aucune chaîne issue d'un podcast n'est injectée comme HTML.
const $ = (id) => document.getElementById(id);
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}
async function request(path, body) {
  const r = await fetch('/api/discover/' + path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Discover-Atelier': '1' }, body: JSON.stringify(body) } : {});
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.erreur || 'Action impossible.');
  return data;
}

function card(item, published) {
  const c = element('article', '', 'card');
  c.style.marginBottom = '10px';
  c.append(element('h3', item.title));
  c.append(element('p', published
    ? (item.verdict === 'rejected' ? 'Publiée automatiquement malgré un rejet du contrôle : à écouter avec un œil critique.' : 'Publiée automatiquement avec des points signalés (chiffres, noms ou nuances à vérifier).')
    : (item.verdict === 'rejected' ? 'À régénérer : le contrôle de fidélité a rejeté cette version.' : 'En attente de ta relecture avant publication (mode manuel).'), 'small muted'));
  const button = element('button', published ? 'Voir le rapport' : 'Lire et vérifier');
  button.onclick = () => openReview(item.id, published);
  c.append(button);
  return c;
}

/** Charge les deux listes ; `onCount` reçoit le nombre d'éléments en attente d'action. */
export async function reviews(onCount) {
  const container = $('reviews');
  try {
    const [pending, flagged] = await Promise.all([request('reviews'), request('flagged')]);
    container.replaceChildren();
    if (pending.reviews.length) {
      container.append(element('h2', 'En attente de relecture'));
      for (const item of pending.reviews) container.append(card(item, false));
    }
    if (flagged.reviews.length) {
      const h = element('h2', 'Publiées avec des points signalés');
      h.style.marginTop = '18px';
      container.append(h);
      for (const item of flagged.reviews) container.append(card(item, true));
    }
    if (!pending.reviews.length && !flagged.reviews.length) container.append(element('p', 'Aucun point signalé par le contrôle de fidélité. 👍', 'empty'));
    onCount?.(pending.reviews.length);
  } catch (error) {
    container.replaceChildren(element('p', error.message, 'error-text'));
  }
}

export async function openReview(id, published = false) {
  const panel = $('review-detail');
  try {
    const review = await request('review?id=' + encodeURIComponent(id));
    panel.replaceChildren();
    panel.hidden = false;
    const close = element('button', 'Fermer le rapport');
    close.onclick = () => { panel.hidden = true; };
    panel.append(close, element('h2', review.title));
    const evaluation = review.prepared.evaluation;
    panel.append(element('p', `Contrôle : ${evaluation.verdict === 'rejected' ? 'rejeté' : evaluation.verdict === 'review' ? 'points à vérifier' : 'ok'} · ${evaluation.wordCount} mots · écoute estimée ${Math.round(evaluation.wordCount / 130)} min${published ? ' · déjà publiée' : ''}`, 'muted'));
    const warnings = [evaluation.coverageWarning, evaluation.tooShortForSubject ? 'La durée demandée est trop courte pour préserver le sujet.' : '', ...(evaluation.language?.warnings || [])].filter(Boolean);
    if (evaluation.durationOutsideTarget) warnings.push(`Durée obtenue : ${evaluation.durationOutsideTarget.actualMinutes} min, cible : ${evaluation.durationOutsideTarget.targetMinutes} min.`);
    for (const [key, label] of [['numbersMissingFromSource', 'Nombre à vérifier'], ['entitiesMissingFromSource', 'Nom à vérifier']]) for (const issue of evaluation[key] || []) warnings.push(`${label} : ${issue.value} (paragraphe ${issue.paragraph}).`);
    for (const judge of [evaluation.judge, evaluation.faithfulJudge].filter(Boolean)) for (const key of ['unsupportedClaims', 'omittedKeyPoints', 'lostNuances', 'promotionsRemaining', 'languageWarnings']) warnings.push(...(judge[key] || []));
    const box = element('div', '', 'warnings');
    box.append(element('h3', warnings.length ? 'Points signalés' : 'Aucun point signalé'));
    for (const warning of [...new Set(warnings)]) box.append(element('p', '• ' + warning, 'error-text'));
    panel.append(box);
    const checks = element('details');
    checks.append(element('summary', 'Détail des contrôles de fidélité'));
    for (const check of evaluation.judge?.factChecks || []) checks.append(element('p', `${check.presentInScript ? '✓' : 'À vérifier'} ${check.reason}`, 'small'));
    panel.append(checks);

    const entries = [], faithfulEntries = [];
    const byId = new Map(review.sources.map((s) => [s.id, s.text]));
    for (const paragraph of review.prepared.script.segments) {
      const block = element('section', '', 'card');
      block.style.margin = '10px 0';
      if (published) {
        block.append(element('p', paragraph.text), element('p', paragraph.fr, 'muted small'));
      } else {
        const en = element('textarea'); en.value = paragraph.text; en.rows = 5; en.setAttribute('aria-label', 'Texte anglais');
        const fr = element('textarea'); fr.value = paragraph.fr; fr.rows = 4; fr.setAttribute('aria-label', 'Traduction française');
        const refs = element('input'); refs.value = paragraph.sourceSegments.join(', '); refs.setAttribute('aria-label', 'Identifiants des passages sources');
        block.append(en, fr, refs);
        entries.push({ paragraph, en, fr, refs });
      }
      const details = element('details');
      details.append(element('summary', 'Passages sources cités'));
      details.append(element('p', paragraph.sourceSegments.map((ref) => ref + ' — ' + byId.get(ref)).join('\n')));
      block.append(details);
      panel.append(block);
    }
    if (review.prepared.faithful && !published) {
      panel.append(element('h3', 'Traduction fidèle intégrale'));
      for (const s of review.prepared.faithful) {
        const block = element('section', '', 'card');
        const en = element('textarea'); en.value = s.text; en.rows = 4; en.setAttribute('aria-label', 'Traduction fidèle anglaise');
        block.append(en, element('p', s.fr, 'muted'));
        faithfulEntries.push({ id: s.id, en });
        panel.append(block);
      }
    }
    if (published) return;
    const actions = element('div', '', 'actions');
    for (const [action, label] of [['approve', 'Accepter et publier'], ['regenerate', 'Régénérer'], ['edit', 'Enregistrer les corrections et contrôler']]) {
      if (action === 'approve' && evaluation.verdict !== 'review') continue;
      const button = element('button', label, action === 'approve' ? 'primary' : '');
      button.onclick = async () => {
        button.disabled = true;
        try {
          const body = { id, signature: review.signature, action };
          if (action === 'edit') body.segments = entries.map(({ paragraph, en, fr, refs }) => ({ text: en.value, fr: fr.value, speaker: paragraph.speaker, sourceSegments: [...new Set(refs.value.split(/[,\s]+/).filter(Boolean))] }));
          if (action === 'edit' && faithfulEntries.length) body.faithful = faithfulEntries.map(({ id: fid, en }) => ({ id: fid, text: en.value }));
          await request('review', body);
          panel.hidden = true;
          await reviews();
        } catch (error) {
          panel.prepend(element('p', error.message, 'error-text'));
          button.disabled = false;
        }
      };
      actions.append(button);
    }
    panel.append(actions);
  } catch (error) {
    panel.hidden = false;
    panel.replaceChildren(element('p', error.message, 'error-text'));
  }
}
