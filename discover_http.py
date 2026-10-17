"""Routes locales de l'onglet Discover ; aucun jeton n'est envoyé au navigateur."""
import json
from pathlib import Path
from urllib.parse import urlsplit

from discover_queue import FILE

ASSETS = {'/discover': ('discover_queue.html', 'text/html; charset=utf-8'),
          '/discover_queue.js': ('discover_queue.js', 'text/javascript; charset=utf-8')}


def traiter(handler, methode, path, donnees=None):
    if path not in ASSETS and not path.startswith('/api/discover/'):
        return False
    host = handler.headers.get('Host', '')
    if urlsplit('http://' + host).hostname not in ('127.0.0.1', 'localhost'):
        handler._envoyer(403, {'erreur': 'Accès local uniquement.'})
        return True
    if methode == 'GET' and path in ASSETS:
        nom, mime = ASSETS[path]
        handler._envoyer(200, (Path(__file__).parent / nom).read_bytes(), mime)
        return True
    if methode == 'POST' and (handler.headers.get('Origin') != 'http://' + host
                             or handler.headers.get('X-Discover-Atelier') != '1'):
        handler.close_connection = True
        handler._envoyer(403, {'erreur': 'Origine locale requise.'})
        return True
    try:
        if methode == 'POST':
            longueur = int(handler.headers.get('Content-Length') or 0)
            if not 0 <= longueur <= 4096:
                handler.close_connection = True
                raise ValueError('Requête trop volumineuse.')
            json.loads(handler.rfile.read(longueur) or b'{}')
        if methode == 'GET' and path == '/api/discover/queue':
            handler._envoyer(200, {**FILE.liste(), 'state': FILE.etat()})
        elif methode == 'POST' and path == '/api/discover/start':
            FILE.demarrer()
            handler._envoyer(200, {'state': FILE.etat()})
        elif methode == 'POST' and path == '/api/discover/stop':
            FILE.arreter()
            handler._envoyer(200, {'state': FILE.etat()})
        else:
            handler._envoyer(404, {'erreur': 'Route inconnue.'})
    except (OSError, ValueError, RuntimeError):
        handler._envoyer(503, {'erreur': 'Discover indisponible. Vérifier config_discover.json et la connexion.'})
    return True
