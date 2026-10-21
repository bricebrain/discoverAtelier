#!/bin/bash
# Double-cliquez sur ce fichier pour lancer l'Atelier Discover
# (file locale de préparation des épisodes et vidéos Discover).
cd "$(dirname "$0")"
exec /usr/local/bin/python3 atelier_discover.py
