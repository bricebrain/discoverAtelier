# CAHIER DES CHARGES DÉFINITIF — ENGLISH FLUENCY

**Version : 2.0 — 16 octobre 2026**  
**Statut : spécification consolidée, prête pour implémentation progressive après audit de l'existant**  
**Référence :** `CAHIER_DES_CHARGES_ECOUTE_ACTIVE(1).md` (v1.1), enrichie des décisions ultérieures.  
**Périmètre :** `convert/` (atelier Mac Python), `englishfluency-worker/` (Cloudflare Worker, D1, R2), `englishPwa/` (React, TypeScript, MUI).

> **Vision.** Apprendre l'anglais avec des contenus réellement intéressants, en préservant leur sens, en adaptant l'aide aux connaissances et aux performances de l'apprenant et en vérifiant les progrès sur des contenus jamais étudiés. L'écoute libre reste prioritaire ; l'écoute active, la lecture, le SRS et ChatGPT Live se complètent. Les mécanismes sont explicables et fonctionnent sans appels IA systématiques.

---

## 0. Décisions irrévocables de conception (sauf validation explicite)

1. **Ne pas supprimer ni remplacer les fonctionnalités existantes** : Lingvist, SRS, lecture, écoute libre, scripts et audios, Live, pipeline bilingue, anciennes publications.
2. **Source toujours conservée.** Vidéo anglaise : audio original et transcription fidèle. Vidéo française : source française conservée et traduction anglaise fidèle avec audio Kokoro. Texte/article : original conservé et anglais de référence si nécessaire. Production personnelle : original brut conservé et correction distinguée des reformulations.
3. **Une adaptation facultative** au niveau utile, pas de génération systématique de A1/A2/B1/B2. D'abord évaluer l'original et proposer des aides ciblées. Une adaptation peut porter sur un extrait seulement.
4. **Niveau de lecture ≠ niveau d'écoute**. Le retour de l'apprenant sur les phrases illustratives suggère B1 confortable à l'écrit, B2 avec aide ; cela n'est pas une certification CECRL. Mesurer l'oral séparément.
5. **Conserver la richesse du contenu** : faits, nombres, nuances, causalité, concepts, jargon important expliqué plutôt que supprimé. Ne jamais confondre traduction fidèle et adaptation pédagogique.
6. **Lingvist conservé** et enrichi : mots déclarés connus, connaissance démontrée en lecture, reconnaissance orale et production sont des signaux différents.
7. **Local-first pour l'audio** : MacWhisper et Kokoro existants. Modèles Hugging Face exécutés localement quand pertinents et compatibles. Aucune obligation d'hébergement HF.
8. **IA cloud optionnelle, contrôlée** : Gemini et DeepSeek ; OpenRouter comme alternative ; clés secrètes, cache, validation, budgets et repli sans IA. Pas de clé API dans le navigateur.
9. **ChatGPT Live** reste l'outil privilégié pour les dialogues oraux ; aucune reconnaissance/enregistrement/notation vocale de l'apprenant dans la PWA.
10. **Mesurer les apprentissages plutôt que l'activité** : contenus inédits et tests différés ; l'auto-évaluation est un complément, jamais une preuve.
11. **Tout déploiement Worker ou PWA exige une autorisation explicite.** Ne jamais pousser automatiquement en production.

## 1. Objectifs, publics et indicateurs

### 1.1 Objectifs fonctionnels

- Importer vidéo/audio YouTube, fichier audio, texte collé, `.txt`, `.md`, article collé ou article depuis URL sous réserve d'extraction autorisée et fiable, transcription personnelle (texte et éventuellement audio).
- Produire une **ressource de référence** en anglais, une traduction française liée, une piste audio en anglais (originale si elle existe), et des segments synchronisés.
- Évaluer l'accessibilité d'un contenu à partir du lexique connu, des expressions, de la grammaire, du débit **si audio**, et surtout des résultats de première compréhension.
- Permettre une **aide à la demande** (glossaire, traduction, explications) ou une adaptation fidèle (passage entier ou extrait).
- Proposer une séance courte d'écoute active avec diagnostic individualisé et 0 à 2 expressions pertinentes vers le SRS.
- Proposer une expérience de lecture active pour les textes sans imposer un audio ; l'audio Kokoro est facultatif puis généré dans l'atelier lorsque demandé.
- Vérifier les connaissances à J+3/J+10 dans des contextes et voix distincts quand les ressources sont disponibles.
- Suivre séparément lecture, compréhension orale, identification sonore et mémorisation.

### 1.2 Non-objectifs initiaux

- Pas de diagnostic CECRL officiel ; pas de score unique de niveau supposé parfaitement fiable.
- Pas de fine-tuning ni de moteur ML de recommandation entraîné.
- Pas de réécriture automatique obligatoire de tout média.
- Pas de diffusion de modèle local depuis le Mac éteint ; ne pas bloquer la PWA sur la disponibilité du Mac.
- Pas de génération automatique de nouvelles voix ou d'audios via une API externe tant que Kokoro répond aux besoins.
- Pas de crawler contournant l'accès aux articles payants ; conserver uniquement les contenus dont l'utilisation est autorisée.

### 1.3 Principes pédagogiques

