# Cahier des charges — Refonte de l’Atelier English Fluency (Mac)

**Version :** 1.0 — 16 octobre 2026  
**Statut :** spécification fonctionnelle et technique cible, à confronter au dépôt existant avant implémentation  
**Produit concerné :** application Mac de préparation de contenus pour l’application mobile EnglishFluency  
**Principe directeur :** conserver l’existant, supprimer les doublons, fiabiliser le pipeline et automatiser la publication.

---

## 1. Contexte et objectifs

### 1.1 Fonctionnement actuel observé

L’application Mac permet actuellement de :
- saisir plusieurs liens YouTube (un par ligne) ;
- extraire les pistes audio et produire une transcription ;
- choisir la langue source, un traitement, un niveau cible et éventuellement un thème ;
- suivre des jobs et retrouver les bundles dans `fileToImport/` ;
- préparer des prompts à copier dans ChatGPT, coller les réponses et enregistrer les résultats ;
- générer un deuxième fichier audio anglais à l’aide du TTS Kokoro, notamment avec une voix britannique ;
- prévisualiser le payload et importer vers Cloudflare.

L’interface présente deux sections, **Conversion rapide** et **Atelier English Fluency**. La première doit disparaître. L’atelier devient l’unique point d’entrée.

### 1.2 Objectif produit

Transformer une vidéo initialement **française ou anglaise** en **bundle pédagogique bilingue**, publiable dans EnglishFluency et comprenant obligatoirement :

1. un **audio d’apprentissage en anglais** ;
2. le **texte intégral anglais** ;
3. le **texte intégral français** ;
4. des **chunks pertinents** (expressions, collocations, phrasal verbs, vocabulaire difficile, formulations réutilisables) ;
5. des **explications grammaticales ciblées** lorsque le contenu en justifie ;
6. des **métadonnées** et un état de publication vérifiable.

L’atelier reste une application de **production / contrôle / publication**. Le lecteur, les exercices et le SRS restent du ressort de l’application mobile.

### 1.3 Public et politique pédagogique

- Apprenant francophone de niveau **A2+**, progressant vers **B1**, avec exposition mesurée à des éléments **B2**.
- Anglais de référence : **britannique (`en-GB`)**, sans altérer la fidélité du sens.
- Traductions **complètes**, sans résumé ni omission.
- Explications pédagogiques **en français**, claires et contextualisées, sans multiplier les annotations inutiles.
- Le **résumé** est facultatif et ne doit jamais remplacer les textes intégraux ni bloquer la publication.

## 2. Périmètre

### 2.1 Inclus dans cette refonte (P0)

- Suppression de l’onglet « Conversion rapide » et recentrage de l’interface sur l’atelier.
- Préservation des fonctions existantes d’extraction, transcription, génération Kokoro, prompts, jobs et import.
- Deux parcours explicites et une sortie pédagogique commune.
- Prompts ChatGPT distincts pour les traductions FR→EN, EN→FR et l’analyse pédagogique.
- Validation structurée des réponses collées depuis ChatGPT.
- Sélection déterministe de **l’audio anglais** à publier.
- Déclenchement automatique de l’import après génération TTS réussie **si** tous les prérequis sont satisfaits.
- Statuts cohérents, reprise sur erreur, prévention des doublons et compatibilité des anciens bundles.

### 2.2 Évolutions prévues ensuite (P1/P2)

- **P1 :** alignement audio/texte, horodatage et surlignage des segments en lecture mobile.
- **P1 :** édition et republication partielles, historique de révisions.
- **P2 :** exploitation automatique des chunks dans les révisions SRS et les exercices mobiles.
- **Hors périmètre initial :** suppression de l’étape manuelle ChatGPT via API payante, création d’un lecteur audio élaboré dans l’application Mac, refonte complète du backend Cloudflare, modification des moteurs d’extraction/TTS si ceux-ci fonctionnent déjà.

## 3. Règles fondamentales

| Règle | Comportement attendu |
|---|---|
| Audio systématiquement anglais côté mobile | Ne jamais publier l’audio français comme audio d’apprentissage. |
| Audio original conservé | Ne jamais écraser ni supprimer l’audio source lors d’un TTS. |
| Source FR | Transcription FR → traduction EN → analyse pédagogique EN → génération Kokoro EN → import. |
| Source EN | Transcription EN → traduction FR → analyse pédagogique EN → import de l’audio EN original. |
| Texte bilingue complet | Les deux textes sont obligatoires et fidèles. |
| Validation avant publication | « Prêt à importer » n’apparaît que si `canPublish === true`. |
| ChatGPT manuel | Les réponses sont copiées/collées puis validées ; aucune obligation d’API LLM. |
| Publications fiables | Un retry ne doit ni créer de doublon ni publier un bundle partiel. |
| Changements de texte | Modifier l’anglais rend obsolètes le TTS associé (source FR) et les analyses dépendantes. |

