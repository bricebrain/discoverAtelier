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
| `idees.py`            | Idées de contenus : recherche YouTube via le Worker, cache 1 h |
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
