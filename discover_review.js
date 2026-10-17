// Relecture locale : aucune chaîne issue d'un podcast n'est injectée comme HTML.
const $ = (id) => document.getElementById(id);
function element(tag,text,className) {
  const node=document.createElement(tag); if(text) node.textContent=text; if(className) node.className=className; return node;
}
async function request(path,body) {
  const r=await fetch('/api/discover/'+path,body ? {method:'POST',headers:{'Content-Type':'application/json','X-Discover-Atelier':'1'},body:JSON.stringify(body)} : {});
  const data=await r.json(); if(!r.ok) throw new Error(data.erreur || 'Action impossible.'); return data;
}
export async function reviews() {
  try {
    const {reviews}=await request('reviews'); const container=$('reviews'); container.replaceChildren();
    if(!reviews.length) return;
    container.append(element('h2','À relire avant publication'));
    for(const item of reviews) {
      const card=element('section','','card'); card.append(element('h3',item.title));
      card.append(element('p',item.verdict==='rejected' ? 'À régénérer : le contrôle de fidélité a rejeté cette version.' : 'Relecture nécessaire. Cette version ne sera pas publiée sans ton accord.'));
      const button=element('button','Lire et vérifier'); button.onclick=()=>open(item.id); card.append(button); container.append(card);
    }
  } catch(error) { $('error').textContent=error.message; }
}
async function open(id) {
  try {
    const review=await request('review?id='+encodeURIComponent(id));
    const panel=$('review-detail'); panel.replaceChildren(); panel.hidden=false;
    panel.append(element('h2',review.title));
    const evaluation=review.prepared.evaluation;
    panel.append(element('p',`Contrôle : ${evaluation.verdict==='rejected' ? 'à régénérer' : 'à relire'} · ${evaluation.wordCount} mots · écoute estimée ${Math.round(evaluation.wordCount/130)} min`));
    const warnings=[evaluation.coverageWarning,evaluation.tooShortForSubject ? 'La durée demandée est trop courte pour préserver le sujet.' : '',...(evaluation.language?.warnings || [])].filter(Boolean);
    if(evaluation.durationOutsideTarget) warnings.push(`Durée obtenue : ${evaluation.durationOutsideTarget.actualMinutes} min, cible : ${evaluation.durationOutsideTarget.targetMinutes} min.`);
    for(const [key,label] of [['numbersMissingFromSource','Nombre à vérifier'],['entitiesMissingFromSource','Nom à vérifier']]) for(const issue of evaluation[key] || []) warnings.push(`${label} : ${issue.value} (paragraphe ${issue.paragraph}).`);
    for(const judge of [evaluation.judge,evaluation.faithfulJudge].filter(Boolean)) for(const key of ['unsupportedClaims','omittedKeyPoints','lostNuances','promotionsRemaining','languageWarnings']) warnings.push(...(judge[key] || []));
    for(const warning of [...new Set(warnings)]) panel.append(element('p',warning,'error'));
    const checks=element('details');checks.append(element('summary','Détail des contrôles de fidélité'));
    for(const check of evaluation.judge?.factChecks || []) checks.append(element('p',`${check.presentInScript ? '✓' : 'À vérifier'} ${check.reason}`,'small'));
    panel.append(checks);
    const entries=[], faithfulEntries=[]; const byId=new Map(review.sources.map(s=>[s.id,s.text]));
    for(const paragraph of review.prepared.script.segments) {
      const block=element('section','','card');
      const en=element('textarea'); en.value=paragraph.text; en.rows=5; en.setAttribute('aria-label','Texte anglais');
      const fr=element('textarea'); fr.value=paragraph.fr; fr.rows=4; fr.setAttribute('aria-label','Traduction française');
      const refs=element('input'); refs.value=paragraph.sourceSegments.join(', '); refs.setAttribute('aria-label','Identifiants des passages sources');
      block.append(en,fr,refs);
      const details=element('details'); details.append(element('summary','Passages sources cités'));
      details.append(element('p',paragraph.sourceSegments.map(ref=>ref+' — '+byId.get(ref)).join('\n'))); block.append(details);
      entries.push({paragraph,en,fr,refs}); panel.append(block);
    }
    if(review.prepared.faithful) {
      panel.append(element('h3','Traduction fidèle intégrale'));
      for(const s of review.prepared.faithful) {const block=element('section','','card');const en=element('textarea');en.value=s.text;en.rows=4;en.setAttribute('aria-label','Traduction fidèle anglaise');block.append(en,element('p',s.fr,'muted'));faithfulEntries.push({id:s.id,en});panel.append(block);}
    }
    const all=element('details');all.append(element('summary','Toutes les sources'));all.append(element('p',review.sources.map(s=>s.id+' — '+s.text).join('\n')));panel.append(all);
    for(const [action,label] of [['approve','Accepter et publier'],['regenerate','Régénérer'],['edit','Enregistrer les corrections et contrôler']]) {
      if(action==='approve' && review.prepared.evaluation.verdict!=='review') continue;
      const button=element('button',label); button.onclick=async()=>{
        button.disabled=true;
        try {
          const body={id,signature:review.signature,action};
          if(action==='edit') body.segments=entries.map(({paragraph,en,fr,refs})=>({text:en.value,fr:fr.value,speaker:paragraph.speaker,sourceSegments:[...new Set(refs.value.split(/[,\s]+/).filter(Boolean))]}));
          if(action==='edit' && faithfulEntries.length) body.faithful=faithfulEntries.map(({id,en})=>({id,text:en.value}));
          await request('review',body); panel.hidden=true; await reviews();
        } catch(error) { $('error').textContent=error.message; button.disabled=false; }
      }; panel.append(button);
    }
  } catch(error) { $('error').textContent=error.message; }
}
