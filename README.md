# 🎓 Atelier Discover

Application web locale qui prépare les épisodes et vidéos demandés depuis
Discover (PWA) : téléchargement, transcription, adaptation au niveau,
voix, quiz et publication vers le Worker Discover.

Séparé le 21 octobre 2026 de l'Atelier English Fluency (dépôt `convert`),
avec l'historique git des fichiers Discover. Les modules autrefois partagés
(`pipeline`, `bundles`, `transcription`, `horodatage`, `adaptation`,
`manifeste_validation`, `tts_kokoro`) sont ici une copie indépendante.

## Installation (une seule fois)

```bash
cd ~/mesProjects/myMobileProjects/discoverAtelier
python3 -m pip install --user -r requirements.txt
```

À placer à la racine (non versionnés) :
- `config_discover.json` : voir `config_discover.example.json` ;
- `config_ia.json` et `config_import.json` : voir les exemples ;
- `venv-tts/` et `modeles_tts/` : environnement et modèles Kokoro.

## Utilisation

Double-cliquez sur **`lancer_discover.command`**, ou :

```bash
python3 atelier_discover.py
```

`DISCOVER_ATELIER_PORT` fixe le port (libre par défaut). Les données de
travail sont dans `fileToImport/.discover-queue/`. Fonctionnement de la
file : `DISCOVER_QUEUE.md`.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
