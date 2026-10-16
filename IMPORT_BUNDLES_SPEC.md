# Spécification — Bundles d'import YouTube/MP3 vers English Fluency

Version : 1.0  
Date : 2026-10-11  
Projet source : `/Users/brice/mesProjects/myMobileProjects/convert`  
Projet cible : `englishfluency-worker` puis app mobile English Fluency

## 1. Objectif

L'application `convert` doit devenir un atelier local de préparation de contenus.

Elle prend un ou plusieurs liens YouTube, génère :

- un fichier audio `.mp3` ;
- une transcription source `.txt` ;
- éventuellement une adaptation anglaise au niveau voulu ;
- éventuellement un résumé français ;
- un fichier de métadonnées `.meta.json`.

Ensuite, un importeur pourra envoyer le bundle complet vers le Worker English Fluency.

L'app React Native ne doit pas faire ce travail lourd. Elle doit seulement consommer les contenus déjà préparés depuis le Worker.

## 2. Principe central : un contenu = un bundle

Chaque contenu est identifié par un même `slug`.

Tous les fichiers liés au même contenu doivent partager ce slug.

Exemple :

```text
fileToImport/
  why-we-procrastinate.mp3
  why-we-procrastinate.transcript.fr.txt
  why-we-procrastinate.adapted.en-B1.txt
  why-we-procrastinate.summary.fr.txt
  why-we-procrastinate.meta.json
```

Le fichier `.meta.json` est obligatoire. Les autres fichiers dépendent du contenu disponible.

## 3. Dossier attendu

Créer dans le projet `convert` :

```text
/Users/brice/mesProjects/myMobileProjects/convert/fileToImport/
```

Ce dossier contient uniquement les bundles prêts ou en cours de préparation.

Recommandation future :

```text
convert/
  fileToImport/
    pending/
    ready/
    imported/
    failed/
```

Mais pour la première version, un seul dossier `fileToImport/` suffit.

## 4. Convention de nommage

Format général :

```text
<slug>.<role>.<langue-ou-niveau>.txt
<slug>.mp3
<slug>.meta.json
```

### 4.1 Audio

```text
<slug>.mp3
```

Exemples :

```text
ma-video.mp3
native-podcast.mp3
```

### 4.2 Transcription source

Transcription fidèle de l'audio original.

```text
<slug>.transcript.fr.txt
<slug>.transcript.en.txt
```

Exemples :

```text
ma-video.transcript.fr.txt
native-podcast.transcript.en.txt
```

### 4.3 Adaptation anglaise au niveau cible

Texte anglais naturel, adapté au niveau de l'utilisateur.

```text
<slug>.adapted.en-A2.txt
<slug>.adapted.en-B1.txt
<slug>.adapted.en-B2.txt
```

Exemple :

```text
ma-video.adapted.en-B1.txt
```

Important :

- Ce fichier peut être généré avec ChatGPT Plus.
- Il n'est pas forcément une traduction mot à mot.
- Il doit garder les faits du texte source.
- Il doit être lisible par un apprenant.

### 4.4 Résumé français

Résumé court destiné à l'interface mobile.

```text
<slug>.summary.fr.txt
```

### 4.5 Optionnel : notes pédagogiques

Plus tard, on pourra ajouter :

```text
<slug>.chunks.en-B1.json
<slug>.quiz.en-B1.json
<slug>.vocab.en-B1.json
```

Ce n'est pas obligatoire en V1.

## 5. Exemples de bundles

### 5.1 Audio français, contenu adapté en anglais

```text
mon-sujet.mp3
mon-sujet.transcript.fr.txt
mon-sujet.adapted.en-B1.txt
mon-sujet.summary.fr.txt
mon-sujet.meta.json
```

Cas d'usage :

- vidéo française ;
- audio original en français ;
- transcription française via MacWhisper ;
- adaptation anglaise générée avec ChatGPT Plus ;
- app mobile affiche l'audio original + lecture anglaise adaptée.

### 5.2 Audio anglais natif

```text
bbc-meetings.mp3
bbc-meetings.transcript.en.txt
bbc-meetings.adapted.en-B1.txt
bbc-meetings.summary.fr.txt
bbc-meetings.meta.json
```