## 4. Parcours métier détaillés

### 4.1 Vidéo source française

1. L’utilisateur colle une ou plusieurs URL YouTube, puis lance la préparation.
2. L’application télécharge/extrait l’audio **français original** et le conserve localement.
3. La transcription FR est produite ; l’utilisateur peut la corriger.
4. Le bouton **Copier le prompt de traduction FR → EN** fournit le texte à utiliser dans ChatGPT.
5. L’utilisateur colle la traduction anglaise produite ; l’application la valide et l’enregistre.
6. L’utilisateur lance le **prompt d’analyse pédagogique** sur le **texte anglais définitif**, puis colle et valide le JSON.
7. L’utilisateur choisit la voix britannique et déclenche **Générer l’audio anglais (Kokoro)**.
8. L’application crée **un second fichier audio anglais**, sans écraser l’audio FR.
9. À la fin du TTS, l’application vérifie l’intégrité de l’audio et tous les prérequis.
10. Si `autoPublish = true` et `canPublish = true`, l’import Cloudflare commence automatiquement ; sinon le bundle reste en attente d’action/validation.
11. Après confirmation serveur, le bundle passe à **Publié** ; un identifiant/version distante est enregistré.

**Point important :** une transcription FR n’est jamais utilisée comme entrée Kokoro pour le fichier publié. Kokoro lit exclusivement la version anglaise validée.

### 4.2 Vidéo source anglaise

1. Extraction et conservation de l’audio anglais original.
2. Transcription en anglais et correction facultative.
3. Génération du prompt **EN → FR**, collage et validation de la traduction française intégrale.
4. Génération du prompt d’analyse pédagogique à partir du texte anglais original validé, puis collage et validation du JSON.
5. L’audio anglais original est sélectionné pour publication ; **aucun TTS requis**.
6. Dès que le bundle est complet, l’import peut se déclencher automatiquement (si l’option est activée) ou rester manuel.

### 4.3 Lots de plusieurs URL

- Chaque URL génère un job et un bundle **isolés**.
- Un échec sur une vidéo n’empêche pas les autres d’avancer.
- Les opérations encore manuelles (ChatGPT, corrections) restent attachées au bon bundle.
- Les publications simultanées sont limitées pour éviter la saturation locale/réseau ; la limite doit être configurable.
- À titre de sécurité, les URL en double sont détectées et l’utilisateur choisit de réutiliser ou régénérer le contenu.

## 5. Interface utilisateur cible

### 5.1 Page d’accueil — Atelier unique

Supprimer la navigation à deux onglets. L’écran principal comporte trois zones :

**A. Ajouter des contenus**
- Champ multiligne « Liens YouTube — un par ligne ».
- Langue source : **Auto (par défaut)**, Français, Anglais ; permettre une correction si la détection est incorrecte.
- Niveau cible : A2+, B1, B2 (B1 par défaut possible selon l’usage actuel).
- Thème facultatif.
- Option **« Publier automatiquement dès que le bundle est prêt »** (valeur mémorisable).
- Bouton principal **Préparer les contenus**.

**B. Bibliothèque de préparation / jobs**
- Liste compacte par contenu : titre, langue source, durée si disponible, progression, statut réel, dernière action nécessaire.
- Recherche et filtres : Tous, À compléter, En cours, En erreur, Publiés.
- Bouton **Ouvrir l’atelier** pour les détails ; ne pas afficher d’énormes prompts en permanence.

**C. Bibliothèque publiée**
- Titre, date et version publiée, état Cloudflare, possibilité de consulter un aperçu ou de republier.

### 5.2 Détail d’un bundle

Présenter un parcours guidé en cinq étapes :

1. **Source & transcription** : lecteur local simple si déjà disponible, texte transcrit, édition et validation.
2. **Traduction bilingue** : prompt adapté au sens, bouton copier, collage du résultat, aperçu EN/FR, validation.
3. **Analyse pédagogique** : prompt chunks + grammaire, collage JSON, erreurs de validation, édition/suppression d’éléments, validation.
4. **Audio anglais** : audio original EN ou création Kokoro EN ; préécoute, voix, statut.
5. **Publication** : checklist, payload, import et état distant.

