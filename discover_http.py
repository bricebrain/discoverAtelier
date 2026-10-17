"""Routes locales de l'onglet Discover ; aucun jeton n'est envoyé au navigateur."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from discover_queue import FILE
import discover_cible
import discover_review
import jsonschema
from urllib.parse import parse_qs, urlencode

# Messages compréhensibles pour les erreurs du Worker les plus courantes.
MESSAGES = {
    'unauthenticated': 'Le Worker refuse le jeton de l’Atelier : vérifier « atelierToken » dans config_discover.json.',
    'already_queued': 'Cet épisode a déjà une préparation en cours avec d’autres réglages. Annule-la d’abord pour changer de réglages.',
    'queue_conflict': 'Une préparation est déjà en cours pour cet épisode.',
    'queue_closed': 'Cette demande est déjà terminée ou annulée.',
    'invalid_options': 'Réglages refusés : vérifie la couverture, le niveau et la durée cible.',
    'not_found': 'Épisode introuvable : il a peut-être quitté la liste des 10 derniers épisodes.',
    'invalid_url': 'Lien YouTube non reconnu : colle l’adresse d’une vidéo (youtube.com/watch?v=… ou youtu.be/…).',
    'invalid_text': 'Le texte doit faire entre 20 et 100 000 caractères.',
}
FILTRES = ('category', 'show', 'lang', 'state', 'cursor')


def _erreur_discover(erreur):
    if isinstance(erreur, discover_cible.ErreurDiscover):
        return MESSAGES.get(erreur.code) or erreur.message or f'Le Worker a refusé la demande ({erreur.code}).'
    if isinstance(erreur, OSError):
        return 'Worker Discover injoignable : vérifier la connexion Internet et « workerUrl ».'
    return None

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
        elif methode == 'GET' and path == '/api/discover/shows':
            handler._envoyer(200, FILE.requete(FILE.config or discover_cible.charger_config(), 'GET', '/atelier/shows'))
        elif methode == 'GET' and path == '/api/discover/episodes':
            query = parse_qs(urlsplit(handler.path).query)
            filtres = {k: v[0][:200] for k, v in query.items() if k in FILTRES and v and v[0]}
            chemin = '/atelier/episodes' + ('?' + urlencode(filtres) if filtres else '')
            handler._envoyer(200, FILE.requete(FILE.config or discover_cible.charger_config(), 'GET', chemin))
        elif methode == 'POST' and path == '/api/discover/prepare':
            episode = str(donnees.get('episodeId', ''))
            options = donnees.get('options') or {}
            if not re.fullmatch(r'[0-9a-f]{20}', episode) or not isinstance(options, dict):
                raise ValueError('Demande de préparation invalide.')
            resultat = FILE.requete(FILE.config or discover_cible.charger_config(), 'POST', f'/atelier/episodes/{episode}/prepare', options)
            FILE.demarrer()  # la préparation commence tout de suite sur ce Mac
            handler._envoyer(200, resultat)
        elif methode == 'POST' and path == '/api/discover/import':
            # Lien YouTube ou texte importé : la demande rejoint la même file que les épisodes.
            kind = donnees.get('kind')
            options = donnees.get('options') or {}
            if kind not in ('youtube', 'text') or not isinstance(options, dict):
                raise ValueError('Import invalide.')
            corps = {'kind': kind, 'options': options}
            if kind == 'youtube':
                corps['url'] = str(donnees.get('url', ''))[:500]
            else:
                corps['title'] = str(donnees.get('title', ''))[:200]
                corps['text'] = str(donnees.get('text', ''))[:100_000]
            resultat = FILE.requete(FILE.config or discover_cible.charger_config(), 'POST', '/atelier/sources', corps)
            FILE.demarrer()
            handler._envoyer(200, resultat)
        elif methode == 'POST' and path in ('/api/discover/retry', '/api/discover/cancel'):
            identifiant = str(donnees.get('id', ''))
            if not re.fullmatch(r'[0-9a-f-]{36}', identifiant):
                raise ValueError('Demande invalide.')
            action = path.rsplit('/', 1)[1]
            FILE.requete(FILE.config or discover_cible.charger_config(), 'POST', f'/atelier/queue/{identifiant}/{action}', {})
            if action == 'retry':
                FILE.demarrer()
            handler._envoyer(200, {'ok': True})
        elif methode == 'GET' and path == '/api/discover/flagged':
            handler._envoyer(200, {'reviews': discover_review.liste(FILE.dossier, publiees=True)})
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
        message = _erreur_discover(erreur)
        if message is None:
            message = str(erreur)[:300] if isinstance(erreur, ValueError) else 'Discover indisponible. Vérifier la configuration et la connexion.'
        handler._envoyer(503, {'erreur': message})
    return True