Cas d'usage :

- podcast ou vidéo anglaise ;
- audio original en anglais ;
- transcription anglaise ;
- adaptation optionnelle plus simple ;
- résumé français.

### 5.3 Audio anglais sans adaptation

```text
native-story.mp3
native-story.transcript.en.txt
native-story.summary.fr.txt
native-story.meta.json
```

Cas d'usage :

- le texte original est déjà adapté au niveau ;
- pas besoin de fichier `adapted`.

## 6. Fichier `.meta.json`

Chaque bundle doit avoir un fichier :

```text
<slug>.meta.json
```

### 6.1 Exemple minimal

```json
{
  "id": "mon-sujet",
  "title": "Mon sujet",
  "sourceType": "youtube",
  "sourceUrl": "https://www.youtube.com/watch?v=...",
  "audioLanguage": "fr",
  "transcriptLanguage": "fr",
  "targetLevel": "B1",
  "contentKind": "personal_interest",
  "createdAt": "2026-10-11T19:40:00Z"
}
```

### 6.2 Exemple complet

```json
{
  "id": "bbc-meetings",
  "title": "BBC Work Meetings",
  "sourceType": "youtube",
  "sourceUrl": "https://www.youtube.com/watch?v=...",
  "audioLanguage": "en",
  "transcriptLanguage": "en",
  "availableFiles": {
    "audio": "bbc-meetings.mp3",
    "transcript": "bbc-meetings.transcript.en.txt",
    "adaptedText": "bbc-meetings.adapted.en-B1.txt",
    "summary": "bbc-meetings.summary.fr.txt"
  },
  "targetLevel": "B1",
  "accent": "en-GB",
  "contentKind": "youtube_audio",
  "topic": "work",
  "rights": "personal_use",
  "processing": {
    "transcriptionProvider": "macwhisper",
    "adaptationProvider": "chatgpt-plus",
    "summaryProvider": "chatgpt-plus"
  },
  "createdAt": "2026-10-11T19:40:00Z"
}
```

### 6.3 Champs recommandés

| Champ | Type | Obligatoire | Description |
|---|---:|---:|---|
| `id` | string | oui | Slug stable du bundle |
| `title` | string | oui | Titre lisible dans l'app |
| `sourceType` | string | oui | `youtube`, `local_mp3`, `manual` |
| `sourceUrl` | string | non | Lien YouTube si disponible |
| `audioLanguage` | string | oui | `fr` ou `en` |
| `transcriptLanguage` | string | oui | `fr` ou `en` |
| `targetLevel` | string | oui | `A2`, `B1`, `B2`, etc. |
| `accent` | string | non | `en-GB` par défaut |
| `contentKind` | string | oui | `youtube_audio`, `personal_interest`, `course`, etc. |
| `topic` | string | non | Sujet principal |
| `rights` | string | oui | `personal_use`, `owned`, `public_domain`, etc. |
| `createdAt` | ISO string | oui | Date de création |
| `availableFiles` | object | conseillé | Liste explicite des fichiers |
| `processing` | object | conseillé | Providers utilisés |

## 7. Règles de langue

L'audio et le texte peuvent être dans des langues différentes.

Cas possibles :

| Audio | Transcription | Adaptation | Cas |
|---|---|---|---|
| FR | FR | EN niveau B1 | Vidéo française adaptée en anglais |
| EN | EN | EN niveau B1 | Audio natif simplifié |
| EN | EN | absent | Audio anglais déjà utilisable |
| FR | FR | absent | Contenu pas encore prêt pour l'app mobile |

L'application mobile doit afficher clairement :

- langue de l'audio original ;
- langue de la transcription ;
- présence ou absence d'une version anglaise adaptée ;
- niveau cible.

## 8. Génération avec ChatGPT Plus

Certains fichiers peuvent être générés manuellement avec ChatGPT Plus avant l'import.

### 8.1 Quand générer les fichiers manquants ?

Recommandation V1 :

1. `convert` télécharge l'audio et produit la transcription source.
2. Le bundle reste dans `fileToImport/`.
3. Un script détecte les fichiers manquants.
4. L'utilisateur copie le transcript dans ChatGPT Plus avec un prompt standard.
5. L'utilisateur colle le résultat dans le bon fichier :
   - `<slug>.adapted.en-B1.txt`
   - `<slug>.summary.fr.txt`