Actions visibles uniquement lorsqu’elles sont pertinentes : **Copier prompt**, **Coller résultat**, **Valider**, **Générer audio EN**, **Publier / Republier**, **Réessayer**.

### 5.3 Statuts et progression

Séparer **statut de traitement** et **état de publication**. Prévoir notamment :

- `extracting`, `transcribing`, `awaiting_translation`, `awaiting_pedagogy`, `generating_tts`, `ready_to_publish`, `publishing`, `published`, `failed` ;
- une raison explicite quand le bundle est bloqué : « Traduction anglaise manquante », « Analyse pédagogique non validée », « Audio EN en cours de génération », etc. ;
- un `lastError`, horodatage et une action **Réessayer** ciblée ;
- aucun statut vert « Prêt à importer » tant qu’il manque une dépendance.

Les badges de validation doivent montrer distinctement : **audio EN**, **texte EN**, **texte FR**, **chunks/grammaire**, **métadonnées**, **publication**. L’original FR conservé n’est pas compté comme « audio EN prêt ».

## 6. Prompts ChatGPT — règles et contrats

Les prompts restent générés localement et copiables. Chaque retour doit être validé avant sauvegarde. Utiliser un **JSON strict** pour rendre l’import fiable, sans Markdown ni texte extérieur.

### 6.1 Préparation des segments

- Découper idéalement le texte en **unités de traduction cohérentes** (phrase ou petit groupe de phrases), identifiées par `segmentId` stable : `s001`, `s002`, etc.
- Conserver l’ordre et la correspondance des ID entre français et anglais.
- Pour les longues vidéos, découper en lots en gardant du contexte adjacent afin de préserver la cohérence ; vérifier que **tous** les segments sont présents avant validation.
- Ne pas imposer à l’utilisateur de recopier manuellement les ID : le prompt les intègre automatiquement.

### 6.2 Prompt de traduction FR → EN

```text
Tu es un traducteur professionnel et professeur d'anglais britannique.
Traduis intégralement les segments français en anglais britannique naturel.
Conserve le sens, les faits, le registre, l'ordre des idées et les nuances.
N'ajoute rien, n'omets rien, ne résume pas. Ne simplifie pas artificiellement les informations.
Conserve chaque id et l'ordre des segments. N'invente aucun segment.
Retourne uniquement un JSON valide, sans Markdown :
{
  "segments": [
    {"id": "s001", "text": "Traduction anglaise correspondante"}
  ]
}
Segments français :
{{SEGMENTS_FR_JSON}}
```

### 6.3 Prompt de traduction EN → FR

```text
Tu es un traducteur professionnel.
Traduis intégralement les segments anglais en français naturel, courant et fidèle.
Conserve le sens, les faits, le registre, l'ordre des idées et les nuances.
N'ajoute rien, n'omets rien, ne résume pas.
Conserve chaque id et l'ordre des segments. N'invente aucun segment.
Retourne uniquement un JSON valide, sans Markdown :
{
  "segments": [
    {"id": "s001", "text": "Traduction française correspondante"}
  ]
}
Segments anglais :
{{SEGMENTS_EN_JSON}}
```

### 6.4 Prompt d’analyse pédagogique (commun aux deux parcours)

