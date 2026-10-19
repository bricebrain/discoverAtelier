# 🎓 Atelier English Fluency

Application web locale qui transforme une vidéo YouTube **française ou
anglaise** en **bundle bilingue** publiable dans l'app mobile English
Fluency : audio **anglais**, textes **EN et FR intégraux**, chunks et
points de grammaire. Spécification : `CAHIER_DES_CHARGES_ENGLISH_FLUENCY_STUDIO.md`.

## Installation (une seule fois)

Ouvrez le Terminal et lancez :

```bash
cd ~/mesProjects/myMobileProjects/convert
python3 -m pip install --user -r requirements.txt
```

> Votre `python3` doit être celui de python.org (3.15, installé dans
> `/Library/Frameworks`) : c'est le cas, `/usr/local/bin/python3` y
> pointe. Le Python 3.9 d'Apple (`/usr/bin/python3`) a un tkinter cassé
> sur les derniers macOS — à éviter pour cette app.

Cela installe :
- **yt-dlp** : téléchargement des vidéos ;
- **imageio-ffmpeg** : fournit un binaire `ffmpeg` (nécessaire à la
  conversion MP3), sans avoir à installer Homebrew.

## Utilisation

Double-cliquez sur **`lancer_atelier.command`** (le navigateur s'ouvre
tout seul), ou dans le Terminal :

```bash
python3 convertisseur_web.py
```

### Révision des 4 000+ mots du Worker

Le bouton **◫ Réviser les 4 000 mots** ouvre un module intégré visuellement à
l'Atelier. Il lit le référentiel réel via `GET /words`, permet de rechercher et
sélectionner les entrées douteuses, puis les traite par lots versionnés. Le filtre
**Pas encore connus** s'appuie sur le statut SRS du `profileId` configuré pour
masquer les mots déjà maîtrisés.

- **Ollama local** : ouvrez l'application Ollama, sélectionnez un modèle
  installé et traitez de petits lots (10 mots maximum sur ce Mac) sans coût
  par requête ;
- **IA externe** : générez un prompt pour Gemini, DeepSeek ou ChatGPT, puis
  collez la réponse JSON dans l'atelier (jusqu'à 50 mots par lot).

Chaque lot suit quatre étapes : sélection (10, 20, 25 ou 50 mots), génération
du prompt, import du JSON et revue humaine. Les identifiants et toutes les
valeurs d'origine doivent correspondre exactement. Un import incomplet garde
les entrées valides comme brouillon et signale les entrées manquantes. Chaque
proposition peut être modifiée, refusée ou approuvée.

La publication explicite appelle l'API d'administration du Worker. Elle ne
modifie jamais la ligne originale de `words` : l'enrichissement courant et
chaque version historique sont stockés séparément dans D1. Les relances sont
idempotentes, un rollback crée une nouvelle version, et les données SRS sont
préservées. Les lots locaux restent dans `vocabularyRevisions/revisions.json`.

La suppression en masse est, elle, appliquée directement au Worker par
`DELETE /words` (200 mots maximum). Après confirmation, la transaction D1
supprime les entrées de `words`, leur progression `word_progress` et leurs
cartes `lingvist_cards` pour tous les profils. Cette action est irréversible.

### Migration automatique du vocabulaire par API

La page `/vocabulaire` propose un parcours sans revue manuelle : Gemini
génère un lot de 20 mots par défaut (taille réglable de 1 à 20), OpenAI contrôle et corrige la proposition,
le schéma local valide le résultat, puis le lot est approuvé et publié.
Une anomalie de structure est relancée automatiquement ; après épuisement
des reprises, la migration s'arrête et libère le lot non publié.

Configurez les clés depuis le bouton **Configurer les API**. Elles sont
écrites dans `config_ia.json` avec des permissions locales restrictives ;
ce fichier est ignoré par Git et les clés ne sont jamais renvoyées par
l'API du navigateur. Les variables `OPENAI_API_KEY` et `GEMINI_API_KEY`
peuvent aussi être utilisées. Voir `config_ia.example.json` pour les
modèles et limites disponibles.

Les réglages économiques par défaut utilisent `gemini-3.1-flash-lite` pour
générer et `gpt-6-luna` avec `reasoning.effort: low` pour contrôler.
Le suivi affiche les tokens entrants et sortants, raisonnement inclus.
Le budget indicatif de 3 à 6 $ pour environ 4 100 mots reste à affiner avec
la consommation du premier lot et les tarifs des fournisseurs ; il ne
constitue pas un plafond de dépenses.

Commencez par **Essai automatique sur 20 mots**. Lorsque ce lot est publié,
choisissez **Tout le corpus restant**. L'arrêt demandé prend effet après le
lot courant, afin de ne jamais laisser une publication à moitié appliquée.

### Parcours

1. Collez un ou plusieurs liens (un job et un bundle par lien), langue
   source **Auto** (ou Français / Anglais si la détection échoue — un job
   en échec se relance aussi avec « ↻ en FR » / « ↻ en EN »), niveau, thème ;
2. L'audio **original** est extrait (`<slug>.mp3`, jamais écrasé) puis
   transcrit dans la langue source ;
3. **📋 Prompt traduction** (FR→EN ou EN→FR) : le texte est découpé en
   segments `s001`, `s002`… ; collez le **JSON** renvoyé par ChatGPT puis
   **✔ Valider et enregistrer**. Un JSON invalide est refusé avec la
   liste des erreurs, sans rien modifier. Les longues vidéos se traitent
   par sections de 40 segments ;