6. Le bundle devient importable.

Plus tard, ce flux pourra être semi-automatisé, mais V1 doit rester simple et contrôlable.

### 8.2 Prompt standard — adaptation FR vers anglais B1

```text
Tu es un professeur d'anglais britannique pour un apprenant francophone niveau A2+/B1.

Je vais te donner une transcription en français.

Objectif :
- produire une version anglaise naturelle en anglais britannique ;
- niveau cible : B1 ;
- garder les faits, les idées et l'ordre général ;
- ne pas traduire mot à mot si ce n'est pas naturel ;
- utiliser des phrases courtes et claires ;
- garder quelques expressions utiles mais pas trop difficiles ;
- ne pas ajouter d'informations qui ne sont pas dans le texte ;
- ne pas faire de résumé : je veux une version complète adaptée.

Format de sortie :
- texte anglais uniquement ;
- pas de Markdown ;
- pas de titre ;
- pas d'explication.

Transcription française :
<<<
COLLER ICI LE TEXTE FRANÇAIS
>>>
```

### 8.3 Prompt standard — simplification d'un transcript anglais vers B1

```text
You are a British English teacher for a French-speaking learner at A2+/B1 level.

I will give you an English transcript.

Goal:
- rewrite it into clear, natural British English at B1 level;
- keep the facts and main ideas;
- keep the general order;
- simplify difficult sentences;
- keep useful natural expressions when possible;
- do not add information;
- do not summarise too much: I want a readable adapted version.

Output format:
- English text only;
- no Markdown;
- no title;
- no explanation.

English transcript:
<<<
PASTE ENGLISH TRANSCRIPT HERE
>>>
```

### 8.4 Prompt standard — résumé français

```text
Tu es un assistant pédagogique.

À partir du texte ci-dessous, produis un résumé français pour une app d'apprentissage de l'anglais.

Objectif :
- 5 à 8 lignes maximum ;
- expliquer clairement le sujet ;
- indiquer pourquoi ce contenu est utile pour apprendre l'anglais ;
- ne pas inventer d'informations ;
- style simple, direct, naturel.

Format :
- texte français uniquement ;
- pas de Markdown ;
- pas de titre.

Texte :
<<<
COLLER ICI LE TEXTE SOURCE OU ADAPTÉ
>>>
```

### 8.5 Prompt optionnel — extraction de chunks

Ce fichier n'est pas obligatoire en V1, mais utile plus tard.

```text
Tu es un professeur d'anglais britannique.

À partir du texte anglais ci-dessous, extrais jusqu'à 12 chunks utiles pour un apprenant français niveau B1.

Un chunk peut être :
- une expression ;
- une collocation ;
- un phrasal verb ;
- une structure de phrase réutilisable ;
- une formulation utile en conversation.

Pour chaque chunk, donne :
- expression anglaise ;
- sens français ;
- exemple court ;
- niveau estimé : A2, B1 ou B2 ;
- contexte d'utilisation.

Retourne uniquement un JSON valide, sans Markdown :

{
  "chunks": [
    {
      "expression": "",
      "meaningFr": "",
      "example": "",
      "level": "B1",
      "context": ""
    }
  ]
}

Texte anglais :
<<<
COLLER ICI LE TEXTE ANGLAIS
>>>
```

## 9. Import vers le Worker

### 9.1 Cible V1 côté Worker

Le Worker possède déjà un endpoint générique :

```text
POST /content
GET /content
```

Payload recommandé pour V1 :

```json
{
  "profileId": "default",
  "id": "mon-sujet",
  "type": "podcast",
  "title": "Mon sujet",
  "level": "B1",
  "topic": "work",
  "body": "Texte anglais adapté ou transcript anglais...",
  "metadata": {
    "sourceType": "youtube",
    "sourceUrl": "https://www.youtube.com/watch?v=...",
    "audioLanguage": "fr",
    "transcriptLanguage": "fr",
    "transcriptText": "Transcription source...",
    "summaryFr": "Résumé français...",
    "adaptedFile": "mon-sujet.adapted.en-B1.txt",
    "transcriptFile": "mon-sujet.transcript.fr.txt"
  },
  "audioR2Key": "prepared-content/mon-sujet.mp3"
}
```