```text
Tu es un professeur d'anglais britannique spécialisé dans l'enseignement aux francophones A2+/B1.
Analyse UNIQUEMENT les segments anglais fournis.
Sélectionne les éléments les plus utiles, sans chercher à remplir artificiellement un quota.
Pour un extrait court, extrais jusqu'à 12 chunks ; pour un document long, le traitement
peut être effectué par sections. Favorise : vocabulaire difficile, faux amis,
collocations, phrasal verbs, expressions idiomatiques et structures réutilisables.
Repère séparément jusqu'à 4 points grammaticaux réellement illustrés dans le texte.
Pour chaque élément, indique un segmentId existant. N'invente pas de citation source.
Les explications et traductions sont en français naturel. Les exemples anglais sont courts,
idiomatiques et cohérents avec un anglais britannique.
Niveaux autorisés : A2, B1, B2. Types autorisés : vocabulary, collocation,
phrasal_verb, idiom, useful_expression, grammar_pattern.
Retourne uniquement ce JSON valide :
{
  "chunks": [
    {
      "id": "c001",
      "expression": "figure out",
      "meaningFr": "comprendre, trouver",
      "exampleEn": "I can't figure it out.",
      "exampleFr": "Je n'arrive pas à comprendre.",
      "level": "B1",
      "type": "phrasal_verb",
      "context": "Lorsque l'on cherche à comprendre un problème",
      "explanationFr": "Figure out signifie comprendre ou trouver une solution.",
      "sourceSegmentId": "s001"
    }
  ],
  "grammarPoints": [
    {
      "id": "g001",
      "title": "Need to + infinitif",
      "explanationFr": "Cette construction sert à exprimer une nécessité.",
      "sourceExcerpt": "We need to understand this.",
      "exampleEn": "You need to check the details.",
      "exampleFr": "Tu dois vérifier les détails.",
      "level": "A2",
      "sourceSegmentId": "s001"
    }
  ]
}
Si aucun point grammatical pertinent ne ressort, renvoie "grammarPoints": [].
Segments anglais :
{{SEGMENTS_EN_JSON}}
```

**Note :** les exemples dans le prompt décrivent un **schéma**, pas des valeurs à reproduire. À l’implémentation, préférer un modèle de JSON Schema fourni et une validation stricte côté application. Les `id` des chunks peuvent être attribués ou normalisés par l’application.

## 7. Contrat de données local

### 7.1 Arborescence cible indicative

Adapter les noms à la structure existante, sans migration destructive :

```text
fileToImport/
  <bundle-id>/
    audio_original.mp3          # FR ou EN selon la source
    audio_en.mp3                # créé seulement pour une source FR
    transcript_fr.txt           # texte français intégral
    transcript_en.txt           # texte anglais intégral
    segments.json               # alignement textuel EN/FR
    pedagogy.json               # chunks et points de grammaire
    meta.json                   # manifeste, provenance, états et versions
```

Pour une source EN, `audio_original.mp3` est l’audio publié ; pour une source FR, `audio_en.mp3` est l’audio publié. Le nom **logique** `publishAudioFile` détermine toujours le fichier sélectionné.

### 7.2 Exemple de `meta.json` (version cible indicative)

```json
{
  "schemaVersion": 2,
  "bundleId": "youtube-videoid-001",
  "title": "Pourquoi la CAN va repasser tous les deux ans ?",
  "sourceUrl": "https://www.youtube.com/watch?v=VIDEO_ID",
  "sourceLanguage": "fr",
  "learningLanguage": "en",
  "targetLocale": "en-GB",
  "targetLevel": "B1",
  "files": {
    "originalAudioFile": "audio_original.mp3",
    "publishAudioFile": "audio_en.mp3",
    "transcriptEnFile": "transcript_en.txt",
    "transcriptFrFile": "transcript_fr.txt",
    "segmentsFile": "segments.json",
    "pedagogyFile": "pedagogy.json"
  },
  "translationValidated": true,
  "pedagogyValidated": true,
  "autoPublish": true,
  "englishTextRevision": 2,
  "ttsGeneratedFromEnglishRevision": 2,
  "publication": {
    "status": "ready_to_publish",
    "remoteId": null,
    "remoteVersion": null,
    "publishedAt": null
  }
}
```

**Sécurité :** ne jamais inclure dans le payload publié les chemins locaux absolus, les tokens d’authentification, les logs techniques ou les fichiers audio français non destinés à l’application mobile. Prévoir un manifeste local et un payload distant distincts.

### 7.3 Exemple simplifié de `segments.json`

```json
{
  "segments": [
    {
      "id": "s001",
      "en": "We need to figure out what went wrong.",
      "fr": "Nous devons comprendre ce qui s'est mal passé.",
      "startMs": null,
      "endMs": null
    }
  ]
}
```

`startMs` / `endMs` représentent **l’audio anglais publié**, jamais les positions de l’audio original français. Ces valeurs peuvent être `null` dans P0 ; elles seront remplies par alignement dans P1.

### 7.4 Validation des contenus

Utiliser un schéma de validation typé (par exemple Zod côté TypeScript) pour vérifier :
- `sourceLanguage ∈ {fr,en}` et `targetLocale = en-GB` ;
- deux textes non vides et segments intégralement appariés ;
- chaque chunk possède une expression, un sens français, un niveau autorisé, un type connu et une référence de segment valide ;
- `grammarPoints` est un tableau pouvant être vide ;
- les JSON collés sont parsables, sans champs inattendus critiques ;
- les fichiers déclarés existent et les médias publiables sont non vides/lisibles ;
- le TTS, quand requis, correspond bien à la dernière révision du texte anglais.

