#!/bin/bash
# Double-cliquez sur ce fichier pour lancer l'atelier English Fluency
# (interface web locale de préparation des bundles bilingues).
cd "$(dirname "$0")"
exec /usr/local/bin/python3 convertisseur_web.py
