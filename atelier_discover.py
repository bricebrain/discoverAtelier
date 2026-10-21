# -*- coding: utf-8 -*-
"""Atelier Discover : serveur local de la file de préparation Discover.

Séparé de l'Atelier English Fluency (dépôt convert). Toutes les routes
sont dans discover_http ; ce fichier ne fait que les servir et démarrer
la file au lancement.
"""

import json
import os
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import bundles
import discover_cible
import discover_http
from discover_queue import FILE


class Gestionnaire(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _envoyer(self, code, corps, type_mime="application/json; charset=utf-8"):
        donnees = corps if isinstance(corps, bytes) else json.dumps(
            corps, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", type_mime)
        self.send_header("Content-Length", str(len(donnees)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(donnees)

    def do_GET(self):
        if not discover_http.traiter(self, "GET", urllib.parse.urlsplit(self.path).path):
            self._envoyer(404, {"erreur": "introuvable"})

    def do_POST(self):
        if not self.path.startswith("/api/discover/"):
            self._envoyer(404, {"erreur": "introuvable"})
            return
        discover_http.traiter(self, "POST", self.path)

    def log_message(self, format, *args):
        pass  # pas de journalisation des requêtes HTTP


def main():
    # Port libre par défaut ; DISCOVER_ATELIER_PORT pour un port fixe
    port = int(os.environ.get("DISCOVER_ATELIER_PORT") or 0)
    serveur = ThreadingHTTPServer(("127.0.0.1", port), Gestionnaire)
    port = serveur.server_address[1]
    url = f"http://127.0.0.1:{port}"
    bundles.assure_dossier()
    if discover_cible.CONFIG.exists():
        try:
            FILE.demarrer()
        except (OSError, ValueError):
            print("   Discover : vérifier config_discover.json.")
    else:
        print("   config_discover.json absent : la file ne démarre pas.")
    print("🎓 Atelier Discover")
    print(f"   Interface   : {url}")
    print(f"   Données     : {FILE.dossier}")
    print("   Pour arrêter : Ctrl+C dans cette fenêtre (ou fermez le Terminal).")

    # Ouvre le navigateur (sauf en mode test)
    if not os.environ.get("DISCOVER_ATELIER_SANS_NAVIGATEUR"):
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt de l'Atelier Discover. À bientôt !")
    finally:
        FILE.arreter()
        serveur.server_close()


if __name__ == "__main__":
    main()