## 8. Publication Cloudflare et automatisation

### 8.1 Préconditions de publication

La fonction centrale `canPublish(bundle)` doit retourner `true` seulement si :

```text
- métadonnées valides ;
- texte anglais présent et validé ;
- texte français présent et validé ;
- segments bilingues cohérents ;
- pédagogie analysée et validée (chunks, éventuels points grammaticaux) ;
- audio anglais de publication présent, lisible et à jour ;
- aucun import identique déjà en cours ;
- aucune erreur bloquante non résolue.
```

La validation pédagogique peut accepter une liste vide de chunks **si** l’analyse a réellement été effectuée, validée et jugée sans élément pertinent : éviter tout quota artificiel.

### 8.2 Déclencheurs

**Source FR :** à la réussite de `generateEnglishTts`, réévaluer `canPublish`. Si `autoPublish` est activé, démarrer l’import. Si la traduction ou la pédagogie n’a pas encore été validée, rester en attente et déclencher l’import lorsque le dernier prérequis sera validé.

**Source EN :** ne pas attendre de TTS. Dès validation du dernier prérequis, lancer l’import si `autoPublish` est activé.

L’utilisateur conserve un bouton **Publier maintenant** et la possibilité de désactiver l’auto-publication.

### 8.3 Opération d’import

1. Préparer un payload distant à partir du manifeste local et du contenu validé.
2. Résoudre `publishAudioFile` et **refuser explicitement** une source FR si le fichier sélectionné est l’audio original français.
3. Réutiliser autant que possible le mécanisme Cloudflare actuel (API d’import et schéma existants), après audit.
4. Envoyer uniquement l’audio anglais et les données nécessaires ; si l’infrastructure est R2 + D1, stocker l’audio dans R2 et les métadonnées/contenus dans D1, en cohérence avec le backend réel.
5. Créer ou mettre à jour le contenu distant en utilisant `bundleId` et `contentRevision` comme base d’idempotence.
6. Ne marquer **Publié** qu’après confirmation de tous les éléments indispensables.
7. Conserver `remoteId`, `remoteVersion`, `publishedAt`, le statut et les erreurs éventuelles.

Si l’API distante ne propose pas d’opération atomique, utiliser un état temporaire non visible en mobile, puis une étape finale d’activation après contrôle de complétude.

### 8.4 Pseudo-code illustratif

```ts
async function afterBundleChanged(bundleId: string) {
  const bundle = await repository.get(bundleId);
  const readiness = await validatePublicationReadiness(bundle);
  await repository.saveReadiness(bundleId, readiness);

  if (!readiness.ok || !bundle.autoPublish) return;
  await publishWithIdempotency(bundleId);
}

async function onEnglishTtsCompleted(bundleId: string, audioPath: string) {
  await repository.registerEnglishAudio(bundleId, audioPath);
  await afterBundleChanged(bundleId);
}
```

Appeler également `afterBundleChanged` après une **validation de traduction**, une **validation pédagogique** et la correction d’une erreur bloquante. Les changements de statut doivent être persistés et ne pas dépendre uniquement de l’état React.

### 8.5 Gestion des erreurs et des reprises

- Import réseau interrompu : afficher **Échec de publication**, conserver tous les fichiers et proposer **Réessayer l’import**.
- TTS interrompu : reprendre la génération TTS uniquement, pas l’extraction YouTube.
- JSON ChatGPT invalide : afficher les erreurs de validation ; ne pas écraser la dernière version valide.
- Modification du texte anglais : marquer l’analyse comme **à revalider** et, pour une source FR, le fichier TTS comme **obsolète** jusqu’à régénération.
- Modification du texte français seul : ne pas régénérer inutilement l’audio EN ; mettre à jour la version du contenu.
- Double clic / multi-jobs : protéger par verrou ou identifiant de requête afin d’éviter deux imports simultanés du même bundle.
- Un ancien contenu déjà publié peut être republié en nouvelle version, sans créer systématiquement une deuxième fiche mobile.

## 9. Qualité linguistique et pédagogique

### 9.1 Traductions

