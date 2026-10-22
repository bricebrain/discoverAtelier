"""Routes locales de l'onglet Discover ; aucun jeton n'est envoyé au navigateur."""
import json
import re
import shutil
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from discover_queue import FILE
import discover_cible
import discover_vocabulary_picks
import discover_vocabulary_sync
import discover_related
import discover_costs
import discover_review
import discover_tts_settings
import jsonschema

# Messages compréhensibles pour les erreurs du Worker les plus courantes.
MESSAGES = {
    'unauthenticated': 'Le Worker refuse le jeton de l’Atelier : vérifier « atelierToken » dans config_discover.json.',
    'already_queued': 'Cet épisode a déjà une préparation en cours avec d’autres réglages. Annule-la d’abord pour changer de réglages.',
    'queue_conflict': 'Une préparation est déjà en cours pour cet épisode.',
    'queue_closed': 'Cette demande est déjà terminée ou annulée.',
    'queue_active': 'Annule d’abord la préparation en cours.',
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

ASSETS = {'/': ('discover_queue.html', 'text/html; charset=utf-8'),
          '/discover': ('discover_queue.html', 'text/html; charset=utf-8'),
          '/discover_queue.js': ('discover_queue.js', 'text/javascript; charset=utf-8'),
          '/discover_tts_ui.js': ('discover_tts_ui.js', 'text/javascript; charset=utf-8'),
          '/discover_review.js': ('discover_review.js', 'text/javascript; charset=utf-8')}


CONTENU = re.compile(r'[a-z0-9][a-z0-9-]{2,95}')
REFS = {'youtube': r'[A-Za-z0-9_-]{11}', 'reflection': r'[0-9a-f-]{36}'}


def effacer_versions_locales(root, kind, ref):
    """Efface les versions publiées gardées sur ce Mac (audio, rapport de contrôle) ; la source transcrite reste en cache."""
    if kind not in REFS or not re.fullmatch(REFS[kind], ref or ''):
        return 0
    dossier = Path(root) / f'{kind}-{ref}'
    effacees = 0
    for prepared in dossier.glob('prepared-*'):
        if prepared.is_dir() and (prepared / 'published.json').exists():
            shutil.rmtree(prepared)
            effacees += 1
    return effacees


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
        if methode == 'GET' and path == '/api/discover/related':
            handler._envoyer(200, discover_related.status(FILE.dossier))
        elif methode == 'GET' and path == '/api/discover/tts':
            handler._envoyer(200, discover_tts_settings.status(FILE.dossier))
        elif methode == 'GET' and path == '/api/discover/vocabulary/status':
            handler._envoyer(200, discover_vocabulary_sync.status(FILE.dossier, FILE.config or discover_cible.charger_config()))
        elif methode == 'GET' and path == '/api/discover/vocabulary':
            handler._envoyer(200, discover_vocabulary_picks.liste(FILE.config or discover_cible.charger_config()))
        elif methode == 'POST' and path == '/api/discover/vocabulary/sync':
            handler._envoyer(200, discover_vocabulary_sync.run(FILE.dossier, FILE.config or discover_cible.charger_config(),
                                                           FILE.requete, busy=FILE.item is not None, automatic=False))
        elif methode == 'GET' and path == '/api/discover/costs':
            # Coûts locaux (IA et voix) : mois en cours et précédent, dernières préparations, plafond Deepgram.
            handler._envoyer(200, discover_costs.rapport(FILE.dossier, FILE.config or discover_cible.charger_config()))
        elif methode == 'POST' and path == '/api/discover/tts':
            config = discover_tts_settings.save(donnees)
            with FILE.verrou:
                FILE.config = config
            handler._envoyer(200, discover_tts_settings.status(FILE.dossier, config))
        elif methode == 'GET' and path == '/api/discover/reviews':
            active = {i['id'] for i in FILE.liste()['items'] if i['status'] == 'pending' and i['stage'] == 'review'}
            handler._envoyer(200, {'reviews': [r for r in discover_review.liste(FILE.dossier) if r['id'] in active]})
        elif methode == 'GET' and path == '/api/discover/review':
            identifiant = parse_qs(urlsplit(handler.path).query).get('id', [''])[0]
            handler._envoyer(200, discover_review.trouver(FILE.dossier, identifiant)[1])
        elif methode == 'POST' and path == '/api/discover/review':
            result = discover_review.action(FILE.dossier, donnees)
            FILE.demarrer()
            handler._envoyer(200, result)
        elif methode == 'GET' and path == '/api/discover/shows':
            handler._envoyer(200, FILE.requete(FILE.config or discover_cible.charger_config(), 'GET', '/atelier/shows'))
        elif methode == 'POST' and path == '/api/discover/show-auto':
            # Préparation automatique d'une chaîne : mêmes règles que dans l'app (vidéos YouTube, deux formules).
            show = str(donnees.get('id', ''))
            if not re.fullmatch(r'[a-z0-9-]{1,64}', show):
                raise ValueError('Émission invalide.')
            corps = {k: donnees[k] for k in ('autoPrepare', 'autoPreset', 'autoLevel') if k in donnees}
            handler._envoyer(200, FILE.requete(FILE.config or discover_cible.charger_config(), 'PATCH', f'/atelier/shows/{show}', corps))
        elif methode == 'POST' and path == '/api/discover/auto-setting':
            if not isinstance(donnees.get('enabled'), bool):
                raise ValueError('Interrupteur invalide.')
            handler._envoyer(200, FILE.requete(FILE.config or discover_cible.charger_config(), 'PUT', '/atelier/settings/auto-prepare', {'enabled': donnees['enabled']}))
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
            if kind not in ('youtube', 'text', 'affaire') or not isinstance(options, dict):
                raise ValueError('Import invalide.')
            corps = {'kind': kind, 'options': options}
            if kind in ('youtube', 'affaire'):
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
        elif methode == 'POST' and path == '/api/discover/remove':
            identifiant = str(donnees.get('id', ''))
            if not re.fullmatch(r'[0-9a-f-]{36}', identifiant):
                raise ValueError('Demande invalide.')
            FILE.requete(FILE.config or discover_cible.charger_config(), 'POST', f'/atelier/queue/{identifiant}/remove', {})
            handler._envoyer(200, {'ok': True})
        elif methode == 'POST' and path == '/api/discover/delete-content':
            contenu = str(donnees.get('contentId', ''))
            if not CONTENU.fullmatch(contenu):
                raise ValueError('Contenu invalide.')
            try:
                FILE.requete(FILE.config or discover_cible.charger_config(), 'DELETE', f'/atelier/contents/{contenu}')
            except discover_cible.ErreurDiscover as erreur:
                if erreur.status != 404:  # déjà supprimé depuis l'app : on nettoie quand même ce Mac
                    raise
            effacees = effacer_versions_locales(FILE.dossier, str(donnees.get('kind', '')), str(donnees.get('ref', '')))
            handler._envoyer(200, {'ok': True, 'localVersions': effacees})
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
        if methode == 'POST':
            FILE.live.invalidate()
    except (OSError, ValueError, RuntimeError, jsonschema.ValidationError) as erreur:
        message = _erreur_discover(erreur)
        if message is None:
            message = str(erreur)[:300] if isinstance(erreur, ValueError) else 'Discover indisponible. Vérifier la configuration et la connexion.'
        handler._envoyer(503, {'erreur': message})
    except Exception:  # un bug ne doit jamais couper la connexion : le navigateur croirait l'Atelier arrêté
        traceback.print_exc()
        handler._envoyer(500, {'erreur': 'Erreur interne de l’Atelier : le détail est dans sa fenêtre Terminal.'})
    return True
