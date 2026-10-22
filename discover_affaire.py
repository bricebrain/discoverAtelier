"""Une décision à la demande, sans recherche, pagination ni récupération en masse.

Sources vérifiées : wiki.free.law/c/courtlistener/help/api/rest/v4/case-law
et nationalarchives.github.io/ds-find-caselaw-docs/public (XML Akoma Ntoso).
"""
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from discover_source import SourceRefusee

CONFIG = Path(__file__).with_name('config_discover.json')
API = 'https://www.courtlistener.com/api/rest/v4/'
FCL = 'https://caselaw.nationalarchives.gov.uk'
LICENCE_FCL = ('Open Justice Licence — Contains information licensed under the Open Justice Licence: '
               'https://caselaw.nationalarchives.gov.uk/open-justice-licence')
MAX_BYTES = 8_000_000
AKN = '{http://docs.oasis-open.org/legaldocml/ns/akn/3.0}'
UK = '{https://caselaw.nationalarchives.gov.uk/akn}'


class _SansRedirection(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SourceRefusee('La source redirige : fournir le lien définitif de la décision.')


def _lire(url, token=None):
    headers = {'User-Agent': 'DiscoverAtelier/1.0 (single judgment on demand)',
               'Accept': 'application/json' if token else 'application/xml'}
    if token:
        headers['Authorization'] = 'Token ' + token
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.build_opener(_SansRedirection()).open(req, timeout=45) as response:
            raw = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as erreur:
        code = erreur.code
        erreur.close()
        if code in (401, 403) and token:
            raise ValueError('CourtListener refuse le jeton : vérifier courtlistener_token dans config_discover.json.') from None
        if code == 429:
            raise ValueError('La source limite les requêtes ; réessayer plus tard.') from None
        raise ValueError(f'Décision inaccessible (HTTP {code}) : vérifier son URL et sa disponibilité en XML.') from None
    except OSError:
        raise ValueError('Impossible de joindre la source de la décision.') from None
    if len(raw) > MAX_BYTES:
        raise ValueError('Décision trop volumineuse.')
    return raw


def _espaces(texte):
    return re.sub(r'\s+', ' ', texte).strip()


class _TexteHTML(HTMLParser):
    """Garde les blocs et retire les notes, leurs appels, scripts et styles."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.texte, self.pile = [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        marque = ' '.join(attrs.get(k, '') for k in ('class', 'id', 'role', 'rel'))
        ignore = (tag in ('script', 'style', 'sup') or
                  bool(re.search(r'footnote|footref|doc-noteref|doc-endnote', marque, re.I)) or
                  (tag == 'a' and re.match(r'#(?:fn|footnote)', attrs.get('href', ''), re.I)))
        if tag not in ('br', 'hr', 'img', 'meta', 'link', 'input', 'wbr'):
            self.pile.append((tag, ignore or bool(self.pile and self.pile[-1][1])))
        if tag in ('p', 'div', 'br', 'li', 'section', 'h1', 'h2', 'h3'):
            self.texte.append('\n')

    def handle_endtag(self, tag):
        if any(t == tag for t, _ in self.pile):
            while self.pile and self.pile.pop()[0] != tag:
                pass
        if tag in ('p', 'div', 'li', 'section'):
            self.texte.append('\n')

    def handle_data(self, data):
        if not self.pile or not self.pile[-1][1]:
            self.texte.append(data)


def _html(texte):
    parseur = _TexteHTML()
    parseur.feed(texte)
    return '\n\n'.join(_espaces(p) for p in ''.join(parseur.texte).splitlines() if p.strip())


def _api(url, ressource, token):
    if not isinstance(url, str) or not re.fullmatch(re.escape(API + ressource + '/') + (r'[a-z0-9-]+/' if ressource == 'courts' else r'[0-9]+/'), url):
        raise ValueError('Lien interne CourtListener invalide.')
    try:
        obj = json.loads(_lire(url, token))
    except (ValueError, UnicodeError) as erreur:
        raise ValueError('Réponse CourtListener illisible : ' + str(erreur)) from None
    if not isinstance(obj, dict):
        raise ValueError('Réponse CourtListener invalide.')
    return obj


def _courtlistener(url, identifiant, config):
    if config is None:
        try:
            config = json.loads(CONFIG.read_text(encoding='utf-8'))
        except FileNotFoundError:
            config = {}
        except (OSError, ValueError):
            raise ValueError('Impossible de lire config_discover.json.') from None
    token = config.get('courtlistener_token')
    if not isinstance(token, str) or not token.strip():
        raise ValueError('CourtListener nécessite un jeton : ajouter courtlistener_token dans config_discover.json '
                         '(https://www.courtlistener.com/profile/api-token/).')
    token = token.strip()
    if re.search(r'\s', token):
        raise ValueError('courtlistener_token invalide : aucun espace ni retour à la ligne autorisé.')
    cluster = _api(API + f'clusters/{identifiant}/', 'clusters', token)
    docket = _api(cluster.get('docket'), 'dockets', token)
    court = _api(docket.get('court'), 'courts', token) if re.fullmatch(
        re.escape(API + 'courts/') + r'[a-z0-9-]+/', str(docket.get('court'))) else None
    # Les identifiants de juridiction sont textuels, contrairement aux autres ressources.
    if court is None:
        raise ValueError('Juridiction CourtListener invalide.')
    textes = []
    for lien in cluster.get('sub_opinions') or []:
        opinion = _api(lien, 'opinions', token)
        contenu = next((opinion[k] for k in ('html_with_citations', 'html_columbia', 'html_lawbox', 'html', 'html_anon_2020')
                        if opinion.get(k)), '')
        if not contenu:
            # Sans balisage, impossible de distinguer sûrement toutes les notes du corps.
            raise ValueError('CourtListener ne fournit pas de texte balisé permettant de retirer les notes.')
        textes.append(_html(contenu))
    return {'source': 'courtlistener', 'url': url, 'title': cluster.get('case_name') or docket.get('case_name') or '',
            'court': court.get('full_name') or court.get('short_name') or '', 'date': cluster.get('date_filed') or '',
            'citation': '; '.join(c.get('citation') or ' '.join(str(c[k]) for k in ('volume', 'reporter', 'page') if c.get(k))
                                  for c in cluster.get('citations', [])),
            'text': '\n\n'.join(textes),
            'licence': 'Décisions judiciaires américaines : domaine public ; https://www.courtlistener.com/terms/'}


def _find_case_law(url):
    raw = _lire(url + '/data.xml')
    if re.search(br'<!DOCTYPE|<!ENTITY', raw, re.I):
        raise ValueError('Déclarations XML externes refusées.')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise ValueError('La source ne contient pas de décision XML Akoma Ntoso lisible.') from None
    judgment = root.find(AKN + 'judgment')
    if judgment is None:
        raise ValueError('La source XML ne contient pas de judgment Akoma Ntoso.')
    work = judgment.find('.//' + AKN + 'FRBRWork')
    def attribut(tag, cle):
        node = work.find(AKN + tag) if work is not None else None
        return node.get(cle, '') if node is not None else ''
    def valeur(tag):
        return _espaces(''.join(judgment.findtext('.//' + tag, default='')))
    # Retirer les notes en conservant leur tail (suite de la phrase dans le parent).
    for parent in judgment.iter():
        for enfant in list(parent):
            if enfant.tag in (AKN + 'authorialNote', AKN + 'noteRef'):
                index = list(parent).index(enfant)
                if index:
                    precedent = parent[index - 1]
                    precedent.tail = (precedent.tail or '') + (enfant.tail or '')
                else:
                    parent.text = (parent.text or '') + (enfant.tail or '')
                parent.remove(enfant)
    parties = [judgment.find(AKN + tag) for tag in ('judgmentBody', 'conclusions')]
    textes = []
    for partie in parties:
        if partie is not None:
            # Les blocs p peuvent contenir des tableaux : ne pas extraire deux fois leurs enfants.
            def blocs(node):
                if node.tag == AKN + 'p':
                    yield _espaces(''.join(node.itertext()))
                else:
                    for enfant in node:
                        yield from blocs(enfant)
            textes.extend(blocs(partie))
    auteur = attribut('FRBRauthor', 'href').lstrip('#')
    cour = next((n.get('showAs', '') for n in judgment.iter(AKN + 'TLCOrganization') if n.get('eId') == auteur), '')
    return {'source': 'find_case_law', 'url': url, 'title': attribut('FRBRname', 'value') or valeur(AKN + 'docTitle'),
            'court': cour or valeur(UK + 'court'), 'date': attribut('FRBRdate', 'date'),
            'citation': valeur(UK + 'cite') or valeur(AKN + 'neutralCitation'),
            'text': '\n\n'.join(t for t in textes if t), 'licence': LICENCE_FCL}


def normaliser_url_affaire(url):
    """Contrôle local identique à celui du Worker, sans accès réseau."""
    try:
        parsed = urlsplit(url)
        valide = (isinstance(url, str) and len(url) <= 500 and parsed.scheme == 'https'
                  and not parsed.username and not parsed.password and parsed.port in (None, 443)
                  and not parsed.query and not parsed.fragment)
    except (TypeError, ValueError):
        valide = False
    if valide:
        from discover_affaire_sources import source_verifiee
        if source_verifiee(url):
            return url
        chemin = re.sub(r'/data\.xml$', '', parsed.path.rstrip('/'))
        if parsed.hostname in ('courtlistener.com', 'www.courtlistener.com') and re.fullmatch(r'/opinion/[0-9]+(?:/[a-zA-Z0-9_-]+)?', chemin):
            return 'https://www.courtlistener.com' + chemin + '/'
        if parsed.hostname == 'caselaw.nationalarchives.gov.uk' and re.fullmatch(r'/(?:[a-z]+/(?:[a-z]+/)?[0-9]{4}/[0-9]+|d-[0-9a-f-]{36})', chemin):
            return FCL + chemin
    raise SourceRefusee('Fournir le lien HTTPS d’une décision CourtListener, Find Case Law ou du catalogue de sources vérifiées.')


def recuperer_affaire(url, config=None):
    """Charge une seule URL explicite ; config facultative, lue sur disque pour CourtListener."""
    url = normaliser_url_affaire(url)
    from discover_affaire_sources import source_verifiee, recuperer
    selection = source_verifiee(url)
    if selection:
        return recuperer(selection, _lire, _html)
    try:
        parsed = urlsplit(url)
        valide = (parsed.scheme == 'https' and not parsed.username and not parsed.password
                  and parsed.port in (None, 443) and not parsed.query)
    except (TypeError, ValueError):
        valide = False
    if not valide:
        raise SourceRefusee('Fournir une URL HTTPS de décision CourtListener ou Find Case Law, sans paramètres.')
    chemin = parsed.path.rstrip('/')
    if parsed.hostname in ('courtlistener.com', 'www.courtlistener.com'):
        match = re.fullmatch(r'/opinion/([0-9]+)(?:/[a-zA-Z0-9_-]+)?', chemin)
        if not match:
            raise SourceRefusee('CourtListener : fournir le lien /opinion/identifiant/ de la décision.')
        resultat = _courtlistener('https://www.courtlistener.com' + chemin + '/', match[1], config)
    elif parsed.hostname == 'caselaw.nationalarchives.gov.uk':
        chemin = re.sub(r'/data\.xml$', '', chemin)
        if not re.fullmatch(r'/(?:[a-z]+/(?:[a-z]+/)?[0-9]{4}/[0-9]+|d-[0-9a-f-]{36})', chemin):
            raise SourceRefusee('Find Case Law : fournir le lien d’une seule décision, pas une recherche ou une liste.')
        resultat = _find_case_law(FCL + chemin)
    else:
        raise SourceRefusee('Source refusée : seuls CourtListener et Find Case Law sont acceptés.')
    if not resultat['text'].strip() or not resultat['title'].strip():
        raise ValueError('La décision ne contient pas de titre ou de texte exploitable.')
    return resultat
