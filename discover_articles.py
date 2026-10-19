"""Récupération du texte d'un article partagé dans My Mind, depuis ce Mac (connexion ordinaire, mieux acceptée par
les sites de presse que les serveurs du Worker). Aucun contournement : la page publique est lue telle qu'elle est
servie à un visiteur non connecté ; un article réservé aux abonnés est signalé « partiel » ou « inaccessible »."""
import html
import re
import urllib.error
import urllib.request
from html.parser import HTMLParser

from manifeste_validation import ErreurManifeste, url_valide

USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'
MAX_BYTES = 3_000_000
MAX_TEXT = 100_000
MIN_COMPLETE = 600
PAR_TOUR = 3

IGNORE = {'nav', 'footer', 'aside', 'figure', 'figcaption', 'header', 'form', 'button', 'script', 'style', 'noscript', 'svg'}
VIDES = {'br', 'img', 'meta', 'link', 'input', 'hr', 'source', 'wbr'}
FIN_DE_PHRASE = re.compile(r'[.!?…:"”»)\]]$')
PARASITES = re.compile(r'^(read more|related|more on this story|sign up|subscribe|lire aussi|à lire aussi|abonnez-vous|'
                       r'newsletter|advertisement|publicité|photograph|photo|image|credit|crédit)\b', re.I)
MENTIONS = re.compile(r'\s*(Get the newsletter!?|Sign up for (our|the) newsletter[^.]*\.|Abonnez-vous à (notre|la) newsletter[^.]*\.)\s*', re.I)
PAYWALL = re.compile(r'isAccessibleForFree"\s*:\s*"?false|réservé aux abonnés|il vous reste \d+% de cet article|'
                     r'pour lire la suite|subscribe to (continue|read)|this article is (only )?(available )?(for|to) subscribers|'
                     r'already a subscriber|déjà abonné', re.I)


class _Paragraphes(HTMLParser):
    """Paragraphes de la page, en notant s'ils sont dans <article>/<main> et hors navigation, encadrés et légendes."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pile, self.paragraphes, self.courant, self.dans_article = [], [], None, 0
        self.titre_page, self.dans_titre, self.og_titre = '', False, ''

    def handle_starttag(self, tag, attrs):
        if tag == 'meta':
            a = dict(attrs)
            if a.get('property') == 'og:title':
                self.og_titre = a.get('content') or ''
        if tag in VIDES:
            return
        self.pile.append(tag)
        if tag in ('article', 'main'):
            self.dans_article += 1
        if tag == 'title':
            self.dans_titre = True
        if tag == 'p' and not (IGNORE & set(self.pile[:-1])):
            self.courant = [[], self.dans_article > 0]

    def handle_endtag(self, tag):
        if tag == 'title':
            self.dans_titre = False
        if tag == 'p' and self.courant:
            texte = re.sub(r'\s+', ' ', ''.join(self.courant[0])).strip()
            if texte:
                self.paragraphes.append((texte, self.courant[1]))
            self.courant = None
        if tag in self.pile:
            while self.pile and self.pile.pop() != tag:
                pass
        if tag in ('article', 'main'):
            self.dans_article = max(0, self.dans_article - 1)

    def handle_data(self, data):
        if self.dans_titre:
            self.titre_page += data
        if self.courant:
            self.courant[0].append(data)


def extraire(page):
    """(titre, texte, paywall) d'une page d'article. Le texte garde un paragraphe par ligne vide."""
    parseur = _Paragraphes()
    parseur.feed(page)
    dans = [t for t, a in parseur.paragraphes if a]
    candidats = dans if sum(map(len, dans)) > 500 else [t for t, _ in parseur.paragraphes]
    # Un paragraphe de corps est assez long et finit comme une phrase (on écarte titres liés, légendes, boutons).
    corps = [MENTIONS.sub('', t).strip() for t in candidats if len(t) >= 40 and FIN_DE_PHRASE.search(t) and not PARASITES.match(t)]
    corps = [t for t in corps if len(t) >= 40]
    # Les pages finissent souvent par des titres d'articles liés en forme de question : on les retire.
    while corps and corps[-1].endswith('?') and len(corps[-1]) < 160:
        corps.pop()
    titre = html.unescape(parseur.og_titre or parseur.titre_page).strip()
    return titre[:200], '\n\n'.join(corps)[:MAX_TEXT], bool(PAYWALL.search(page))


def statut(texte, paywall):
    if paywall:
        return 'partial' if texte else 'unavailable'
    if len(texte) < MIN_COMPLETE:
        return 'partial' if len(texte) >= 200 else 'unavailable'
    return 'complete'


def recuperer(url, ouvrir=None):
    """Lit la page publique et en extrait l'article : {'status', 'text', 'title'}. Jamais d'exception réseau."""
    ouvrir = ouvrir or urllib.request.urlopen
    try:
        url_valide(url, allow_http=True)
        requete = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,application/xhtml+xml',
                                                       'Accept-Language': 'fr,en;q=0.8'})
        with ouvrir(requete, timeout=20) as reponse:
            url_valide(reponse.geturl(), allow_http=True)  # une redirection ne doit pas mener vers le réseau local
            if 'html' not in (reponse.headers.get('Content-Type') or 'text/html'):
                return {'status': 'unavailable'}
            brut = reponse.read(MAX_BYTES + 1)
            if len(brut) > MAX_BYTES:
                return {'status': 'unavailable'}
            charset = reponse.headers.get_content_charset() or 'utf-8'
    except (ErreurManifeste, urllib.error.URLError, OSError, ValueError):
        return {'status': 'unavailable'}
    titre, texte, paywall = extraire(brut.decode(charset, 'replace'))
    etat = statut(texte, paywall)
    return {'status': etat, 'text': texte, 'title': titre} if etat != 'unavailable' else {'status': 'unavailable'}


# Deux files : notes My Mind (UUID) et articles d'Explorer sans texte dans leur flux (The Guardian).
FILES_ARTICLES = (('/atelier/article-fetches', r'[0-9a-f-]{36}'), ('/atelier/article-texts', r'[0-9a-f]{20}'))


def traiter_en_attente(config, requete, verifier=lambda: None, ouvrir=None):
    """Traite quelques demandes en attente ; renvoie le nombre traité. Appelé quand le préparateur est inactif."""
    traitees = 0
    for chemin, motif in FILES_ARTICLES:
        demandes = requete(config, 'GET', chemin).get('items') or []
        for demande in demandes[:PAR_TOUR]:
            verifier()
            if not re.fullmatch(motif, str(demande.get('id', ''))):
                continue
            resultat = recuperer(str(demande.get('url') or ''), ouvrir)
            requete(config, 'POST', chemin + '/' + demande['id'], resultat)
            traitees += 1
    return traitees
