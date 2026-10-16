# -*- coding: utf-8 -*-
"""Import de textes dans l'atelier (LOT 1, cahier v2.0 § 3.1).

Entrées : texte collé, fichier .txt ou .md, article collé (l'URL, l'auteur
et la date ne servent que de provenance : aucune extraction automatique),
production personnelle.

Le bundle reste au nommage à plat de fileToImport/ :

    <slug>.source.<l>.txt|md   source brute, jamais modifiée
    <slug>.transcript.<l>.txt  texte normalisé (affiché et segmenté)
    <slug>.meta.json           sourceType, contentType, provenance, sourceRevision
    <slug>.segments.json       segments par paragraphes puis phrases, sans timings

Aucun audio n'est exigé : le contenu est lisible dès sa publication ;
Kokoro reste facultatif.
"""

import re

import bundles
import pipeline

MAX_CARACTERES = 200_000
TYPES_CONTENU = ("article", "transcript", "personal_output", "other")
LIBELLES_TYPES = {"article": "Article", "transcript": "Transcription",
                  "personal_output": "Production personnelle", "other": "Texte"}
SOURCES_TEXTE = pipeline.SOURCES_TEXTE

_MOTS_FR = set("""le la les un une des du de et est sont dans pour pas que qui
sur avec ce cette ces il elle nous vous ils elles mais ou donc car au aux
été être avoir fait plus très aussi comme tout sa son ses leur leurs je
tu on se ne en par""".split())
_MOTS_EN = set("""the a an and is are was were in on for not that which who
with this these those it he she we you they but or so because of to at by
be been have has had do does did more very also like all his her their i
my your from as if than then there what when""".split())