- Exhaustives, naturelles, fidèles au contenu et au registre.
- Pas de conversion en résumé, pas d’ajout inventé, pas de simplification non demandée.
- Les noms propres, chiffres, dates et concepts techniques doivent être conservés correctement.
- Prévisualisation côte à côte EN/FR et édition avant validation finale.

### 9.2 Chunks

- Sélection par **utilité** pour A2+/B1, pas uniquement par difficulté objective.
- Types : `vocabulary`, `collocation`, `phrasal_verb`, `idiom`, `useful_expression`, `grammar_pattern`.
- Priorité aux unités réutilisables et aux ambiguïtés de sens en contexte.
- Chaque chunk doit pouvoir renvoyer à un segment du texte anglais.
- Les explications grammaticales sont séparées des chunks, mais peuvent être liées aux mêmes segments.
- Jusqu’à 12 chunks sur un extrait court est un **maximum indicatif**, pas une obligation ; pour les longs audios, analyser plusieurs sections, dédoublonner puis classer.

### 9.3 Voix et audio

- Par défaut : voix anglaise britannique disponible dans Kokoro (par exemple Emma GB si elle est réellement installée).
- Préécoute du TTS et régénération possibles.
- Conserver le texte anglais exact utilisé pour synthétiser l’audio, ou son empreinte de version.
- Veiller à la prononciation des noms propres, acronymes et nombres ; toute correction du texte de synthèse doit rester cohérente avec le texte affiché.

## 10. Compatibilité, architecture et contraintes techniques

### 10.1 Préserver l’existant

Avant toute modification, réaliser un audit ciblé du dépôt :
- framework UI et structure des écrans/onglets ;
- services YouTube, transcription et Kokoro ;
- schémas `meta.json`, noms des fichiers et structure de `fileToImport/` réellement utilisés ;
- interface d’import Cloudflare et schéma attendu par EnglishFluency mobile ;
- persistance des jobs et statuts, comportement de reprise ;
- rôle exact des anciennes notions « adaptation », « traduction », « résumé » et « prêt à importer ».

**Ne pas inventer ou renommer les endpoints existants.** Construire un adaptateur/migrateur léger si le nouveau format doit cohabiter avec des bundles historiques.

### 10.2 Principes d’implémentation

- Centraliser la logique dans un **service de pipeline** et un **validateur métier** ; éviter des conditions éparpillées dans les composants UI.
- Définir des types pour les contenus, statuts, fichiers et versions.
- Utiliser des écritures de fichiers sûres (fichier temporaire, validation puis renommage) afin de ne pas corrompre le bundle.
- Associer chaque action asynchrone à `bundleId` et tracer les événements utiles sans exposer de secrets.
- Définir explicitement les permissions d’accès à la route d’import et protéger les clés Cloudflare ; ne pas placer de jeton privé dans un payload client public.
- Prévoir des timeouts, annulations et relances ciblées pour les traitements audio longs.
- Éviter de re-télécharger/retranscrire si les artefacts validés existent et sont inchangés.

### 10.3 Alignement temporel (P1)

- Ne pas recycler les timestamps de l’original FR pour l’audio synthétique EN.
- Après TTS FR→EN, recalculer les alignements à partir du nouveau fichier EN (forced alignment ou autre méthode vérifiable).
- Pour une source EN, réutiliser les timings issus de la transcription seulement s’ils correspondent exactement au fichier audio publié.
- L’absence de timings ne bloque pas P0 si l’application mobile accepte des segments sans horodatage.

### 10.4 Droits d’usage

Le pipeline doit être employé avec des vidéos et des audios que l’utilisateur est autorisé à récupérer, transformer et republier. Ne pas présumer que la disponibilité publique d’une vidéo YouTube autorise automatiquement sa redistribution audio.

## 11. Critères d’acceptation (tests de recette)