- Input compréhensible : contenu globalement intelligible avec quelques nouveautés ; le « i+1 » est une heuristique, non un score exact.
- Deux pratiques coexistantes : **extensive** (plaisir/sens, peu d'interruptions) et **intensive** (court extrait, décodage et feedback).
- Première écoute sans support pour mesurer la compréhension spontanée ; ne pas confondre répétition et généralisation.
- Les mots connus à l'écrit ne sont pas réputés connus à l'oral.
- Éviter les « tests partout » ; questions limitées, ciblées et parfois facultatives.
- Les exercices de reconnaissance sonore et les exercices de compréhension du sens sont comptabilisés séparément.

## 2. Architecture fonctionnelle

```text
ENTRÉES
  YouTube EN / FR | Fichier audio EN / FR | Texte / article EN / FR |
  Transcription personnelle EN / FR (+ éventuellement audio)
            |
            v
ATELIER MAC (convert/)
  Import -> normalisation -> source immuable -> transcription si audio
        -> traduction fidèle si nécessaire -> alignement source/segments
        -> analyse pédagogique -> estimation du niveau accessible
        -> OPTION: adaptation fidèle (complète ou extrait)
        -> OPTION: Kokoro EN et timings propres à chaque version
        -> validation humaine -> publication
            |
            v
CLOUDFLARE (Worker / D1 / R2)
  versions, segments, variantes, audios, états pédagogiques, sessions,
  progrès, références audio, données SRS, exercices de transfert
  -> passerelle IA sécurisée, cache, quotas et budgets (si activée)
            |
            v
PWA REACT
  Écoute/lecture libre | Écoute active | Lecture active | Comparaison
  versions | Aides ciblées | Lingvist/SRS | Vérifications différées |
  ChatGPT Live (prompt copié) | Tableau de progrès
```

**Séparation des responsabilités** : l'atelier Mac réalise les traitements audio lourds ; le Worker stocke, sécurise et orchestre les tâches légères ; la PWA lit, interagit et met en cache. Les contenus publiés demeurent utilisables même sans accès à Gemini, DeepSeek ou OpenRouter.

## 3. Import universel et pipeline commun

### 3.1 Entrées prises en charge

| Entrée | Référence conservée | Préparation anglaise | Audio proposé |
|---|---|---|---|
| YouTube / audio EN | Audio original + transcription EN | EN originale fidèle | Original authentique |
| YouTube / audio FR | Audio FR + transcription FR | Traduction EN fidèle | Kokoro EN |
| Article / texte EN | Texte original EN + provenance | Identique (normalisé sans altérer le sens) | Kokoro EN facultatif |
| Article / texte FR | Texte FR + provenance | Traduction EN fidèle | Kokoro EN facultatif |
| Transcription personnelle EN | Texte brut EN (+ audio si fourni) | Correction EN annotée, distincte d'une reformulation | Kokoro sur version corrigée, facultatif |
| Transcription personnelle FR | Texte brut FR (+ audio si fourni) | Traduction fidèle EN ; reformulation facultative | Kokoro EN facultatif |

**Import article URL** : extraire uniquement si le site le permet, afficher URL, titre, date/auteur si disponibles, état d'extraction, conserver un texte source vérifiable ; proposer un collage manuel si l'extraction est bloquée. Limiter les tailles, nettoyer HTML et scripts ; aucun HTML importé n'est injecté tel quel dans la PWA.

**Texte collé** : détection de langue proposée mais confirmable ; sélection du type `article | transcript | personal_output | other` ; titre éditable ; aperçu du nombre de caractères et des paragraphes.

### 3.2 Pipeline partagé

1. Ingestion + validation taille/format, conservation source, empreinte stable (`sourceRevision`).
2. Transcription MacWhisper SRT si audio ; garder la source et en dériver TXT. Pour un texte, segmentation par paragraphes/phrases avec ID stables.
3. Création du **texte anglais de référence** : identité si EN ; traduction fidèle si FR ; correction documentée pour production personnelle EN.
4. Segmentation et alignement propre à chaque version ; traduction FR disponible segment par segment, sans imposer une correspondance 1:1 si reformulation.
5. Analyse des chunks, grammaire, questions optionnelles et prononciations possibles.
6. Analyse d'accessibilité estimée ; proposer source seule, aide ciblée ou adaptation.
7. Si audio nécessaire : conserver l'original EN ou générer Kokoro avec ses propres timings ; si lecture seulement, aucun TTS obligatoire.
8. Validation humaine, publication versionnée ; ancienne version utilisable par les références existantes.

### 3.3 Modes de contenu et de fidélité

- `faithful` : transcription/traduction/correction sans suppression d'information ; référence stable.
- `assisted_original` : même texte original, avec aides affichables et surlignage des difficultés.
- `adapted` : texte plus accessible **sans perte des faits ou nuances importantes** ; générer avec consignes et contrôle de fidélité ; texte et audio distincts.
- `targeted_adaptation` : seulement la section ou les segments sélectionnés ; ne pas remplacer le fichier original ni prétendre que sa synchronisation s'applique à l'adaptation.

Génération de variantes à la demande **depuis l'atelier** en première version. Si demande dans la PWA, elle devient une demande différée explicite, visible comme telle, tant que le Mac n'est pas accessible. Ne pas promettre une génération instantanée locale.

## 4. Moteur d'accessibilité / Comprehensible Input

### 4.1 Principes

La difficulté **estimée** précède la séance et se distingue de la compréhension **observée**. Le moteur doit être explicable, avec diagnostic de confiance ; aucune catégorisation CECRL n'est présentée comme certaine sur un seul passage.

Entrées :
- Lingvist : mots déclarés connus et progression SRS (`words`, `word_progress`) ;
- lemmes et variantes morphologiques, mots composés et chunks ;
- grammaire/structures de l'extrait, jargon et densité conceptuelle ;
- débit **par extrait** si audio, accent et type de voix connus (authentique / TTS) ;
- résultats des dernières premières écoutes/lectures et des tests différés ;
- auto-évaluation, utilisée uniquement comme signal faible.

### 4.2 Couverture lexicale estimée

- Calcul sur les **occurrences** (tokens de mots) et, en complément, sur les mots distincts ; préserver les négations et unités multi-mots.
- Faire une lemmatisation prudente ; ne pas assimiler automatiquement `work` à toutes ses constructions ni `get` à ses phrasal verbs.
- Source `validated_manually` différente de `demonstrated_reading` et `demonstrated_listening`.
- Mots absents du profil = « inconnus ou non évalués », jamais automatiquement « inconnus ».
- L'indice lexical sert au tri et aux aides, **pas** à attribuer une maîtrise orale garantie ni un niveau CECRL.

### 4.3 Profil de compétences (progression non destructive)

Conserver le SRS existant et lui adjoindre un profil par entrée :
- `declaredKnown` (validation manuelle Lingvist) ;
- `readingRecognition` (résultats de lecture / exercices texte) ;
- `listeningRecognition` (résultats audio) ;
- `meaningInContext` (questions de sens) ;
- `productionEvidence` (facultatif, données déclarées de Live ou production personnelle, **pas** évaluation automatique de prononciation).

Les indicateurs sont des états/probabilités de travail simples avec date, provenance et nombre d'observations ; ne pas imposer cinq systèmes SRS indépendants. Prévoir migration additive depuis les tables existantes.

### 4.4 Politique de choix des versions

| Observation sur l'original | Suggestion |
|---|---|
| Idées principales comprises, quelques difficultés | Original avec glossaire et aides ciblées |
| Original très facile | Original sans surcharge, ou extrait plus exigeant |
| Sujet seulement compris | Passage adapté B1/B1+ ou accompagné, à confirmer |
| Presque rien compris | Adaptation plus accessible puis retour progressif à l'original |
| Absence de première écoute | Ne pas adapter automatiquement sur la seule base du score lexical ; proposer choix utilisateur |

Le niveau proposé dépend du **profil de compréhension orale pour l'audio**, et du profil de lecture pour les textes. Le retour actuel de l'utilisateur (« B1 lisible avec 1–2 mots manquants, B2 stimulant, A2 trop simplifié ») ne sert que d'hypothèse initiale de lecture, pas de règle globale.

### 4.5 Fidélité et alignement des versions

- Stocker pour chaque variante : source, langue, transformation, niveau **cible estimé**, modèle/prompt/version, révision, statut de revue.
- Vérifier l'intégrité des chiffres, noms, relations causales, réserves (« may », « might »), termes techniques ; conserver le jargon essentiel avec définitions.
- Liaison `sectionMappings` entre sections originales et adaptées (plusieurs-vers-plusieurs autorisé) ; ne jamais réutiliser `startMs/endMs` d'une autre piste.
- Pour les contenus FR traduits EN, conserver une traduction **fidèle** séparée de l'éventuelle adaptation B1/B2.
- Les annotations et résultats liés à l'original ne sont pas recopiés vers une adaptation sans validation.

## 5. Atelier Mac : détails audio et analyse

### 5.1 Transcription et timings

- MacWhisper `mw transcribe --format srt` pour les sources audio : conserver `.srt`, produire `.txt` pour l'ancien pipeline.
- Segments EN originaux = regroupements de répliques SRT consécutives (ordre inchangé, ≈220 caractères sans couper une réplique), `startMs/endMs` issus du SRT. Vérifier à l'oreille sur l'audio final.
- Kokoro : synthèse **par segment** de chaque variante EN, avec blocs internes et silences mesurés ; produire timings depuis les échantillons audio ; la variante a une timeline autonome.
- Pour une version texte sans TTS, timings `null` et mode **lecture active disponible**, écoute active indisponible jusqu'à génération d'audio.
- Vérifier croissance des timings, chevauchements (tolérance 200 ms), fin du dernier segment <= durée +500 ms ; invalide = pas d'écoute active, sans bloquer la publication.
- `segmentationVersion`, `contentRevision`, `audioRevision` pour distinguer modification textuelle, segmentation et piste audio. Re-segmentation d'ancien bundle = avertissement traduction/analyse à refaire.
- Possibilité de tester WhisperX/alignement local via Hugging Face **en expérimentation**, uniquement si les SRT se révèlent insuffisants ; vérifier CPU, latence et qualité sur Mac Intel 16 Go. Aucun remplacement obligatoire de MacWhisper.

### 5.2 Analyse linguistique

Analyses : `chunks`, `grammarPoints`, `connectedSpeech`, `comprehensionQuestions`, `estimatedDifficulty`, `lexicalCoverage`, `sectionMappings` si adaptation.

**Connected speech** : à partir du texte seul, annoter `possiblePronunciation` et `verified:false` (ne jamais prétendre que l'enregistrement contient la réduction). Seule une écoute humaine dans l'atelier peut passer `verified:true` ; la PWA formule « Souvent prononcé... » ou « Ici, on entend... » selon l'état. Types `reduction | linking | elision | weak_form | assimilation`.

**Questions** : 3 ou 4 choix, lien à segments/sections existants, 1 question de sens par ≈2 minutes, au maximum 3 par extrait ; préférer idées principales et causalité plutôt que détails lexicaux ; listes vides acceptées. Les questions destinées à évaluer la **première écoute** doivent être préparées sans montrer le texte au préalable.

### 5.3 IA multimodèle : implémentation

Un service `AIProvider` local dans Python et une passerelle éventuelle Worker pour les appels depuis la PWA :
- `Gemini`: analyses nécessitant réellement l'audio ou les documents multimodaux, traductions / reformulations testées ;
- `DeepSeek`: analyses textuelles, questions, adaptations, exemples de transfert ;
- `OpenRouter`: modèles alternatifs et secours configurables ;
- `Hugging Face`: dépôt de modèles spécialisés **exécutables localement** ; pas besoin du service d'inférence payant ;
- `MacWhisper` + `Kokoro`: pipeline audio existant conservé.

Ne pas imposer un fournisseur selon une réputation supposée : comparer 15–20 extraits réels avec une grille de fidélité, clarté, conformité JSON, coût et latence ; choisir un défaut par tâche configurable.

Sécurité : clés `.env` local / Cloudflare secrets, jamais dans React ni les métadonnées publiées ; opt-in et transparence sur l'envoi d'audios/textes aux API ; attention particulière aux transcriptions personnelles et contenus sensibles. Budget plafonné, taux limites, retry contrôlé, cache par hash de `(input, model, promptVersion, options)` ; aucun appel systématique au visionnage. Valider strictement JSON (Python et Zod/TypeScript), taille, liens d'IDs, duplications, qualité et fidélité. En cas d'indisponibilité, conserver prompts copier-coller ChatGPT + JSON collé comme mode manuel de secours.

**Important :** analyser un audio avec Gemini peut aider, mais ne valide pas à lui seul l'exactitude phonétique d'une annotation.

## 6. Expérience PWA : écoute libre et active

### 6.1 Lecture libre et versions

Conserver lecteur actuel. Sur une fiche contenu : affichage `Original / Avec aide / Adapté` uniquement selon les variantes disponibles. Badge `Voix authentique` / `Kokoro — voix de synthèse`. Montrer la source et le niveau **cible de l'adaptation**, jamais l'annoncer comme niveau évalué de l'utilisateur. Afficher les correspondances de sections et un passage « Voir ce passage dans l'original » lorsque la liaison existe.

### 6.2 Écoute active : parcours de référence

Extrait **1–2 min par défaut**, jusqu'à 3 min s'il est accessible. Choix d'extraits successifs ou manuel ; un même contenu peut contenir plusieurs séances.

1. **Première écoute sans texte** : auto-évaluation `nothing | topic | main_ideas | almost_all` et 1–3 questions de sens si disponibles ; ne pas afficher la réponse avant de fixer le résultat de première écoute.
2. **Décodage** : texte EN synchronisé, FR masqué à la demande, lecture segmentée/boucles, 0,75×/0,9×/1× ; marquer jusqu'à cinq segments et leur cause `not_recognized | unknown_words | too_fast | meaning`.
3. **Réécoute sans texte** : `yes | partly | no` pour chaque segment marqué, indicateur local de séance uniquement.
4. **Restitution** : résumé oral ou écrit facultatif ; note locale (pas envoyée au Worker) ; bouton de copie d'un prompt contextualisé vers ChatGPT Live, sans API d'enregistrement.
5. **Mémorisation** : suggérer 0–2 chunks réellement utiles ; validation utilisateur facultative ; ne pas dupliquer un chunk déjà connu sans apporter un nouvel exemple pertinent.

**Adaptations simples** : si presque tout est compris et QCM réussi, parcours court ; si sons connus mais non identifiés, priorité aux boucles ; si presque rien n'est compris et QCM raté, extrait plus court, aides et éventuelle version adaptée. Proposer, ne jamais imposer. Éviter de conclure à une difficulté générale sur une seule question ratée.

**Lecture par segment** : HTTP `Range` en Worker, contrôle fin d'un segment via `requestAnimationFrame` pendant boucle, `timeupdate` pour surlignage ordinaire, marges de 120 ms, tolérance visée ±250 ms Safari iOS et ±100 ms Chrome desktop, à vérifier en recette. Suspendre la boucle hors lecture / écran inactif pour ménager batterie. Sécuriser la reprise locale d'une session interrompue (expiration indicative 24 h).

### 6.3 Lecture active

- Une ressource texte sans audio est immédiatement lisible.
- Premier passage **sans traductions ni glossaire affichés**, question éventuelle sur le sens global.
- Aide sur mots/chunks sélectionnés, explication de grammaire, traduction à la demande.
- Identifier 0–2 expressions utiles pour le SRS ; créer de préférence une carte existante enrichie plutôt qu'un doublon.
- Si disponible, écoute Kokoro de la variante pour entraîner ensuite la reconnaissance orale.
- Distinction nette des progrès **lecture** et **écoute** ; le texte lu ne constitue pas un test de première écoute inédit.

## 7. SRS et transfert différé

### 7.1 Compatibilité Lingvist/SRS

- Garder tables `words`, `word_progress` et les routes de promotion existantes.
- Ajout d'un canal de maîtrise audio et provenance des validations, sans réinitialiser les historiques.
- Déduplication : forme normalisée + langue + catégorie (et distinctions d'acception/contexte), sans fusionner automatiquement des quasi-synonymes suggérés par embeddings.
- État manuel « connu » = indice lexical ; réussite audio indépendante.
- Une expression peut posséder plusieurs exemples audio, avec source et révision ; les anciennes références restent fonctionnelles.

### 7.2 Génération ciblée des transferts

Ne **pas** synthétiser des tests pour tous les chunks. Après sélection d'une expression par l'apprenant :
- privilégier un élément de transfert déjà en cache ;
- sinon demander un exemple textuel inédit (DeepSeek/Gemini selon budget) via Worker, le valider et stocker ;
- pour son audio, **Kokoro local uniquement** dans la configuration initiale : soit petit pool de tests préproduits à l'atelier, soit génération différée à la prochaine ouverture de l'atelier ; jamais prétendre que le Worker peut joindre un Mac éteint ;
- si pas de nouvel audio à J+3, proposer la révision sur l'original marquée `same_context:true`, **non comptée comme transfert**, et inscrire le besoin d'audio neuf en attente. Aucune obligation de TTS payant.

### 7.3 Types de tests

- `meaning`: nouvelle phrase audio, choisir le sens ;
- `context`: nouvelle phrase audio, répondre à une question sur la situation ;
- `sound_form`: nouvelle phrase audio, identifier l'expression parmi trois formes écrites.

Sans texte avant la réponse, seconde écoute autorisée ; montrer correction ensuite. Recueillir confiance déclarée après coup (facultatif). J+3 et J+10 par défaut ; ne pas comptabiliser comme apprentissage généralisé un test `same_context`.

**Métriques séparées :** les deux premiers alimentent compréhension du sens ; le dernier reconnaissance sonore. Pas de score unique trompeur. Échec de transfert peut rendre la carte SRS due plus tôt sans effacer sa maîtrise écrite.

## 8. Worker Cloudflare, données et sécurité

### 8.1 Contrats minimaux proposés (à adapter après inspection du code)

```ts
type ContentSource = {
  id: string;
  kind: 'youtube' | 'audio_file' | 'article_url' | 'pasted_text' | 'personal_transcript';
  language: 'en' | 'fr';
  originalText: string;
  originalAudioKey?: string;
  sourceUrl?: string;
  sourceRevision: string;
};

type ContentVariant = {
  id: string;
  contentId: string;
  kind: 'faithful' | 'assisted_original' | 'adapted' | 'targeted_adaptation';
  parentVariantId?: string;
  levelTarget?: 'A2' | 'B1' | 'B1+' | 'B2' | 'custom';
  contentRevision: string;
  segmentationVersion: number;
  audioRevision?: string;
  audioOrigin?: 'original' | 'kokoro_tts';
  audioKey?: string;
  segments: Array<{ id: string; en: string; fr?: string; startMs: number | null; endMs: number | null; wordsPerMinute?: number }>;
  sectionMappings?: Array<{ sourceSegmentIds: string[]; targetSegmentIds: string[] }>;
};

type LearnerLexicalEvidence = {
  profileId: string;
  itemId: string;
  declaredKnown?: boolean;
  readingRecognition?: number;
  listeningRecognition?: number;
  meaningInContext?: number;
  source: string;
  observedAt: string;
};
```

Le contrat est **conceptuel** : inspecter le schéma existant avant de figer noms, nullabilité et clés. Favoriser une migration additive sans dupliquer inutilement tous les contenus dans D1 si `metadata` reste suffisant à court terme. Définir précisément la source de vérité entre métadonnées et tables normalisées.

### 8.2 HTTP et stockage audio

- `/audio/<key>` gère `Range: bytes=a-b`, `bytes=a-`, `bytes=-n`, renvoie `206` avec `Content-Range`, `Content-Length`, `Accept-Ranges`, et `416` sur plage invalide ; lecture partielle R2. Préserver comportement sans Range et prise en charge correcte HEAD/content-type.
- Clés R2 versionnées et immuables ; aucune clé mutable servie sous `immutable`.
- Table de références actives audio (`content`, `srs_card`, `transfer`) et marqueur `retired_at`; suppression différée par cron seulement si **aucune référence** et délai dépassé. Gestion atomique des changements de référence, des suppressions de contenu, des publications échouées et des cartes SRS supprimées.
- Route de retrait authentifiée, contrôle strict de propriété et de préfixe ; ne jamais accepter arbitrairement une clé appartenant à un autre contenu/profil.
- Migration/rétrocompatibilité : ancien audio `prepared-content/<id>.mp3` continue d'être lisible ; anciens contenus sans timing restent en écoute libre.

### 8.3 Séances, permissions et API

Étendre les sessions v1.1 : `profile_id, content_id, content_revision, variant_id, excerpt_start_ms, excerpt_end_ms, excerpt_wpm, audio_origin, path_variant, first_pass_rating, questions_total, questions_correct, marked_segments, retained_chunks, is_calibration, started_at, finished_at`.

Routes proposées :
- `POST/GET /listening/sessions` ; `GET /listening/stats` ;
- `POST /listening/promote-chunks` ;
- `GET/POST /listening/transfer-checks` ;
- nouvelles routes **uniquement après examen des conventions actuelles** : `GET /learner/lexical-profile`, `POST /content/assess`, `POST /content/adaptation-request`, `GET /content/:id/variants` ;
- traitement d'enrichissement IA via endpoint Worker authentifié, idempotent, cache et quota. Aucune IA requise pour consulter une ressource déjà publiée.

Exiger la correspondance `profileId` / identité authentifiée côté Worker ; le profil fourni par le client n'accorde aucune permission. Sessions idempotentes par ID unique, mises à jour conjointes des learning events ; journaliser coûts sans conserver inutilement des transcriptions personnelles dans les logs.

### 8.4 Contrôles IA

- Autorisation explicite pour envoyer un document personnel à un service externe ; option « local uniquement / manuel ».
- Limites de longueur et de budget (montants configurables, pas de tarifs codés en dur) ; clé par fournisseur ; repli et circuit breaker.
- Prompts versionnés ; sorties JSON structurées validées ; suppression des instructions dangereuses issues des contenus importés ; le texte source est une **donnée non fiable**, pas une instruction système.
- Audit léger : fournisseur, modèle, tokens, coût estimé, temps, erreurs, version du prompt, sans fuite de secrets.

## 9. Analyse de difficulté : implémentation par étapes

### Étape A (sans nouvelle IA en temps réel)

- Créer couverture lexicale estimée à partir du Lingvist/SRS existant ; déduplication simple ; grammaire et débit si disponibles.
- Étiquette *accessible / adapté / exigeant* accompagnée de raisons, **confiance faible** tant que pas d'écoute réelle.
- Première écoute et résultat QCM servent de vérité terrain provisoire ; ne pas surinterpréter un seul échec.

### Étape B (IA facultative dans l'atelier)

- Analyse par Gemini/DeepSeek pour expressions complexes, structures, jargon ; adaptation fidèle de passages demandés.
- Vérification humaine des adaptations à forte densité d'informations (nombres, science, finance).
- Prompts manuels compatibles pour toutes les tâches en mode hors API.

### Étape C (après observation)

- Recommandations basées sur les erreurs récurrentes et réussites par compétence ; le moteur de règles choisit l'objectif pédagogique, le LLM **ne décide pas seul** de progression.
- Embeddings Hugging Face locaux pour suggérer doublons/équivalences, jamais fusionner automatiquement des sens distincts.

## 10. Mesures et expérimentation de 28 jours

### 10.1 Indicateurs

1. **Compréhension sur extraits inédits** : réponses aux questions de sens *à la première écoute*, sans transcription ; principal.
2. **Transfert du sens à J+3/J+10** : nouvelle phrase/voix, types `meaning` et `context` ; principal.
3. **Reconnaissance sonore différée** : type `sound_form` ; séparé.
4. Auto-évaluation et calibration de confiance ; secondaire.
5. Reconnaissance après décodage ; mesure de séance, pas de maîtrise.
6. Couverture lexicale estimée et part de vocabulaire déclaré connu ; diagnostics, pas preuves de compréhension.

### 10.2 Protocole

- Préparer **au moins huit**, idéalement 12–16 extraits de contrôle authentiques, 1–2 min, de difficulté comparable et deux ou trois questions de sens chacun. Contrôler thème, débit, accent et difficulté lexicale ; ordre randomisé avant l'expérience.
- Ils ne sont jamais utilisés en écoute active, ni montrés en traduction, ni utilisés pour entraîner le SRS avant leur test.
- Quatre semaines : écoute active 5 jours/7 si tenable ; contrôles au début de séances répartis sur les semaines ; inclure des audios inédits à la fin.
- Noter autres activités (Lingvist, Live, exposition extérieure) et ressenti hebdomadaire ; éviter l'abandon pour surcharge.
- +15 points de réussite et taux de transfert à J+3/J+10 (70/60 %) peuvent servir **de repères exploratoires**, pas de seuils de preuve scientifique ; la faible taille et l'absence de contrôle ne permettent pas d'attribution causale.
- Différencier résultats par voix authentique et TTS ; mesurer aussi si l'usage de versions adaptées facilite **ensuite** la compréhension de l'original.

### 10.3 Décision après protocole

- Si progrès sur audios inédits et bonne adhésion : avancer sur SRS audio et personnalisation.
- Si progrès sur audios répétés mais pas inédits : travailler généralisation, voix diverses et contenu authentique.
- Si fatigue ou non-utilisation : simplifier parcours, ne pas imposer de tests sur tous les contenus.
- Si absence de signal clair : ne pas prétendre que la méthode échoue ; ajuster et répéter l'observation avant d'investir dans un moteur complexe.

## 11. Roadmap de développement et dépendances

### LOT 0 — Audit et protection de l'existant (bloquant pour toutes migrations)

- Inventorier fichiers, API, schémas D1, contrats metadata, routes de SRS et profils, volumes, lecteurs et versionnement.
- Cartographier le pipeline Studio déjà en place et ne modifier que les étapes nécessaires.
- Écrire tests de non-régression pour contenu historique, SRS/Lingvist, Live, lecture libre, audio FR/EN.
- Définir une convention unique pour `sourceRevision`, `contentRevision`, `variantId`, `audioRevision` et références.

### LOT 1 — Sources multiples + fondations audio

- Import texte collé, `.txt`, `.md`, article et transcription personnelle ; détection/confirmation langue ; types de contenu.
- Pipeline de référence commun (audio -> MacWhisper SRT ; texte -> segmentation) ; traduction fidèle via API facultative ou collage manuel ; Kokoro facultatif pour textes.
- Horodatage Kokoro par variante, SRT originaux, validations, clés R2 versionnées, requêtes Range, maintien anciens contenus.
- Lecteur source, texte et audio s'il existe, avec lecture libre intacte.
- Tests EA et tests d'import, y compris texte sans audio.

### LOT 2 — Profil lexical + première estimation Comprehensible Input

- Réutiliser validations Lingvist et SRS ; construire représentation des connaissances **écrit vs oral**.
- Couverture lexicale indicative, repérage de chunks, explications des difficultés, étiquettes explicables.
- UI « original / avec aide » ; suggestion d'adaptation non bloquante.
- Mesure indépendante des niveaux de compréhension écrite et orale.

### LOT 3 — Écoute active et lecture active

- Parcours cinq phases avec variantes adaptatives simples et reprise ; lecteur segmenté ; diagnostic ; restitution Live facultative.
- Lecture active sans exigence de piste TTS ; 0–2 chunks vers SRS ; idempotence.
- Protocole de contrôle initial prêt avant première campagne de 28 jours.

### LOT 4 — Adaptation fidèle ciblée + versions audio

- Adaptation complète ou passage sélectionné depuis l'atelier ; mode `assisted_original` en priorité.
- Vérification de fidélité, niveaux cibles indicatifs, mapping original/adapté ; ne pas faire correspondre artificiellement deux timelines.
- Audio Kokoro pour variante, nouvelles révisions et visualisation des correspondances ; pas de création automatique de tous les niveaux.

### LOT 5 — Transfert différé et expérience de 28 jours

- Tests de transfert textuels ciblés ; pool Kokoro local ou génération différée dans l'atelier ; audit des ressources manquantes.
- Vérifications à J+3/J+10, scores de sens et reconnaissance distincts ; gestion SRS et références audio.
- Contrôles inédits, protocole 28 jours, recueil ressenti et analyse.

### LOT 6 — Consolidation, uniquement après observation

- SRS audio d'abord, statistiques détaillées et recommandations contextuelles ; embeddings locaux en option.
- Tests de performance/modèles HF sur Mac Intel uniquement si l'amélioration attendue justifie la complexité.
- Version plus élaborée du moteur de progression sans rendre toute interaction dépendante d'un LLM.

**Ordre partiellement ajustable** : les fonctions d'adaptation peuvent être livrées avant la totalité du lot 3 si elles répondent à un blocage ; toutefois les fondations audio, la gestion des variantes et la rétrocompatibilité doivent précéder les fonctionnalités qui s'y appuient.

## 12. Critères d'acceptation prioritaires

| ID | Scénario | Résultat attendu |
|---|---|---|
| EF-01 | Import article EN collé | Source EN conservée, lecture possible immédiatement, audio facultatif |
| EF-02 | Import article FR | Source FR conservée, traduction EN **fidèle** distincte de l'adaptation |
| EF-03 | Import transcription personnelle EN | Original, correction et reformulation restent distinguables |
| EF-04 | Import YouTube EN | Audio authentique + texte EN horodaté conservés |
| EF-05 | Import audio FR | Audio source conservé ; Kokoro anglais synchronisé à **sa propre** transcription |
| EF-06 | Texte sans piste audio | Lecture active possible, écoute active indisponible sans crash |
| EF-07 | Source B2/C1 mais sens compris | Aides ciblées proposées avant réécriture complète |
| EF-08 | Génération d'une adaptation B1+ | Source intacte, chiffres/noms/nuances préservés, niveau cible affiché comme indicatif |
| EF-09 | Adaptation de 2 paragraphes uniquement | Aucune altération de la source entière ; lien de sections vers l'original |
| EF-10 | Utilisateur valide mot connu dans Lingvist | Signal `declaredKnown` actualisé ; aucune maîtrise audio inventée |
| EF-11 | Utilisateur échoue à reconnaître un mot connu à l'écrit | Diagnostic audio et révision auditive proposés, maîtrise écrite préservée |
| EF-12 | Audio absent ou API IA indisponible | Contenu déjà publié reste lisible ; flux manuel de secours disponible |
| EF-13 | Assistant IA produit JSON invalide ou hors contexte | Rejet explicite, données valides existantes intactes |
| EF-14 | Annotation phonétique non écoutée par humain | `verified=false`, affichage « Souvent prononcé... » |
| EF-15 | Lecture boucle segment sur Safari iPhone | Réponse Range 206 ; positionnement vérifié selon tolérance v1.1 |
| EF-16 | Republier un audio | Nouvelle clé immuable ; cartes SRS continuent d'utiliser anciennes références actives |
| EF-17 | Suppression d'un contenu avec cartes SRS | Ressources audio nécessaires aux cartes conservées |
| EF-18 | Séance interrompue puis reprise | Reprise locale correcte sans doubler les événements Worker |
| EF-19 | Retenir zéro chunk | Séance terminée sans créer d'entrée SRS |
| EF-20 | Transfert sur audio d'origine uniquement | `same_context=true`, exclu de la métrique de transfert |
| EF-21 | Test de forme sonore réussi et sens échoué | Statistiques séparées, pas de « compréhension réussie » globale |
| EF-22 | Extrait de contrôle inédit | Jamais exposé pendant entraînement, question comptée à première écoute seulement |
| EF-23 | Demande d'adaptation depuis PWA avec Mac éteint | Indiquer demande différée ou indisponibilité, ne pas feindre une génération immédiate |
| EF-24 | Absence de clé API ou quota dépassé | Ni fuite de secret ni erreur bloquante dans la lecture/les séances |
| EF-25 | Avant déploiement Worker/PWA | Accord explicite demandé, aucun déploiement implicite |
| EF-26 | Ancien contenu sans timings | Lecture classique intacte, pas de bouton écoute active |

## 13. Tests techniques obligatoires

- Tests unitaires Python : segmentation SRT, extraction texte, lemmatisation approximative, horodatage Kokoro, empreintes de versions, validation JSON, fidélité des références/IDs.
- Worker : Range (suffixe, ouvert, fin incluse, erreur 416, HEAD), auth de profil, quotas IA, contenu non fiable, idempotence des séances, conservation/nettoyage R2, suppression de contenu, ancien cache.
- Front : écoute/lecture sans audio, bascule original/adapté, aucun saut de timing entre deux versions, reprise de séance, affichage phonétique vérifié/non vérifié, diagnostics sans réponse, accessibilité clavier et mobile.
- Validation humaine : 10 extraits audio Safari iOS + 10 Chrome, 10 articles EN/FR, 5 textes personnels, 5 variantes adaptées avec vérification des chiffres et nuances.
- Tests d'intégration : déclencher création SRS, republier variante, supprimer contenu original, vérifier que la révision audio continue à fonctionner.

## 14. Questions de réalisation à résoudre par audit (ne pas improviser)

1. Comment les profils/auth sont-ils actuellement reliés à `word_progress` et aux contenus ?
2. Le Worker peut-il réutiliser `metadata` sans migrations volumineuses, ou faut-il une table `content_variants` ?
3. Quelle limite légale et technique pour les fichiers et articles importés ?
4. Quelle option pour demander depuis la PWA une adaptation lorsque le Mac est éteint ? Première version : demande différée seulement, sauf si un TTS distant gratuit/autorisé est décidé ultérieurement.
5. Quel mécanisme de publication atomique évite les métadonnées pointant vers des fichiers R2 non encore présents ?
6. Quels modèles Gemini/DeepSeek/OpenRouter sont effectivement accessibles avec les clés/crédits, quotas et règles de confidentialité de l'utilisateur ? **Vérifier avant de fixer les modèles ou les prix.**
7. Quel format exact des chunks, des révisions et des cartes existantes permet une déduplication sans régression ?

Les questions ci-dessus sont des points **d'audit d'implémentation**, pas des demandes de revalidation de la vision produit. L'agent doit examiner le code, prendre la voie la moins destructive et consigner les choix.

## 15. Instruction finale pour l'agent de développement

> **Mission :** implémenter English Fluency 2.0 par lots en partant des trois dépôts existants, en conservant l'ensemble des fonctionnalités actuelles. Lire d'abord ce cahier ET le cahier `CAHIER_DES_CHARGES_ECOUTE_ACTIVE(1).md` pour conserver les détails d'interface et les règles de lecture/audio déjà spécifiées. Auditer le code avant de figer noms de routes, tables et composants ; ne jamais inventer un contrat existant.
>
> **Ordre :** commencer par LOT 0 et LOT 1, tests de non-régression en premier ; ensuite construire le profil lexical, l'écoute/lecture active, l'adaptation fidèle, et le transfert différé. Faire un bilan technique et pédagogique à chaque fin de lot.
>
> **Règles :** conserver les contenus sources, rendre les adaptations facultatives, générer une seule variante utile plutôt que tous les niveaux, respecter les timelimes audio indépendantes, distinguer lexique écrit et oral, ne pas considérer les déclarations comme preuves. Préférer MacWhisper et Kokoro en local ; Gemini/DeepSeek/OpenRouter optionnels et sécurisés ; HF local seulement lorsque pertinent.
>
> **Qualité :** TypeScript/Python typés, schémas explicites, erreurs gérées, tests pour chaque migration/API, support iPhone Safari, UI mobile sobre, mode dégradé hors IA, documentation `.env.example` sans secret, commandes de test et plan de retour arrière.
>
> **Déploiement :** aucune publication Worker ni PWA sans consentement explicite. Ne jamais supprimer une clé audio R2 encore référencée.

---

### Annexe A — Lien avec la spécification v1.1

Les exigences de la v1.1 qui restent applicables sont maintenues : diagnostic en quatre causes ; cinq phases ; variantes de parcours `reference | quick | decoding | supported` ; tests de transfert `meaning | context | sound_form` ; `verified:false` des prononciations ; `segmentationVersion` et `contentRevision` ; tables/événements d'écoute ; Range 206/416 ; versionnement et références audio ; protocole exploratoire de 28 jours ; compatibilité des anciens bundles. **En cas de contradiction, le présent document prévaut**, en particulier pour les sources textuelles, la génération des adaptations, la prise en compte Lingvist et l'utilisation des services IA.

### Annexe B — Exemples de décision

- **YouTube EN C1, sujet très intéressant, idées principales comprises :** conserver audio authentique ; proposer aide ciblée ; aucune adaptation automatique.
- **YouTube EN C1, presque rien compris :** créer une version B1/B1+ fidèle avec Kokoro, puis comparer des passages sélectionnés avec l'original ; garder le C1 accessible.
- **Article FR de science :** traduire fidèlement EN, lecture EN/FR ; voix Kokoro facultative ; adaptation seulement si compréhension insuffisante.
- **Ma journée en anglais, texte dicté :** conserver transcription brute ; générer version corrigée (sans réinventer les faits) et reformulation naturelle ; écouter la correction avec Kokoro ; remonter difficultés utiles vers SRS.
- **Mot validé Lingvist, échec à l'écoute :** conserver la maîtrise écrite ; entraîner reconnaissance orale au lieu de répéter une traduction déjà maîtrisée.