def nettoyer_texte(texte):
    """Fins de ligne unifiées, caractères de contrôle retirés, espaces de
    fin supprimés, au plus une ligne vide entre deux paragraphes."""
    propre = (texte or "").lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    propre = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", propre)
    propre = "\n".join(ligne.rstrip() for ligne in propre.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", propre).strip()


def markdown_vers_texte(texte):
    """Texte lisible depuis du Markdown : en-tête YAML, balises HTML,
    images, marques de titres, listes, citations et emphase retirées ; un
    lien garde son libellé. Le contenu des blocs de code est conservé."""
    propre = nettoyer_texte(texte)
    propre = re.sub(r"\A---\n.*?\n---\n", "", propre, flags=re.S)
    propre = re.sub(r"^```[^\n]*$", "", propre, flags=re.M)
    propre = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", propre)
    propre = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", propre)
    propre = re.sub(r"<[^>]+>", "", propre)
    propre = re.sub(r"^[ \t]{0,3}#{1,6}[ \t]+", "", propre, flags=re.M)
    propre = re.sub(r"^[ \t]{0,3}>[ \t]?", "", propre, flags=re.M)
    propre = re.sub(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+", "", propre, flags=re.M)
    propre = re.sub(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$", "", propre, flags=re.M)
    propre = re.sub(r"(\*\*|__)(.+?)\1", r"\2", propre)
    propre = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", propre)
    propre = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?!\w)", r"\1", propre)
    propre = re.sub(r"`([^`]+)`", r"\1", propre)
    return nettoyer_texte(propre)


def detecter_langue(texte):
    """Proposition de langue ('fr' | 'en' | None) et confiance (0 à 1),
    par mots fréquents et accents. L'utilisateur confirme toujours."""
    mots = re.findall(r"[a-zà-ÿœæ']+", (texte or "").lower()[:20000])
    if not mots:
        return None, 0.0
    fr = sum(1 for m in mots if m in _MOTS_FR)
    en = sum(1 for m in mots if m in _MOTS_EN)
    fr += sum(1 for m in mots if re.search(r"[éèêàùçôîœ]", m)) * 0.5
    total = fr + en
    if total < 3:
        return None, 0.0
    langue = "fr" if fr > en else "en"
    return langue, round(max(fr, en) / total, 2)


def paragraphes(texte):
    return [p.strip() for p in re.split(r"\n\s*\n", texte or "") if p.strip()]


def apercu(texte):
    return {"caracteres": len(texte or ""), "paragraphes": len(paragraphes(texte)),
            "mots": len(re.findall(r"\w+", texte or ""))}


def segmenter_paragraphes(texte):
    """Segments par paragraphe puis par phrases (~220 caractères) : un
    segment ne mélange jamais deux paragraphes. Ne perd aucun mot."""
    segments = []
    for paragraphe in paragraphes(texte):
        segments.extend(pipeline.segmenter(paragraphe))
    return segments


def type_source(type_contenu, url):
    if type_contenu == "personal_output":
        return "personal_transcript"
    if type_contenu == "article" and url:
        return "article_url"
    return "pasted_text"


def preparer(texte, nom_fichier=None):
    """Analyse un texte avant import (aperçu, langue proposée). Renvoie
    un dict sérialisable, ou lève ValueError."""
    texte_lisible = _texte_lisible(texte, nom_fichier)
    langue, confiance = detecter_langue(texte_lisible)
    return {"apercu": apercu(texte_lisible), "langueProposee": langue,
            "confiance": confiance, "extrait": texte_lisible[:400]}


def _texte_lisible(texte, nom_fichier):
    if not (texte or "").strip():
        raise ValueError("texte vide")
    if len(texte) > MAX_CARACTERES:
        raise ValueError(f"texte trop long ({len(texte)} caractères, maximum {MAX_CARACTERES})")
    if nom_fichier and not re.search(r"\.(txt|md|markdown)$", nom_fichier, re.I):
        raise ValueError("seuls les fichiers .txt et .md sont acceptés")
    est_md = bool(nom_fichier and re.search(r"\.(md|markdown)$", nom_fichier, re.I))
    lisible = markdown_vers_texte(texte) if est_md else nettoyer_texte(texte)
    if not lisible:
        raise ValueError("aucun texte lisible après nettoyage")
    return lisible


def creer_bundle(titre, texte, langue, type_contenu="other", url=None,
                 auteur=None, date=None, nom_fichier=None, niveau="B1",
                 theme=None):
    """Crée le bundle d'un texte. Renvoie (slug, None) ou (None, erreur).
    La langue est celle confirmée par l'utilisateur."""
    titre = " ".join((titre or "").split())
    if not titre:
        return None, "titre requis"
    if langue not in ("fr", "en"):
        return None, "langue à confirmer : fr ou en"
    if type_contenu not in TYPES_CONTENU:
        return None, f"type inconnu : {type_contenu}"
    url = (url or "").strip() or None
    if url and not re.match(r"^https?://", url):
        return None, "l'URL de provenance doit commencer par http:// ou https://"
    try:
        lisible = _texte_lisible(texte, nom_fichier)
    except ValueError as e:
        return None, str(e)
    if niveau not in bundles.NIVEAUX:
        niveau = "B1"

    with pipeline.VERROU:
        slug, doublon = bundles.slug_disponible(bundles.slugifier(titre), url)
        if not slug:
            return None, f"déjà présent : {doublon}"
        extension = "md" if nom_fichier and re.search(r"\.(md|markdown)$", nom_fichier, re.I) else "txt"
        brut = nettoyer_texte(texte) if extension == "txt" else (texte or "").replace("\r\n", "\n")
        # Source immuable, puis texte normalisé (affiché et segmenté)
        pipeline.ecrire_atomique(pipeline.chemin(slug, f"source.{langue}.{extension}"), brut + "\n")
        pipeline.ecrire_atomique(pipeline.chemin(slug, f"transcript.{langue}.txt"), lisible + "\n")

        meta = bundles.construire_meta(slug, titre, url or "", langue, langue,
                                       niveau, theme, statut="prepared")
        meta.update({
            "sourceType": type_source(type_contenu, url),
            "contentKind": "text",
            "contentType": type_contenu,
            "audioLanguage": None,
            "sourceRevision": pipeline.revision_source(lisible),
            "provenance": {k: v for k, v in (("url", url), ("author", (auteur or "").strip() or None),
                                              ("publishedAt", (date or "").strip() or None),
                                              ("fileName", nom_fichier)) if v},
            "processing": {"transcriptionProvider": "import texte"},
        })
        bundles.ecrire_meta(slug, meta)
        segments = []
        for i, morceau in enumerate(segmenter_paragraphes(lisible), 1):
            segment = {"id": f"s{i:03d}", "en": None, "fr": None, "startMs": None, "endMs": None}
            segment[langue] = morceau
            segments.append(segment)
        pipeline.ecrire_segments(slug, segments, segmentationVersion=1, timingSource=None)
        bundles.rafraichir_meta(slug)
        return slug, None