| ID | Scénario | Résultat attendu |
|---|---|---|
| AC-01 | Ouvrir l’application | Une seule section « Atelier English Fluency » ; « Conversion rapide » n’est plus visible. |
| AC-02 | Préparer une vidéo FR | Audio FR original conservé ; textes FR et EN générés/validés. |
| AC-03 | Générer Kokoro pour cette vidéo | Deux fichiers audio locaux distincts ; le fichier EN est choisi pour la publication. |
| AC-04 | Publication FR complète avec auto-publication active | L’import démarre après TTS terminé et tous prérequis validés, sans deuxième clic. |
| AC-05 | Publication FR incomplète | Aucun import automatique ; raison du blocage visible. |
| AC-06 | Préparer une vidéo EN | Audio EN original choisi ; texte FR et analyse requis ; aucun Kokoro nécessaire. |
| AC-07 | Coller un JSON ChatGPT invalide | Message précis, aucune corruption des données valides précédentes. |
| AC-08 | Chunks sans segment existant | Rejet explicite avant publication. |
| AC-09 | Changer la traduction EN d’un bundle FR | Audio TTS marqué obsolète ; régénération requise avant publication. |
| AC-10 | Échec réseau Cloudflare | Statut d’échec, fichiers locaux conservés, retry possible sans doublon. |
| AC-11 | Préparer plusieurs URL | Bundles/jobs indépendants, avec statuts propres. |
| AC-12 | Ouvrir un ancien bundle | Lecture compatible ou message de migration guidée ; aucune perte silencieuse. |
| AC-13 | Contrôler un bundle « prêt » | Un seul fichier audio EN correct est sélectionné et les deux textes sont présents. |
| AC-14 | Modifier seulement le texte FR après publication | Pas de TTS inutile ; republication du contenu textuel possible. |
| AC-15 | Actualiser/relancer l’application pendant un job | État local reconstitué ; action de reprise claire. |

## 12. Plan d’implémentation recommandé

### Phase 0 — Audit et sauvegarde

- Repérer les composants, services, schémas, endpoints et formats réels.
- Constituer des échantillons de bundles FR/EN existants.
- Sauvegarder les contenus et mettre en place les tests de non-régression.

### Phase 1 — Socle métier (P0, prioritaire)

- Supprimer l’onglet Conversion rapide en conservant les services partagés.
- Formaliser `sourceLanguage`, `publishAudioFile`, les deux textes obligatoires et `canPublish`.
- Corriger les statuts « prêt à importer ».
- Mettre à jour les prompts de traduction et les validateurs de résultats.
- Structurer les chunks et points grammaticaux.

### Phase 2 — TTS et publication (P0, prioritaire)

- Générer/conserver le second MP3 Kokoro pour les sources FR.
- Ajouter versionnement, détection des fichiers obsolètes et sélection de l’audio EN.
- Brancher la publication automatique sur la complétude réelle du bundle.
- Fiabiliser les retries/idempotence et vérifier les imports côté mobile.

### Phase 3 — Ergonomie (P0/P1)

- Remplacer les longs panneaux déroulants par une liste compacte et un écran de détail guidé.
- Ajouter prévisualisation bilingue, messages de validation et checklist explicite.
- Ajouter recherche, filtres et historique de publication.

### Phase 4 — Enrichissement pédagogique (P1/P2)

- Alignement audio ↔ texte EN/FR.
- Révisions/republishes partielles.
- Passerelle vers le SRS et les exercices de l’application mobile.

## 13. Livrables attendus du développement

- Application Mac refondue, basée sur le dépôt existant.
- Formats locaux et payload Cloudflare documentés, avec exemples FR et EN.
- Modèles de prompts FR→EN, EN→FR et analyse pédagogique.
- Validations typées, tests automatisés de `canPublish` et des transitions de statuts.
- Test de bout en bout des deux parcours jusqu’à l’application mobile.
- Notes de migration pour les bundles anciens et instructions de récupération sur erreur.

## 14. Consigne à transmettre à l’agent de développement

> Implémente ce cahier des charges **par évolution de l’application actuelle**, pas comme un nouveau projet. Commence par auditer le dépôt et identifie précisément les composants UI, les fonctions d’extraction/transcription, le TTS Kokoro, les fichiers de bundle, l’import Cloudflare et leurs dépendances. Présente les écarts avec la spécification et un plan de modifications limité. Ne supprime aucun service partagé avec « Conversion rapide » sans vérifier ses consommateurs. Préserve les bundles existants et l’API mobile. Ajoute d’abord les tests métier pour les parcours source FR et source EN, puis développe par phases. N’invente pas les noms de routes et de fichiers sans les vérifier dans le dépôt.

---

### Décisions structurantes retenues

**Un seul atelier. Un audio publié toujours en anglais. L’original est conservé. Deux textes intégraux EN/FR. Des chunks et explications contextualisés. ChatGPT reste manuel pour la traduction et l’analyse. Kokoro produit un second MP3 pour les sources FR. L’import Cloudflare devient automatique une fois tous les prérequis validés.**
