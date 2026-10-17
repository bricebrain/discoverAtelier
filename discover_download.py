"""Téléchargements bornés : DNS public épinglé, redirections revalidées, noms locaux calculés."""
import hashlib
import http.client
import ipaddress
import os
import socket
import ssl
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit


def cible_publique(url):
    p = urlsplit(url)
    if (p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password
            or p.fragment or p.port not in (None, 80 if p.scheme == 'http' else 443)):
        raise ValueError('Adresse de média interdite.')
    ips = list(dict.fromkeys(a[4][0] for a in socket.getaddrinfo(
        p.hostname, p.port or (443 if p.scheme == 'https' else 80), type=socket.SOCK_STREAM)))
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError('Le média doit être hébergé sur une adresse publique.')
    return p, ips


def ouvrir(url):
    p, ips = cible_publique(url)
    port = p.port or (443 if p.scheme == 'https' else 80)
    derniere = None
    # Certaines réponses DNS annoncent plusieurs routes dont une seule est joignable.
    for ip in ips:
        connection = http.client.HTTPConnection(p.hostname, port, timeout=30)
        sock = None
        try:
            sock = socket.create_connection((ip, port), timeout=8)
            if p.scheme == 'https':
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=p.hostname)
            sock.settimeout(30)
            connection.sock = sock
            connection.request('GET', (p.path or '/') + ('?' + p.query if p.query else ''),
                               headers={'User-Agent': 'discover-atelier/1.0', 'Accept-Encoding': 'identity'})
            return connection, connection.getresponse()
        except (OSError, http.client.HTTPException) as erreur:
            derniere = erreur
            connection.close()
            if sock:
                sock.close()
    raise RuntimeError('Le serveur du média ne répond pas.') from derniere


def empreinte(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def telecharger(url, chemin, limite, verifier=lambda: None):
    chemin = Path(chemin)
    temporaire = chemin.with_suffix(chemin.suffix + '.part')
    debut = time.monotonic()
    try:
        for saut in range(4):
            verifier()
            connexion, reponse = ouvrir(url)
            try:
                if reponse.status in (301, 302, 303, 307, 308):
                    location = reponse.getheader('Location')
                    if not location or saut == 3:
                        raise ValueError('Trop de redirections du média.')
                    url = urljoin(url, location)
                    continue
                if reponse.status != 200:
                    raise RuntimeError(f'Média indisponible (HTTP {reponse.status}).')
                longueur = reponse.getheader('Content-Length')
                attendu = int(longueur) if longueur is not None else None
                if attendu is not None and attendu > limite:
                    raise ValueError('Média trop volumineux.')
                taille = 0
                with temporaire.open('wb') as sortie:
                    while True:
                        verifier()
                        if time.monotonic() - debut > 1800:
                            raise RuntimeError('Téléchargement trop long.')
                        bloc = reponse.read(64 * 1024)
                        if not bloc:
                            break
                        taille += len(bloc)
                        if taille > limite:
                            raise ValueError('Média trop volumineux.')
                        sortie.write(bloc)
                if taille == 0:
                    raise ValueError('Média vide.')
                if attendu is not None and taille != attendu:
                    raise RuntimeError('Téléchargement incomplet.')
                verifier()
                os.replace(temporaire, chemin)
                return empreinte(chemin)
            finally:
                connexion.close()
    finally:
        temporaire.unlink(missing_ok=True)