### 9.2 Règle de choix du `body`

Le champ `body` doit contenir le texte principal que l'app mobile va lire.

Priorité :

1. `adapted.en-<level>.txt` si disponible ;
2. `transcript.en.txt` si l'audio est anglais et pas d'adaptation ;
3. ne pas importer dans l'app mobile si seul `transcript.fr.txt` existe.

### 9.3 Audio R2

L'audio `.mp3` doit être stocké dans R2 avec une clé stable :

```text
prepared-content/<slug>.mp3
```

Le Worker stocke cette clé dans `audioR2Key`.

## 10. Automatisation multi-liens YouTube

Tu veux pouvoir coller plusieurs liens YouTube.

C'est une très bonne idée, mais il faut traiter chaque lien comme un job indépendant.

### 10.1 Format d'entrée URL

L'interface peut accepter :

```text
https://youtube.com/watch?v=aaa
https://youtube.com/watch?v=bbb
https://youtube.com/watch?v=ccc
```

Ou séparé par espaces, comme aujourd'hui.

### 10.2 Choix manuel de langue et traitement

Au moment où l'utilisateur colle une ou plusieurs URLs, l'interface doit demander explicitement les informations suivantes.

Cela évite de dépendre uniquement d'une détection automatique parfois mauvaise.

Champs recommandés :

```text
Langue audio :
- Français
- Anglais

Traitement voulu :
- Audio FR → transcription FR + adaptation anglaise
- Audio EN → transcription EN + adaptation anglaise simplifiée
- Audio EN → transcription EN seulement

Niveau cible :
- A2
- B1
- B2

Thème optionnel :
- Travail
- Quotidien
- Culture
- Tech
- Voyage
- Autre
```

Pour un batch de plusieurs liens, ces options peuvent s'appliquer à tout le lot en V1.

Plus tard, l'interface pourra permettre de modifier les options ligne par ligne.

### 10.3 Valeurs à écrire dans `.meta.json`

Ajouter ces champs dans le meta :

```json
{
  "audioLanguage": "fr",
  "transcriptLanguage": "fr",
  "targetLevel": "B1",
  "processingGoal": "fr_to_en_adaptation",
  "topic": "work"
}
```

Valeurs recommandées pour `processingGoal` :

```text
fr_to_en_adaptation
en_simplify_to_level
en_transcript_only
```

Interprétation :

| `processingGoal` | Audio | Transcription | Fichier attendu |
|---|---|---|---|
| `fr_to_en_adaptation` | FR | FR | `.adapted.en-<level>.txt` |
| `en_simplify_to_level` | EN | EN | `.adapted.en-<level>.txt` |
| `en_transcript_only` | EN | EN | pas d'adaptation obligatoire |

### 10.4 Règles de traitement

Pour chaque URL :

1. créer un `jobId` ;
2. récupérer les métadonnées YouTube ;
3. générer un slug unique ;
4. télécharger le MP3 ;
5. produire la transcription ;
6. créer ou mettre à jour `<slug>.meta.json` ;
7. marquer le job `ready_for_adaptation` si l'adaptation manque ;
8. marquer le job `ready_for_import` si tous les fichiers nécessaires existent.

### 10.5 Statuts recommandés

```text
queued
downloading
transcribing
needs_adaptation
needs_summary
ready_for_import
importing
imported
failed
```

### 10.6 Pourquoi pas tout paralléliser ?

Recommandation V1 :

- traiter les vidéos une par une ou avec une petite concurrence de 2 maximum ;
- éviter de lancer 10 téléchargements/transcriptions en même temps ;
- garder un journal par job ;
- permettre de relancer uniquement les jobs échoués.

### 10.7 Améliorations recommandées pour l'interface `convert`

Priorité haute :

1. File de jobs visible :
   - une ligne par URL ;
   - statut par job ;
   - bouton relancer uniquement ce job.
