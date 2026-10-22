"""Catalogue explicite de sources historiques vérifiées ; aucune exploration automatique du Web."""
import json
import re


def catalogue():
    from manifeste_validation import contrats
    return json.loads((contrats() / 'affaires-sources.json').read_text(encoding='utf-8'))


def source_verifiee(url):
    return next((source for source in catalogue() if source['url'] == url), None)


def extraire(source, contenu, nettoyer):
    """Bornes éditoriales vérifiées : exclure menus, formulaires et autres affaires."""
    if source['id'] == 'donoghue':
        match = re.search(r'<h1[^>]*>Case report</h1>(.*?)<!--// CONTENT COL -->', contenu, re.S)
    elif source['id'] == 'carlill':
        match = re.search(r'<div class="entry-content">(.*?)</article>', contenu, re.S)
    else:
        match = re.search(r'<article\b[^>]*>(.*?)</article>', contenu, re.S)
    if not match:
        raise ValueError('La structure de la source a changé : vérifier le texte avant de préparer l’affaire.')
    texte = nettoyer(match[1])
    if source['id'] == 'liebeck':
        debut, fin = texte.find('The Hot Coffee Case'), texte.find('Support our Work')
        if debut < 0 or fin <= debut:
            raise ValueError('Le texte de l’affaire Liebeck est introuvable dans la page source.')
        texte = texte[debut:fin]
        # Deux formulaires publicitaires sont insérés au milieu de l’article.
        texte = re.sub(r'Want more content like this\?.*?Coffee that other restaurants', 'Coffee that other restaurants', texte, flags=re.S)
    if len(texte.split()) < 200:
        raise ValueError('Source trop courte ou illisible pour une histoire vérifiée.')
    return texte.strip()


def recuperer(source, lire, nettoyer):
    raw = lire(source['url'])
    try:
        contenu = raw.decode('utf-8-sig')
    except UnicodeError:
        raise ValueError('La source juridique n’est pas un document HTML UTF-8 lisible.') from None
    texte = extraire(source, contenu, nettoyer)
    return {**source, 'source': 'catalogue_verifie', 'text': texte}