4. **📋 Prompt analyse pédagogique** sur le texte anglais : chunks +
   grammaire en JSON, validés (niveau, type, segment existant) ;
5. **Audio anglais** : source FR → **🔊 Générer l'audio EN (Kokoro)**
   crée `<slug>.audio-en.mp3` à partir du texte anglais validé ; source EN
   → l'audio original est publié, sans TTS ;
6. **🚀 Publier** n'apparaît que si tout est prêt (badges audio EN,
   texte EN, texte FR, chunks/grammaire, métadonnées). Seul l'audio
   anglais est envoyé (R2), puis `POST /content` (upsert sur l'id : un
   retry ne crée pas de doublon).

**Auto-publication** : cochez « Publier automatiquement dès que le
bundle est prêt » (choix mémorisé), ou l'interrupteur « auto-publication »
d'un bundle. La publication part alors toute seule dès que le dernier
prérequis est validé (fin du Kokoro, traduction ou analyse collée), sans
deuxième clic. Une version déjà publiée n'est pas renvoyée, et un échec
réseau n'est pas relancé automatiquement : « Réessayer » reste manuel.

**Reprise après redémarrage** : les jobs sont enregistrés dans
`fileToImport/_jobs.json`. Au lancement, un job, un Kokoro ou une
publication interrompus apparaissent en échec avec leur action de reprise
(l'audio déjà extrait n'est pas re-téléchargé), et les fichiers
temporaires sont nettoyés.

Modifier le texte anglais rend l'analyse et l'audio Kokoro **obsolètes**
(à refaire avant publication). Les anciens bundles restent lisibles :
ils demandent simplement une traduction segmentée.

Fichiers d'un bundle (nommage à plat dans `fileToImport/`) :
`<slug>.mp3`, `<slug>.audio-en.mp3`, `<slug>.transcript.<langue>.txt`,
`<slug>.translation.<langue>.txt`, `<slug>.segments.json`,
`<slug>.pedagogy.json`, `<slug>.meta.json`.

La connexion au Worker est configurée dans **`config_import.json`**
(`workerUrl`, `apiSecret`, `profileId`).

> ⚠️ Un seul exemplaire à la fois : avant de relancer l'app, fermez la
> fenêtre Terminal de l'instance précédente (Ctrl+C).

### Tests

```bash
python3 -m unittest discover -s tests -v
```

## Fichiers du projet

| Fichier               | Rôle                                              |
|-----------------------|---------------------------------------------------|
| `convertisseur_web.py`| Serveur local : jobs, Kokoro, routes de l'atelier |
| `interface.html`      | Interface web (atelier unique)                    |
| `pipeline.py`         | Logique métier : segments, prompts, validation, canPublish, publication |
| `transcription.py`    | Transcription : sous-titres YouTube + MacWhisper  |
| `bundles.py`          | Fichiers des bundles (slug, meta, inventaire) + connexion Worker |
| `vocabulaire.py`      | Orchestration de la révision du référentiel          |
| `vocabulaire_lots.py` | Cycle de vie sélection, import, revue et publication |
| `vocabulaire_prompt.py` | Prompt lexical versionné et snapshot des sources   |
| `vocabulaire_publication.py` | Publication authentifiée vers le Worker      |
| `vocabulaire_stockage.py` | Persistance atomique des lots locaux              |
| `vocabulaire_progression.py` | Filtrage des mots connus via le SRS Worker   |
| `vocabulaire_suppression.py` | Suppression en masse authentifiée du Worker  |
| `ollama_vocabulaire.py` | Client du moteur IA local Ollama                      |
| `vocabulaire_automatisation.py` | Orchestration Gemini → OpenAI → publication |
| `vocabulaire_ia_clients.py` | Clients HTTP OpenAI et Gemini sans dépendance     |
| `vocabulaire_ia_config.py` | Configuration locale sécurisée des fournisseurs    |
| `vocabulaire_ia_schema.py` | Schéma JSON strict commun aux deux API             |
| `vocabulaire_validation.py` | Validation pure des réponses IA du référentiel |
| `vocabulaire.html`    | Interface dédiée à la révision des mots            |
| `vocabulaire_api.js`  | Service HTTP du module vocabulaire                   |
| `tts_kokoro.py`       | Synthèse Kokoro (lancée via `venv-tts`)           |
| `tests/`              | Tests métier des parcours FR et EN                |
| `fileToImport/`       | Bundles préparés pour l'app English Fluency       |
| `config_import.json`  | Connexion au Worker (URL, secret, profil)         |
| `lancer_atelier.command` | Lanceur par double-clic (macOS)               |
| `IMPORT_BUNDLES_SPEC.md` | Spécification des bundles (référence)          |
| `requirements.txt`    | Dépendances Python                                |

## En cas de problème

- **« ffmpeg est introuvable »** → relancez l'installation des
  dépendances (voir plus haut).
- **Erreurs de téléchargement du type "Sign in to confirm you're not a
  bot" ou formats indisponibles** → YouTube change souvent son
  fonctionnement ; mettez yt-dlp à jour :

  ```bash
  python3 -m pip install --user --upgrade yt-dlp
  ```

- **HTTP 429 (Too Many Requests)** sur les sous-titres → vous avez
  enchaîné trop de traitements ; attendez quelques minutes puis
  relancez le job (bouton ↻).

## Rappel légal

Cet outil est destiné à un **usage personnel** (vos propres vidéos,
contenus libres de droits ou autorisés). Télécharger des œuvres
protégées peut enfreindre le droit d'auteur et les conditions
d'utilisation de YouTube — la responsabilité de l'usage vous incombe.
# atelierConvert
