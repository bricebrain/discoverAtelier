const $ = (id) => document.getElementById(id);
const api = window.VocabulaireApi;
const echapper = (valeur) => String(valeur ?? "").replace(/[&<>"']/g,
  (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const libelles = {
  known:"Connu", not_known:"À apprendre",
  not_started:"Non commencé", prompt_generated:"Prompt créé", response_imported:"À approuver",
  review_required:"Revue requise", ready_to_publish:"Prêt à publier", rejected:"Refusé",
  published:"Publié", validation_failed:"Import incomplet", publish_failed:"Échec publication",
};
const etat = {
  mots:[], total:0, offset:0, limit:50, selection:new Set(), batch:null, batches:[],
  recherche:"", niveau:"", type:"", connaissance:"not_known", enrichissement:"", timer:null,
  editionId:null, selectionMode:false,
  ia:null, iaTimer:null,
};

function toast(message, type="") {
  const element = document.createElement("div"); element.className=`toast ${type}`; element.textContent=message;
  $("toasts").appendChild(element); setTimeout(() => element.remove(), 4500);
}
function statutHtml(statut) {
  return `<span class="statut ${echapper(statut)}">${echapper(libelles[statut] || statut || "—")}</span>`;
}
function parametres(extra={}) {
  return new URLSearchParams({q:etat.recherche,niveau:etat.niveau,type:etat.type,
    connaissance:etat.connaissance,enrichissement:etat.enrichissement,
    offset:String(etat.offset),limit:String(etat.limit),...extra});
}
function allerEtape(numero) {
  if (numero > 1 && !etat.batch) return toast("Créez ou ouvrez d’abord un lot.","erreur");
  document.querySelectorAll(".vue").forEach((vue) => vue.classList.toggle("active",vue.dataset.view===String(numero)));
  document.querySelectorAll(".etape").forEach((bouton) => bouton.classList.toggle("active",bouton.dataset.step===String(numero)));
}
function majSelection() {
  $("selection-count").textContent=etat.selection.size;
  $("creer-lot").disabled=!etat.selection.size || etat.selection.size>50;
  $("supprimer-selection").disabled=!etat.selection.size || etat.selection.size>200;
  $("effacer-selection").disabled=!etat.selection.size;
  document.querySelectorAll("[data-word-id]").forEach((caseMot) => { caseMot.checked=etat.selection.has(caseMot.dataset.wordId); });
}

async function chargerMots(force=false) {
  etat.selectionMode=false;
  $("mots").innerHTML='<tr><td colspan="8" class="vide">Chargement du référentiel…</td></tr>';
  try {
    const data=await api.mots(parametres(force?{force:"1"}:{}));
    Object.assign(etat,{mots:data.items,total:data.total});
    $("stats").textContent=`${data.corpusTotal.toLocaleString("fr-FR")} mots · ${data.knownTotal.toLocaleString("fr-FR")} connus`;
    if ($("type").options.length===1) data.types.forEach((type) => $("type").add(new Option(type,type)));
    rendreMots();
  } catch (erreur) { $("mots").innerHTML=`<tr><td colspan="8" class="vide">${echapper(erreur.message)}</td></tr>`; toast(erreur.message,"erreur"); }
}
function rendreMots() {
  const pages=Math.max(1,Math.ceil(etat.total/etat.limit));
  $("resume-liste").textContent=etat.selectionMode
    ? `${etat.selection.size} mot(s) sélectionné(s) automatiquement — tous affichés ci-dessus`
    : `${etat.total.toLocaleString("fr-FR")} résultat${etat.total>1?"s":""}`;
  $("page").textContent=etat.selectionMode?"Sélection":`${Math.floor(etat.offset/etat.limit)+1} / ${pages}`;
  $("precedent").disabled=etat.selectionMode||etat.offset===0; $("suivant").disabled=etat.selectionMode||etat.offset+etat.limit>=etat.total;
  $("mots").innerHTML=etat.mots.length?etat.mots.map((mot)=>`<tr>
    <td class="check"><input type="checkbox" data-word-id="${echapper(mot.id)}"></td>
    <td>${echapper(mot.id)}</td><td><span class="mot">${echapper(mot.mot)}</span></td>
    <td class="traduction">${echapper(mot.traduction||"—")}</td><td><span class="tag">${echapper(mot.type||"—")}</span></td>
    <td>${echapper(mot.niveau||"—")}</td><td>${statutHtml(mot.knowledgeStatus)}</td><td>${statutHtml(mot.enrichmentStatus)}</td></tr>`).join("")
    :'<tr><td colspan="8" class="vide">Aucun mot ne correspond à ces filtres.</td></tr>';
  majSelection();
}

async function chargerLot(batchId="") {
  try { const data=await api.lot(batchId); etat.batch=data.batch; etat.batches=data.batches; rendreLot(); }
  catch (erreur) { toast(erreur.message,"erreur"); }
}
function rendreLots() {
  $("nombre-lots").textContent=etat.batches.length;
  $("lots").innerHTML=etat.batches.length?etat.batches.map((lot)=>`<button class="lot ${etat.batch?.batchId===lot.batchId?"actif":""}" data-batch-id="${echapper(lot.batchId)}"><strong>${echapper(lot.batchId)}</strong><span>${lot.count}</span><small>${echapper(libelles[lot.status]||lot.status)}</small></button>`).join(""):'<p class="vide">Aucun lot créé.</p>';
}
function rendreLot() {
  rendreLots(); const lot=etat.batch;
  $("prompt").textContent=lot?.prompt||"Créez d’abord un lot à l’étape 1.";
  $("lot-prompt-id").textContent=lot?.batchId||"Aucun lot";
  if (lot?.responseRaw && !$("reponse").value.trim()) $("reponse").value=lot.responseRaw;
  $("supprimer-lot").disabled=!lot || lot.status==="published" || Object.values(lot.entries||{}).some((item)=>item.status==="published");
  rendreRevisions();
}
function sourceDuLot(id) { return etat.batch?.sourceEntries.find((source)=>source.id===id)||{}; }
function rendreRevisions() {
  const lot=etat.batch, items=lot?Object.entries(lot.entries||{}):[];
  const prets=items.filter(([,item])=>item.status==="ready_to_publish").length;
  const publies=items.filter(([,item])=>item.status==="published").length;
  const enAttente=items.filter(([,item])=>["response_imported","review_required"].includes(item.status)).length;
  $("resume-revue").innerHTML=lot?`<strong>${items.length}</strong> importées · <strong>${prets}</strong> approuvées · <strong>${publies}</strong> publiées`:"";
  const erreurs=lot?.errors||[];
  $("erreurs-lot").innerHTML=erreurs.length?`<div class="message erreur"><strong>Import incomplet :</strong><br>${erreurs.slice(0,8).map(echapper).join("<br>")}</div>`:"";
  $("revisions").innerHTML=items.length?items.map(([id,item])=>rendreRevision(id,item)).join(""):'<p class="vide">Aucune proposition importée.</p>';
  $("publier").disabled=!prets || lot?.status==="published";
  $("tout-approuver").disabled=!enAttente;
}
function rendreRevision(id,item) {
  const source=sourceDuLot(id), p=item.proposed, sens=p.senses||[];
  const actions=item.status==="published"?'<span class="pastille sure">✓ Publié</span>':`<button class="btn petit" data-action="editer" data-id="${echapper(id)}">Modifier</button><button class="btn petit" data-action="refuser" data-id="${echapper(id)}">Refuser</button><button class="btn petit primaire" data-action="approuver" data-id="${echapper(id)}">Approuver</button>`;
  return `<article class="revision"><div class="revision-tete"><strong>${echapper(source.word)}</strong><span class="tag">${echapper(p.partOfSpeech)}</span>${statutHtml(item.status)}<span class="espaceur"></span><small>ID ${echapper(id)}</small></div>
    <div class="comparaison"><div><h3>Valeur originale</h3><b>${echapper(source.translation||"—")}</b><p>${echapper(source.type||"—")} · ${echapper(source.cefr||"—")}</p></div><div class="fleche">→</div>
    <div class="details-proposition"><h3>Enrichissement proposé</h3><b>${echapper(p.displayForm)} — ${echapper(p.primaryTranslation)}</b><ul>${sens.map((s)=>`<li>${echapper(s.translation)} · <em>${echapper(s.exampleEn)}</em></li>`).join("")}</ul></div></div>
    ${(item.warnings||[]).length?`<div class="avertissements">⚠ ${item.warnings.map(echapper).join(" · ")}</div>`:""}<div class="revision-actions">${actions}</div></article>`;
}

async function selectionnerProchains() {
  try {
    const data=await api.prochains(parametres({limit:$("taille-lot").value,offset:"0"}));
    etat.selection=new Set(data.ids); etat.mots=data.items; etat.total=data.items.length;
    etat.offset=0; etat.selectionMode=true; rendreMots(); toast(`${data.ids.length} mot(s) sélectionné(s) et affiché(s).`);
  } catch (erreur) { toast(erreur.message,"erreur"); }
}
async function effacerSelection() {
  etat.selection.clear(); etat.offset=0; await chargerMots();
}
async function creerLot() {
  try { const data=await api.creerLot([...etat.selection]); etat.batch=data.batch; etat.selection.clear(); await chargerLot(data.batch.batchId); await chargerMots(); allerEtape(2); }
  catch (erreur) { toast(erreur.message,"erreur"); }
}
async function importer() {
  const texte=$("reponse").value.trim(); if (!texte) return toast("Collez ou importez une réponse JSON.","erreur");
  try {
    const data=await api.importer(etat.batch.batchId,texte); etat.batch=data.batch; etat.batches=data.batches;
    const n=Object.keys(data.batch.entries||{}).length, incomplet=data.batch.errors.length;
    $("rapport-import").innerHTML=`<div class="message ${incomplet?"erreur":"ok"}">${n} entrée(s) valide(s) conservée(s)${incomplet?` · ${data.batch.errors.length} anomalie(s) à corriger.`:"."}</div>`;
    rendreLot(); allerEtape(4); await chargerMots();
  } catch (erreur) { $("rapport-import").innerHTML=`<div class="message erreur">${echapper(erreur.message)}</div>`; }
}
async function changerStatut(id,statut) {
  try { await api.statut(etat.batch.batchId,id,statut); await chargerLot(etat.batch.batchId); }
  catch (erreur) { toast(erreur.message,"erreur"); }
}
async function toutApprouver() {
  const items=Object.values(etat.batch?.entries||{});
  const sensibles=items.filter((item)=>item.status==="review_required").length;
  const suffixe=sensibles?`\n\n${sensibles} proposition(s) demandent normalement une revue renforcée.`:"";
  if (!confirm(`Approuver toutes les propositions valides en attente ?${suffixe}`)) return;
  try { const data=await api.approuverTout(etat.batch.batchId); etat.batch=data.batch; etat.batches=data.batches; rendreLot(); toast(`${data.approved} proposition(s) approuvée(s).`); }
  catch (erreur) { toast(erreur.message,"erreur"); }
}
function ouvrirEdition(id) {
  etat.editionId=id; $("edition-json").value=JSON.stringify(etat.batch.entries[id].proposed,null,2); $("dialogue-edition").showModal();
}
async function enregistrerEdition(event) {
  event.preventDefault();
  try { const proposition=JSON.parse($("edition-json").value); await api.editer(etat.batch.batchId,etat.editionId,proposition); $("dialogue-edition").close(); await chargerLot(etat.batch.batchId); }
  catch (erreur) { toast(`Modification refusée : ${erreur.message}`,"erreur"); }
}
async function publier() {
  if (!confirm("Publier les entrées approuvées dans English Fluency ?")) return;
  const bouton=$("publier"), texte=bouton.textContent; bouton.disabled=true; bouton.textContent="Publication en cours…";
  try { const data=await api.publier(etat.batch.batchId,$("publication-partielle").checked); toast(`${data.publication.ids.length} enrichissement(s) publié(s).`); await chargerLot(etat.batch.batchId); await chargerMots(true); }
  catch (erreur) { toast(erreur.message,"erreur"); await chargerLot(etat.batch.batchId); }
  finally { bouton.textContent=texte; }
}
async function supprimerLot() {
  if (!etat.batch) return;
  const message=`Supprimer le lot ${etat.batch.batchId} ?\n\nSes mots redeviendront disponibles pour la sélection automatique.`;
  if (!confirm(message)) return;
  try {
    const data=await api.supprimerLot(etat.batch.batchId);
    etat.batch=data.batch; etat.batches=data.batches; etat.selection.clear();
    rendreLot(); await chargerMots(); allerEtape(1); toast("Lot supprimé : ses mots sont de nouveau disponibles.");
  } catch (erreur) { toast(erreur.message,"erreur"); }
}
function telechargerPrompt() {
  if (!etat.batch) return; const blob=new Blob([etat.batch.prompt],{type:"text/plain;charset=utf-8"}); const a=document.createElement("a");
  a.href=URL.createObjectURL(blob); a.download=`${etat.batch.batchId}-prompt.txt`; a.click(); URL.revokeObjectURL(a.href);
}
function demanderSuppression() {
  const ids=[...etat.selection]; $("suppression-count").textContent=ids.length;
  $("suppression-apercu").textContent=ids.slice(0,20).map((id)=>etat.mots.find((m)=>m.id===id)?.mot||id).join(", "); $("dialogue-suppression").showModal();
}
async function supprimer() {
  const bouton=$("confirmer-suppression"); bouton.disabled=true;
  try { const data=await api.supprimer([...etat.selection]); $("dialogue-suppression").close(); etat.selection.clear(); await chargerMots(true); toast(`${data.deleted} mot(s) supprimé(s).`); }
  catch (erreur) { toast(erreur.message,"erreur"); } finally { bouton.disabled=false; }
}

function rendreIa() {
  const migration=etat.ia;if(!migration)return;const config=migration.config||{};
  const actif=["running","stopping"].includes(migration.status), total=migration.total||0;
  const progression=total?Math.round((migration.processed||0)*100/total):0;
  $("ia-gemini").textContent=`Gemini · ${config.generatorModel||"non configuré"}`;
  $("ia-openai").textContent=`OpenAI · ${config.auditorModel||"non configuré"} · raisonnement faible`;
  $("ia-gemini").classList.toggle("configure",config.geminiConfigured);
  $("ia-openai").classList.toggle("configure",config.openaiConfigured);
  $("ia-message").textContent=migration.error||migration.message||"Prêt.";
  const usage=migration.usage||{};
  $("ia-resume").textContent=total?`${migration.processed||0} / ${total} traités · ${migration.published||0} publiés · ${usage.calls||0} appels API · ${usage.inputTokens||0} tokens entrants · ${usage.outputTokens||0} tokens sortants (raisonnement inclus)`:`Lots de ${config.batchSize||20} mots · Aucune migration lancée.`;
  $("ia-progression-barre").style.width=`${progression}%`;
  $("ia-demarrer").disabled=actif||!config.geminiConfigured||!config.openaiConfigured;
  $("ia-arreter").disabled=!actif;
  if(actif&&!etat.iaTimer)etat.iaTimer=setInterval(chargerIa,3000);
  if(!actif&&etat.iaTimer){clearInterval(etat.iaTimer);etat.iaTimer=null;chargerMots(true);chargerLot();}
}
async function chargerIa() {
  try { etat.ia=await api.iaEtat();rendreIa(); }
  catch(erreur){$("ia-message").textContent=erreur.message;}
}
function ouvrirConfigurationIa() {
  const config=etat.ia?.config||{};$("cle-gemini").value="";$("cle-openai").value="";
  $("modele-gemini").value=config.generatorModel||"gemini-3.1-flash-lite";
  $("modele-openai").value=config.auditorModel||"gpt-6-luna";
  $("ia-taille").value=config.batchSize||20;$("ia-reprises").value=config.maxRetries??2;
  $("ia-publier-auto").checked=config.autoPublish!==false;$("dialogue-ia").showModal();
}
async function enregistrerConfigurationIa(event) {
  event.preventDefault();
  try {
    await api.iaConfigurer({geminiApiKey:$("cle-gemini").value,openaiApiKey:$("cle-openai").value,
      generatorModel:$("modele-gemini").value,auditorModel:$("modele-openai").value,
      batchSize:Number($("ia-taille").value),maxRetries:Number($("ia-reprises").value),
      autoPublish:$("ia-publier-auto").checked});
    $("dialogue-ia").close();await chargerIa();toast("Configuration API enregistrée localement.");
  } catch(erreur){toast(erreur.message,"erreur");}
}
async function demarrerIa() {
  const limite=Number($("ia-limite").value), perimetre=$("ia-perimetre").value;
  const description=perimetre==="not_known"?"Mots non traités et pas encore connus uniquement.":"Tous les mots non traités, y compris les mots déjà connus.";
  const texte=(limite?`Lancer un essai entièrement automatique sur ${limite} mots ?`:"Lancer la correction et la publication automatiques du corpus restant ?")+`\n\n${description}`;
  if(!confirm(texte))return;
  try { await api.iaDemarrer(perimetre,limite);await chargerIa();toast("Migration API démarrée."); }
  catch(erreur){toast(erreur.message,"erreur");}
}
async function arreterIa() { try{await api.iaArreter();await chargerIa();}catch(erreur){toast(erreur.message,"erreur");} }

$("mots").addEventListener("change",(e)=>{const id=e.target.dataset.wordId;if(!id)return;e.target.checked?etat.selection.add(id):etat.selection.delete(id);majSelection();});
document.querySelectorAll(".etape,[data-go]").forEach((b)=>b.addEventListener("click",()=>allerEtape(Number(b.dataset.step||b.dataset.go))));
$("lots").addEventListener("click",(e)=>{const b=e.target.closest("[data-batch-id]");if(b){chargerLot(b.dataset.batchId);allerEtape(4);}});
$("revisions").addEventListener("click",(e)=>{const b=e.target.closest("[data-action]");if(!b)return;if(b.dataset.action==="editer")ouvrirEdition(b.dataset.id);else changerStatut(b.dataset.id,b.dataset.action==="approuver"?"ready_to_publish":"rejected");});
[["niveau","niveau"],["type","type"],["connaissance","connaissance"],["enrichissement","enrichissement"]].forEach(([id,cle])=>$(id).addEventListener("change",(e)=>{etat[cle]=e.target.value;etat.offset=0;etat.selection.clear();chargerMots();}));
$("recherche").addEventListener("input",(e)=>{clearTimeout(etat.timer);etat.timer=setTimeout(()=>{etat.recherche=e.target.value;etat.offset=0;chargerMots();},250);});
$("prochains").addEventListener("click",selectionnerProchains); $("creer-lot").addEventListener("click",creerLot); $("analyser-json").addEventListener("click",importer);
$("copier-prompt").addEventListener("click",async()=>{if(etat.batch){await navigator.clipboard.writeText(etat.batch.prompt);toast("Prompt copié.");}}); $("telecharger-prompt").addEventListener("click",telechargerPrompt);
$("fichier-json").addEventListener("change",async(e)=>{const [fichier]=e.target.files;if(fichier)$("reponse").value=await fichier.text();});
$("enregistrer-edition").addEventListener("click",enregistrerEdition); $("publier").addEventListener("click",publier);
$("tout-approuver").addEventListener("click",toutApprouver);
$("supprimer-lot").addEventListener("click",supprimerLot);
$("effacer-selection").addEventListener("click",effacerSelection);
$("precedent").addEventListener("click",()=>{etat.offset=Math.max(0,etat.offset-etat.limit);chargerMots();}); $("suivant").addEventListener("click",()=>{etat.offset+=etat.limit;chargerMots();});
$("supprimer-selection").addEventListener("click",demanderSuppression); $("confirmer-suppression").addEventListener("click",supprimer); ["fermer-suppression","annuler-suppression"].forEach((id)=>$(id).addEventListener("click",()=>$("dialogue-suppression").close()));
$("ia-configurer").addEventListener("click",ouvrirConfigurationIa);$("enregistrer-ia").addEventListener("click",enregistrerConfigurationIa);$("ia-demarrer").addEventListener("click",demarrerIa);$("ia-arreter").addEventListener("click",arreterIa);
$("synchroniser").addEventListener("click",async()=>{etat.offset=0;await chargerMots(true);toast("Référentiel synchronisé.");});
$("reinitialiser").addEventListener("click",()=>{Object.assign(etat,{recherche:"",niveau:"",type:"",connaissance:"not_known",enrichissement:"",offset:0});["recherche","niveau","type","enrichissement"].forEach((id)=>$(id).value="");$("connaissance").value="not_known";chargerMots();});
Promise.all([chargerMots(),chargerLot(),chargerIa()]);
