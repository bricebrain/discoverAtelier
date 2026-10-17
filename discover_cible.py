"""Publication Discover reprenable, sans modifier le pipeline EnglishFluency."""
import http.client
import json
import os
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

from manifeste_validation import valider_manifeste

CONFIG = Path(__file__).resolve().parent / 'config_discover.json'


def charger_config():
    try:
        config = json.loads(CONFIG.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise ValueError('Configurer config_discover.json à partir de son exemple.') from e
    url = urlsplit(config.get('workerUrl', ''))
    token = config.get('atelierToken', '')
    local = url.scheme == 'http' and url.hostname in ('localhost', '127.0.0.1')
    if ((url.scheme != 'https' and not local) or not url.hostname or url.username
            or url.password or url.query or url.fragment or url.path not in ('', '/')
            or len(token) < 32 or '\r' in token or '\n' in token):
        raise ValueError('Configuration Discover invalide.')
    return config


def requete(config, method, path, data=None, fichier=None, headers=None):
    url = urlsplit(config['workerUrl'])
    cls = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
    connection = cls(url.hostname, url.port, timeout=120)
    entetes = {'Authorization': 'Bearer ' + config['atelierToken'], **(headers or {})}
    body = json.dumps(data, ensure_ascii=False).encode('utf-8') if data is not None else None
    if body is not None:
        entetes['Content-Type'] = 'application/json'
    try:
        if fichier:
            with open(fichier, 'rb') as stream:
                connection.request(method, path, body=stream, headers=entetes)
        else:
            connection.request(method, path, body=body, headers=entetes)
        response = connection.getresponse()
        raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise RuntimeError('Réponse Discover trop volumineuse.')
        result = json.loads(raw or b'{}')
        if response.status >= 400:
            # Ne jamais inclure la configuration ou le jeton dans les erreurs.
            code = (result.get('error') or {}).get('code', 'http_error')
            raise RuntimeError(f'Discover {response.status} : {code}')
        return result
    finally:
        connection.close()


def publier_manifeste(manifest, paths, signal=None, config=None):
    valider_manifeste(manifest)
    config = config or charger_config()
    signal = signal or (lambda _: None)
    signal('Déclaration Discover…')
    state = requete(config, 'POST', '/atelier/publications', {'manifest': manifest})
    if state['status'] == 'ready':
        return state
    base = '/atelier/publications/' + state['publicationId']
    for path in state['missing']:
        if path not in paths:
            raise ValueError('Fichier local manquant : ' + path)
        f = manifest['files'][path]
        signal('Envoi Discover : ' + path)
        requete(config, 'PUT', base + '/files/' + quote(path, safe='/'),
                fichier=paths[path], headers={'Content-Type': f['contentType'],
                                             'Content-Length': str(f['size']),
                                             'x-content-sha256': f['sha256']})
    signal('Validation et publication Discover…')
    result = requete(config, 'POST', base + '/commit')
    if result['status'] != 'ready':
        raise RuntimeError('Révision dépassée : la version courante a été conservée.')
    return result


def publier(slug, signal=None):
    import bundles
    from discover_bundle import construire
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{2,95}', slug):
        raise ValueError('Identifiant de bundle invalide pour Discover.')
    manifest, paths = construire(slug)
    result = publier_manifeste(manifest, paths, signal)
    # Métadonnée séparée : la publication EnglishFluency existante reste indépendante.
    with bundles.VERRO:
        meta = bundles.lire_meta(slug)
        meta['discoverPublication'] = {'id': result['publicationId'], 'status': 'ready',
                                      'publishedAt': bundles.maintenant()}
        bundles.ecrire_meta(slug, meta)
    return result