2. Génération automatique du `.meta.json`.
3. Scanner `fileToImport/` et afficher les bundles détectés.
4. Afficher les fichiers manquants :
   - transcript ;
   - adaptation ;
   - résumé ;
   - meta ;
   - audio.
5. Boutons “copier prompt ChatGPT” :
   - adaptation FR → EN niveau cible ;
   - simplification EN → EN niveau cible ;
   - résumé FR ;
   - extraction chunks optionnelle.
6. Zone “coller résultat ChatGPT” :
   - l'utilisateur colle le texte ;
   - l'app l'enregistre directement dans le bon fichier.

Priorité moyenne :

1. Détection des doublons par URL YouTube.
2. Slug stable et propre depuis le titre.
3. Preview du contenu :
   - audio ;
   - transcription ;
   - adaptation ;
   - résumé ;
   - meta.
4. Validation avant import :
   - texte principal anglais présent ;
   - meta valide ;
   - langue cohérente ;
   - audio optionnel mais lié si présent.
5. Journal par contenu dans le meta ou dans `<slug>.log.txt`.

Plus tard :

1. Import Worker automatique.
2. Upload audio vers R2.
3. POST `/content`.
4. Marquage `imported`.
5. Extraction de chunks JSON.
6. Gestion ligne par ligne des options dans un batch.

## 11. Détection des bundles prêts

Un script peut scanner `fileToImport/` et grouper les fichiers par slug.

Pseudo-code :

```python
for file in fileToImport:
    slug = extract_slug(file.name)
    group files by slug

for bundle in bundles:
    read <slug>.meta.json
    detect audio
    detect transcript
    detect adapted text
    detect summary
    decide status
```

Règle V1 :

- si `meta.json` manque → bundle invalide ;
- si `mp3` manque → import texte possible mais audio absent ;
- si seul transcript FR existe → `needs_adaptation` ;
- si adapted EN existe → `ready_for_import` ;
- si transcript EN existe sans adapted EN → `ready_for_import`.

## 12. Ce que GLM doit coder en priorité

### Lot 1 — Structurer les bundles

- Créer le dossier `fileToImport/` si absent.
- Ajouter dans l'interface les choix :
  - langue audio ;
  - traitement voulu ;
  - niveau cible ;
  - thème optionnel.
- Générer un slug propre pour chaque vidéo.
- Produire :
  - `<slug>.mp3`
  - `<slug>.transcript.<lang>.txt`
  - `<slug>.meta.json`
- Ajouter le statut dans le meta.

### Lot 2 — Scanner les fichiers

- Ajouter un script ou une route locale `/api/bundles`.
- Afficher les bundles détectés.
- Afficher les fichiers manquants.
- Indiquer `needs_adaptation`, `needs_summary`, `ready_for_import`.

### Lot 3 — Multi-liens YouTube

- Transformer l'entrée URL en liste.
- Créer un job par URL.
- Appliquer les options globales de langue/traitement/niveau à chaque job.
- Afficher une progression par job.
- Continuer même si un job échoue.

### Lot 4 — Préparer l'import Worker

- Lire le bundle.
- Construire le payload `/content`.
- Prévoir l'upload R2 de l'audio.
- Marquer le bundle comme `imported`.

## 13. Points importants à ne pas oublier

- Ne jamais mélanger transcription source et adaptation.
- Toujours garder la langue explicite.
- Ne pas importer un contenu uniquement français comme lecture anglaise.
- Toujours lier audio, transcript, adaptation et résumé par le même slug.
- Garder les fichiers source même après import.
- Éviter les imports doublons grâce à `id`.
- Prévoir que l'audio peut être français ou anglais.
- Prévoir que le texte principal mobile doit être anglais.
- L'adaptation ChatGPT Plus doit être reproductible grâce à un prompt standard.

## 14. Résumé architecture

```text
YouTube links
  ↓
convert app locale
  ↓
fileToImport/<slug> bundle
  ↓
ChatGPT Plus si adaptation/résumé manquants
  ↓
import Worker
  ↓
D1 /content + R2 audio
  ↓
app mobile English Fluency
  ↓
Écouter → Contenus préparés
```

Cette architecture garde l'app mobile légère et transforme le Mac en back-office de contenus.
