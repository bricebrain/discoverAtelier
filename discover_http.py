"""Routes locales de l'onglet Discover ; aucun jeton n'est envoyé au navigateur."""
import json
from pathlib import Path
from urllib.parse import urlsplit

from discover_queue import FILE
import discover_review
import jsonschema

ASSETS = {'/discover': ('discover_queue.html', 'text/html; charset=utf-8'),
          '/discover_queue.js': ('discover_queue.js', 'text/javascript; charset=utf-8'),
          '/discover_review.js': ('discover_review.js', 'text/javascript; charset=utf-8')}


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
            if not 0 <= longueur <= 300_000:
                handler.close_connection = True
                raise ValueError('Requête trop volumineuse.')
            donnees = json.loads(handler.rfile.read(longueur) or b'{}')
            if not isinstance(donnees, dict):
                raise ValueError('Objet JSON requis.')
        if methode == 'GET' and path == '/api/discover/reviews':
            active = {i['id'] for i in FILE.liste()['items'] if i['status'] == 'pending' and i['stage'] == 'review'}
            handler._envoyer(200, {'reviews': [r for r in discover_review.liste(FILE.dossier) if r['id'] in active]})
        elif methode == 'GET' and path == '/api/discover/review':
            from urllib.parse import parse_qs
            identifiant = parse_qs(urlsplit(handler.path).query).get('id', [''])[0]
            handler._envoyer(200, discover_review.trouver(FILE.dossier, identifiant)[1])
        elif methode == 'POST' and path == '/api/discover/review':
            result = discover_review.action(FILE.dossier, donnees)
            FILE.demarrer()
            handler._envoyer(200, result)
        elif methode == 'GET' and path == '/api/discover/queue':
            handler._envoyer(200, {**FILE.liste(), 'state': FILE.etat()})
        elif methode == 'POST' and path == '/api/discover/start':
            FILE.demarrer()
            handler._envoyer(200, {'state': FILE.etat()})
        elif methode == 'POST' and path == '/api/discover/stop':
            FILE.arreter()
            handler._envoyer(200, {'state': FILE.etat()})
        else:
            handler._envoyer(404, {'erreur': 'Route inconnue.'})
    except (OSError, ValueError, RuntimeError, jsonschema.ValidationError) as erreur:
        handler._envoyer(503, {'erreur': str(erreur)[:300] if isinstance(erreur, ValueError) else 'Discover indisponible. Vérifier la configuration et la connexion.'})
    return True
