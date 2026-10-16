# -*- coding: utf-8 -*-
"""Pipeline bilingue English Fluency — cahier des charges v1.0 (P0).

Logique métier centralisée : segmentation, prompts ChatGPT JSON,
validation des réponses collées, sélection de l'audio anglais publié et
`etat_publication` (équivalent de `canPublish`).

Le nommage à plat de fileToImport/ est conservé ; ce module y ajoute :

    <slug>.segments.json   segments EN/FR appariés (s001, s002…), avec
                           segmentationVersion et timingSource
    <slug>.pedagogy.json   chunks + points de grammaire
    <slug>.audio-en.mp3    audio Kokoro (source FR uniquement)
    <slug>.audio-en.timings.json  timings propres à l'audio Kokoro
    <slug>.transcript.<l>.srt     SRT MacWhisper (timings de l'audio original)

Versions (AUDIT_LOT0.md § 8) : sourceRevision, segmentationVersion,
audioRevision, contentRevision, variantId ; l'audio est publié sous une clé
R2 immuable prepared-content/<id>-faithful-<audioRevision>.mp3.

L'audio original reste <slug>.mp3 et n'est jamais écrasé. Les anciens
fichiers (transcript, translation, adapted) sont lus mais jamais
supprimés : un bundle ancien demande simplement une traduction segmentée.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading

import bundles
import horodatage

VERROU = threading.RLock()

NIVEAUX_PEDAGOGIE = ("A2", "B1", "B2")
TYPES_CHUNK = ("vocabulary", "collocation", "phrasal_verb", "idiom",
               "useful_expression", "grammar_pattern")
TAILLE_LOT_TRADUCTION = 40   # segments par prompt de traduction
TAILLE_LOT_PEDAGOGIE = 80    # segments par prompt d'analyse
SEGMENT_CIBLE = 220          # caractères visés par segment
SEGMENT_MAX = 420            # au-delà, une phrase est découpée


# ---------------------------------------------------------------------------
# Fichiers
# ---------------------------------------------------------------------------
def chemin(slug, suffixe):
    return os.path.join(bundles.DOSSIER_BUNDLES, f"{slug}.{suffixe}")


def ecrire_atomique(chemin_cible, contenu):
    """Écrit dans un fichier temporaire caché puis renomme : un bundle
    n'est jamais laissé à moitié écrit."""
    dossier = os.path.dirname(chemin_cible)
    descripteur, temporaire = tempfile.mkstemp(dir=dossier, prefix=".tmp-")
    try:
        with os.fdopen(descripteur, "w", encoding="utf-8") as f:
            f.write(contenu)
        os.replace(temporaire, chemin_cible)
    except BaseException:
        if os.path.exists(temporaire):
            os.remove(temporaire)
        raise


def ecrire_json(chemin_cible, donnees):
    ecrire_atomique(chemin_cible,
                    json.dumps(donnees, ensure_ascii=False, indent=2) + "\n")


def lire_json(chemin_source):
    try:
        with open(chemin_source, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def empreinte(texte):
    return hashlib.sha256((texte or "").encode("utf-8")).hexdigest()[:16]


def revision_source(contenu):
    """sourceRevision : 16 hex du SHA-256 de la source brute (octets de
    l'audio original, ou texte normalisé en UTF-8)."""
    if isinstance(contenu, str):
        contenu = contenu.replace("\r\n", "\n").strip().encode("utf-8")
    return hashlib.sha256(contenu or b"").hexdigest()[:16]


_CACHE_REVISION_AUDIO = {}


def revision_audio(chemin_audio):
    """audioRevision : 8 hex du SHA-256 des octets du fichier audio, ou
    None s'il est illisible. Mis en cache par (taille, date de
    modification) : etat_publication est appelé à chaque affichage."""
    try:
        infos = os.stat(chemin_audio)
    except (OSError, TypeError):
        return None
    cle = (chemin_audio, infos.st_size, infos.st_mtime_ns)
    if cle not in _CACHE_REVISION_AUDIO:
        sha = hashlib.sha256()
        with open(chemin_audio, "rb") as f:
            for bloc in iter(lambda: f.read(1 << 20), b""):
                sha.update(bloc)
        _CACHE_REVISION_AUDIO[cle] = sha.hexdigest()[:8]
    return _CACHE_REVISION_AUDIO[cle]


def revision_source_bundle(slug, meta):
    """sourceRevision du bundle : celle du meta (imports texte), sinon
    l'empreinte de l'audio original <slug>.mp3."""
    if (meta or {}).get("sourceRevision"):
        return meta["sourceRevision"]
    chemin_audio = chemin_bundle(f"{slug}.mp3")
    try:
        infos = os.stat(chemin_audio)
    except OSError:
        return None
    cle = ("source", chemin_audio, infos.st_size, infos.st_mtime_ns)
    if cle not in _CACHE_REVISION_AUDIO:
        sha = hashlib.sha256()
        with open(chemin_audio, "rb") as f:
            for bloc in iter(lambda: f.read(1 << 20), b""):
                sha.update(bloc)
        _CACHE_REVISION_AUDIO[cle] = sha.hexdigest()[:16]
    return _CACHE_REVISION_AUDIO[cle]


VARIANTE_FIDELE = "faithful"


def id_variante(content_id, kind=VARIANTE_FIDELE):
    return f"{content_id}~{kind}"


def cle_audio_r2(content_id, audio_revision, kind=VARIANTE_FIDELE):
    """Clé R2 immuable : une nouvelle révision audio = une nouvelle clé."""
    return f"prepared-content/{content_id}-{kind}-{audio_revision}.mp3"


# ---------------------------------------------------------------------------
# Langues (adaptateur anciens / nouveaux meta)
# ---------------------------------------------------------------------------
def langue_source(meta):
    """'fr' ou 'en' : sourceLanguage (v2) sinon audioLanguage (v1)."""
    langue = (meta or {}).get("sourceLanguage") or (meta or {}).get(
        "audioLanguage")
    return langue if langue in ("fr", "en") else None


def langue_cible(source):
    return "en" if source == "fr" else "fr"


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------
def _decouper_longue(phrase):
    """Coupe une phrase trop longue (sous-titres sans ponctuation) aux
    virgules, puis par paquets de mots."""
    morceaux, courant = [], ""
    for partie in re.split(r"(?<=[,;:])\s+", phrase):
        mots = partie.split()
        for mot in mots:
            if courant and len(courant) + len(mot) + 1 > SEGMENT_CIBLE:
                morceaux.append(courant)
                courant = mot
            else:
                courant = f"{courant} {mot}".strip()
    if courant:
        morceaux.append(courant)
    return morceaux


def segmenter(texte):
    """Découpe un texte en unités de traduction cohérentes (1 à quelques
    phrases, ~220 caractères). Ne perd ni n'ajoute aucun mot."""
    propre = " ".join((texte or "").split())
    if not propre:
        return []
    phrases = []
    for phrase in re.split(r"(?<=[.!?…])\s+", propre):
        if len(phrase) > SEGMENT_MAX:
            phrases.extend(_decouper_longue(phrase))
        elif phrase:
            phrases.append(phrase)

    segments, courant = [], ""
    for phrase in phrases:
        if courant and len(courant) + len(phrase) + 1 > SEGMENT_CIBLE:
            segments.append(courant)
            courant = phrase
        else:
            courant = f"{courant} {phrase}".strip()
    if courant:
        segments.append(courant)
    return segments


def lire_segments(slug):
    donnees = lire_json(chemin(slug, "segments.json"))
    if not donnees or not isinstance(donnees.get("segments"), list):
        return None
    return donnees["segments"]


def lire_infos_segments(slug):
    """segmentationVersion (1 par défaut, anciens bundles) et timingSource
    (None : pas d'horodatage) de segments.json."""
    donnees = lire_json(chemin(slug, "segments.json")) or {}
    return {"segmentationVersion": donnees.get("segmentationVersion") or 1,
            "timingSource": donnees.get("timingSource")}


def ecrire_segments(slug, segments, **infos):
    """Écrit segments.json en conservant segmentationVersion et
    timingSource (sauf s'ils sont fournis)."""
    donnees = {**lire_infos_segments(slug), **infos, "segments": segments}
    ecrire_json(chemin(slug, "segments.json"), donnees)


def _texte_transcript_source(slug, source):
    fichiers = bundles.decrire_fichiers(slug)
    if fichiers["transcript"] and fichiers["langueTranscript"] == source:
        with open(os.path.join(bundles.DOSSIER_BUNDLES,
                               fichiers["transcript"]), encoding="utf-8") as f:
            return f.read()
    return None


def initialiser_segments(slug):
    """Crée <slug>.segments.json depuis la transcription source s'il
    n'existe pas. Renvoie (segments, erreur)."""
    with VERROU:
        existants = lire_segments(slug)
        if existants:
            return existants, None
        meta = bundles.lire_meta(slug)
        source = langue_source(meta)
        if not source:
            return None, "langue source inconnue (fr/en) dans le meta"
        segments = segments_depuis_srt(slug, source)
        if segments:
            ecrire_segments(slug, segments, segmentationVersion=1,
                            timingSource=horodatage.TIMING_SRT)
            return segments, None
        texte = _texte_transcript_source(slug, source)
        if not texte or not texte.strip():
            return None, f"transcription {source.upper()} manquante"
        segments = []
        for i, morceau in enumerate(segmenter(texte), 1):
            segment = {"id": f"s{i:03d}", "en": None, "fr": None,
                       "startMs": None, "endMs": None}
            segment[source] = morceau
            segments.append(segment)
        ecrire_segments(slug, segments, segmentationVersion=1, timingSource=None)
        return segments, None


def segments_depuis_srt(slug, source):
    """Segments horodatés depuis <slug>.transcript.en.srt (audio anglais
    authentique). None si la source n'est pas anglaise ou sans SRT : les
    timings d'un audio français ne sont jamais réutilisés (v1.2 § 6.1)."""
    if source != "en":
        return None
    try:
        with open(chemin(slug, "transcript.en.srt"), encoding="utf-8") as f:
            repliques = horodatage.lire_srt(f.read())
    except OSError:
        return None
    if not repliques:
        return None
    return [{"id": f"s{i:03d}", "en": g["text"], "fr": None,
             "startMs": g["startMs"], "endMs": g["endMs"]}
            for i, g in enumerate(horodatage.regrouper_repliques(repliques), 1)]


def horodatage_possible(slug):
    """L'action « Horodater » re-segmente un ancien bundle anglais depuis
    son SRT. Renvoie (possible, avertissement ou raison)."""
    meta = bundles.lire_meta(slug) or {}
    if langue_source(meta) != "en":
        return False, "seule une source anglaise (audio authentique) s'horodate par SRT"
    if lire_infos_segments(slug)["timingSource"] == horodatage.TIMING_SRT:
        return False, "déjà horodaté"
    segments = lire_segments(slug) or []
    deja_traduit = any((s.get("fr") or "").strip() for s in segments)
    return True, ("La re-segmentation change les segments : la traduction et "
                  "l'analyse pédagogique seront à refaire." if deja_traduit else None)


def horodater(slug):
    """Re-segmente un bundle anglais depuis son SRT (nouvelle
    segmentationVersion). Les anciens segments et l'analyse sont
    sauvegardés à côté (.v<n>.bak.json), jamais supprimés.
    Renvoie (segments, erreur)."""
    with VERROU:
        possible, raison = horodatage_possible(slug)
        if not possible:
            return None, raison
        meta = bundles.lire_meta(slug) or {}
        nouveaux = segments_depuis_srt(slug, "en")
        if not nouveaux:
            return None, "SRT anglais manquant : transcrire d'abord avec MacWhisper (SRT)"
        version = lire_infos_segments(slug)["segmentationVersion"]
        for nom in ("segments.json", "pedagogy.json"):
            if os.path.exists(chemin(slug, nom)):
                base = nom.rsplit(".", 1)[0]
                shutil.copyfile(chemin(slug, nom), chemin(slug, f"{base}.v{version}.bak.json"))
        if os.path.exists(chemin(slug, "pedagogy.json")):
            os.remove(chemin(slug, "pedagogy.json"))
        ecrire_segments(slug, nouveaux, segmentationVersion=version + 1,
                        timingSource=horodatage.TIMING_SRT)
        _maj_meta(slug, translationValidated=False,
                  englishTextRevision=meta.get("englishTextRevision", 0) + 1)
        return nouveaux, None


def texte_complet(segments, langue):
    return "\n".join((s.get(langue) or "").strip() for s in segments or [])


def traduction_complete(segments):
    return bool(segments) and all(
        (s.get("en") or "").strip() and (s.get("fr") or "").strip()
        for s in segments)


def lots(elements, taille):
    return [elements[i:i + taille] for i in range(0, len(elements), taille)]


def _segments_json(segments, langue):
    lignes = [json.dumps({"id": s["id"], "text": s.get(langue) or ""},
                         ensure_ascii=False) for s in segments]
    return "[\n" + ",\n".join(lignes) + "\n]"


# ---------------------------------------------------------------------------
# Prompts (cahier des charges §6)
# ---------------------------------------------------------------------------
PROMPT_FR_EN = """Tu es un traducteur professionnel et professeur d'anglais britannique.
Traduis intégralement les segments français en anglais britannique naturel.
Conserve le sens, les faits, le registre, l'ordre des idées et les nuances.
N'ajoute rien, n'omets rien, ne résume pas. Ne simplifie pas artificiellement les informations.
Conserve chaque id et l'ordre des segments. N'invente aucun segment.
Retourne uniquement un JSON valide, sans Markdown :
{{
  "segments": [
    {{"id": "s001", "text": "Traduction anglaise correspondante"}}
  ]
}}
{lot}Segments français :
{segments}"""

PROMPT_EN_FR = """Tu es un traducteur professionnel.
Traduis intégralement les segments anglais en français naturel, courant et fidèle.
Conserve le sens, les faits, le registre, l'ordre des idées et les nuances.
N'ajoute rien, n'omets rien, ne résume pas.
Conserve chaque id et l'ordre des segments. N'invente aucun segment.
Retourne uniquement un JSON valide, sans Markdown :
{{
  "segments": [
    {{"id": "s001", "text": "Traduction française correspondante"}}
  ]
}}
{lot}Segments anglais :
{segments}"""

PROMPT_PEDAGOGIE = """Tu es un professeur d'anglais britannique spécialisé dans l'enseignement aux francophones A2+/B1.
Analyse UNIQUEMENT les segments anglais fournis.
Sélectionne les éléments les plus utiles, sans chercher à remplir artificiellement un quota.
Extrais jusqu'à 12 chunks. Favorise : vocabulaire difficile, faux amis,
collocations, phrasal verbs, expressions idiomatiques et structures réutilisables.
Repère séparément jusqu'à 4 points grammaticaux réellement illustrés dans le texte.
Pour chaque élément, indique un segmentId existant. N'invente pas de citation source.
Les explications et traductions sont en français naturel. Les exemples anglais sont courts,
idiomatiques et cohérents avec un anglais britannique.
Niveaux autorisés : A2, B1, B2. Types autorisés : vocabulary, collocation,
phrasal_verb, idiom, useful_expression, grammar_pattern.
Retourne uniquement ce JSON valide (les valeurs ci-dessous illustrent le schéma, ne les recopie pas) :
{{
  "chunks": [
    {{
      "expression": "figure out",
      "meaningFr": "comprendre, trouver",
      "exampleEn": "I can't figure it out.",
      "exampleFr": "Je n'arrive pas à comprendre.",
      "level": "B1",
      "type": "phrasal_verb",
      "context": "Lorsque l'on cherche à comprendre un problème",
      "explanationFr": "Figure out signifie comprendre ou trouver une solution.",
      "sourceSegmentId": "s001"
    }}
  ],
  "grammarPoints": [
    {{
      "title": "Need to + infinitif",
      "explanationFr": "Cette construction sert à exprimer une nécessité.",
      "sourceExcerpt": "We need to understand this.",
      "exampleEn": "You need to check the details.",
      "exampleFr": "Tu dois vérifier les détails.",
      "level": "A2",
      "sourceSegmentId": "s001"
    }}
  ]
}}
Si aucun point grammatical pertinent ne ressort, renvoie "grammarPoints": [].
{lot}Segments anglais :
{segments}"""


def _mention_lot(numero, total):
    if total <= 1:
        return ""
    return (f"(Section {numero}/{total} d'un texte plus long : traite "
            f"uniquement ces segments.)\n")


def prompt_traduction(slug):
    """Prompt du prochain lot à traduire. Renvoie (prompt, info, erreur)."""
    segments, erreur = initialiser_segments(slug)
    if erreur:
        return None, None, erreur
    source = langue_source(bundles.lire_meta(slug))
    cible = langue_cible(source)
    tous = lots(segments, TAILLE_LOT_TRADUCTION)
    for numero, lot in enumerate(tous, 1):
        if any(not (s.get(cible) or "").strip() for s in lot):
            gabarit = PROMPT_FR_EN if source == "fr" else PROMPT_EN_FR
            prompt = gabarit.format(lot=_mention_lot(numero, len(tous)),
                                    segments=_segments_json(lot, source))
            return prompt, {"lot": numero, "lots": len(tous),
                            "sens": f"{source}→{cible}"}, None
    return None, None, "traduction déjà complète pour tous les segments"


def lire_pedagogie(slug):
    return lire_json(chemin(slug, "pedagogy.json"))


def _pedagogie_a_jour(pedagogie, hash_en):
    return bool(pedagogie) and pedagogie.get("englishTextHash") == hash_en


def prompt_pedagogie(slug):
    """Prompt d'analyse du prochain lot de segments anglais."""
    segments = lire_segments(slug)
    if not traduction_complete(segments):
        return None, None, "traduction incomplète : terminez d'abord les deux textes"
    hash_en = empreinte(texte_complet(segments, "en"))
    pedagogie = lire_pedagogie(slug)
    faits = pedagogie.get("lotsAnalyses", 0) if _pedagogie_a_jour(
        pedagogie, hash_en) else 0
    tous = lots(segments, TAILLE_LOT_PEDAGOGIE)
    if faits >= len(tous):
        return None, None, "analyse pédagogique déjà complète"
    numero = faits + 1
    prompt = PROMPT_PEDAGOGIE.format(
        lot=_mention_lot(numero, len(tous)),
        segments=_segments_json(tous[numero - 1], "en"))
    return prompt, {"lot": numero, "lots": len(tous)}, None


# ---------------------------------------------------------------------------
# Validation des réponses collées
# ---------------------------------------------------------------------------
def parser_json_colle(texte):
    """Parse un JSON collé depuis ChatGPT. Tolère seulement une clôture
    ```json … ``` autour. Renvoie (objet, erreur)."""
    brut = (texte or "").strip()
    clos = re.match(r"^```(?:json)?\s*(.*?)\s*```$", brut, re.S)
    if clos:
        brut = clos.group(1)
    try:
        objet = json.loads(brut)
    except ValueError as e:
        return None, f"JSON invalide : {e}"
    if not isinstance(objet, dict):
        return None, "JSON invalide : un objet { … } est attendu"
    return objet, None


def valider_traduction(objet, segments):
    """Renvoie ({id: texte}, erreurs)."""
    erreurs = []
    elements = objet.get("segments")
    if not isinstance(elements, list) or not elements:
        return {}, ['"segments" doit être une liste non vide']
    connus = {s["id"] for s in segments}
    traductions = {}
    for i, element in enumerate(elements, 1):
        if not isinstance(element, dict):
            erreurs.append(f"segment n°{i} : objet attendu")
            continue
        identifiant, texte = element.get("id"), element.get("text")
        if identifiant not in connus:
            erreurs.append(f"segment n°{i} : id inconnu {identifiant!r}")
        elif identifiant in traductions:
            erreurs.append(f"segment {identifiant} : en double")
        elif not isinstance(texte, str) or not texte.strip():
            erreurs.append(f"segment {identifiant} : texte vide")
        else:
            traductions[identifiant] = " ".join(texte.split())
    return traductions, erreurs


def _texte_requis(element, cle, prefixe, erreurs):
    valeur = element.get(cle)
    if not isinstance(valeur, str) or not valeur.strip():
        erreurs.append(f"{prefixe} : « {cle} » manquant")
        return None
    return valeur.strip()


def _texte_optionnel(element, cle):
    valeur = element.get(cle)
    return valeur.strip() if isinstance(valeur, str) and valeur.strip() else None


def valider_pedagogie(objet, ids_segments):
    """Renvoie (chunks, grammarPoints, erreurs). Les ids c001/g001 sont
    attribués par l'application."""
    erreurs = []
    chunks_bruts = objet.get("chunks")
    grammaire_brute = objet.get("grammarPoints", [])
    if not isinstance(chunks_bruts, list):
        erreurs.append('"chunks" doit être une liste (éventuellement vide)')
        chunks_bruts = []
    if not isinstance(grammaire_brute, list):
        erreurs.append('"grammarPoints" doit être une liste (éventuellement vide)')
        grammaire_brute = []

    def commun(element, prefixe):
        niveau = element.get("level")
        if niveau not in NIVEAUX_PEDAGOGIE:
            erreurs.append(f"{prefixe} : niveau {niveau!r} non autorisé (A2, B1, B2)")
        segment = element.get("sourceSegmentId")
        if segment not in ids_segments:
            erreurs.append(f"{prefixe} : sourceSegmentId {segment!r} inexistant")
        return niveau, segment

    chunks = []
    for i, element in enumerate(chunks_bruts, 1):
        prefixe = f"chunk n°{i}"
        if not isinstance(element, dict):
            erreurs.append(f"{prefixe} : objet attendu")
            continue
        expression = _texte_requis(element, "expression", prefixe, erreurs)
        sens = _texte_requis(element, "meaningFr", prefixe, erreurs)
        type_chunk = element.get("type")
        if type_chunk not in TYPES_CHUNK:
            erreurs.append(f"{prefixe} : type {type_chunk!r} inconnu")
        niveau, segment = commun(element, prefixe)
        chunks.append({
            "expression": expression, "meaningFr": sens,
            "exampleEn": _texte_optionnel(element, "exampleEn"),
            "exampleFr": _texte_optionnel(element, "exampleFr"),
            "level": niveau, "type": type_chunk,
            "context": _texte_optionnel(element, "context"),
            "explanationFr": _texte_optionnel(element, "explanationFr"),
            "sourceSegmentId": segment,
        })

    grammaire = []
    for i, element in enumerate(grammaire_brute, 1):
        prefixe = f"point de grammaire n°{i}"
        if not isinstance(element, dict):
            erreurs.append(f"{prefixe} : objet attendu")
            continue
        titre = _texte_requis(element, "title", prefixe, erreurs)
        explication = _texte_requis(element, "explanationFr", prefixe, erreurs)
        niveau, segment = commun(element, prefixe)
        grammaire.append({
            "title": titre, "explanationFr": explication,
            "sourceExcerpt": _texte_optionnel(element, "sourceExcerpt"),
            "exampleEn": _texte_optionnel(element, "exampleEn"),
            "exampleFr": _texte_optionnel(element, "exampleFr"),
            "level": niveau, "sourceSegmentId": segment,
        })
    return chunks, grammaire, erreurs


# ---------------------------------------------------------------------------
# Enregistrement des résultats collés
# ---------------------------------------------------------------------------
def _maj_meta(slug, **champs):
    meta = bundles.lire_meta(slug) or {}
    meta.update(champs)
    bundles.ecrire_meta(slug, meta)
    return meta


def enregistrer_traduction(slug, texte_colle):
    """Fusionne une traduction JSON (un lot ou tout) dans segments.json.
    En cas d'erreur, rien n'est écrit. Renvoie (resume, erreurs)."""
    with VERROU:
        segments, erreur = initialiser_segments(slug)
        if erreur:
            return None, [erreur]
        objet, erreur = parser_json_colle(texte_colle)
        if erreur:
            return None, [erreur]
        traductions, erreurs = valider_traduction(objet, segments)
        if erreurs:
            return None, erreurs

        meta = bundles.lire_meta(slug) or {}
        source = langue_source(meta)
        cible = langue_cible(source)
        avant_en = empreinte(texte_complet(segments, "en"))
        for segment in segments:
            if segment["id"] in traductions:
                segment[cible] = traductions[segment["id"]]
        ecrire_segments(slug, segments)

        complete = traduction_complete(segments)
        if complete:
            # Fichier texte lisible, conservé pour compatibilité (v1)
            ecrire_atomique(chemin(slug, f"translation.{cible}.txt"),
                            texte_complet(segments, cible) + "\n")
        champs = {"translationValidated": complete}
        if empreinte(texte_complet(segments, "en")) != avant_en and complete:
            champs["englishTextRevision"] = meta.get("englishTextRevision", 0) + 1
        processing = meta.get("processing") or {}
        processing["translationProvider"] = "chatgpt-plus"
        champs["processing"] = processing
        _maj_meta(slug, **champs)
        restants = sum(1 for s in segments if not (s.get(cible) or "").strip())
        return {"segmentsTraduits": len(traductions),
                "segmentsRestants": restants, "complete": complete}, []


def enregistrer_pedagogie(slug, texte_colle):
    """Ajoute l'analyse du prochain lot dans pedagogy.json. Les chunks
    déjà présents (même expression) sont dédoublonnés."""
    with VERROU:
        segments = lire_segments(slug)
        if not traduction_complete(segments):
            return None, ["traduction incomplète : terminez d'abord les deux textes"]
        objet, erreur = parser_json_colle(texte_colle)
        if erreur:
            return None, [erreur]
        hash_en = empreinte(texte_complet(segments, "en"))
        tous = lots(segments, TAILLE_LOT_PEDAGOGIE)
        pedagogie = lire_pedagogie(slug)
        if not _pedagogie_a_jour(pedagogie, hash_en):
            pedagogie = {"englishTextHash": hash_en, "lotsAnalyses": 0,
                         "lotsTotal": len(tous), "chunks": [],
                         "grammarPoints": []}
        if pedagogie["lotsAnalyses"] >= len(tous):
            return None, ["analyse pédagogique déjà complète"]
        lot = tous[pedagogie["lotsAnalyses"]]
        chunks, grammaire, erreurs = valider_pedagogie(
            objet, {s["id"] for s in lot})
        if erreurs:
            return None, erreurs

        vus = {c["expression"].lower() for c in pedagogie["chunks"]}
        for chunk in chunks:
            if chunk["expression"].lower() not in vus:
                vus.add(chunk["expression"].lower())
                pedagogie["chunks"].append(chunk)
        titres = {g["title"].lower() for g in pedagogie["grammarPoints"]}
        for point in grammaire:
            if point["title"].lower() not in titres:
                titres.add(point["title"].lower())
                pedagogie["grammarPoints"].append(point)
        for i, chunk in enumerate(pedagogie["chunks"], 1):
            chunk["id"] = f"c{i:03d}"
        for i, point in enumerate(pedagogie["grammarPoints"], 1):
            point["id"] = f"g{i:03d}"
        pedagogie["lotsAnalyses"] += 1
        pedagogie["lotsTotal"] = len(tous)
        ecrire_json(chemin(slug, "pedagogy.json"), pedagogie)

        complete = pedagogie["lotsAnalyses"] >= len(tous)
        meta = bundles.lire_meta(slug) or {}
        processing = meta.get("processing") or {}
        processing["pedagogyProvider"] = "chatgpt-plus"
        _maj_meta(slug, pedagogyValidated=complete, processing=processing)
        return {"lot": pedagogie["lotsAnalyses"], "lots": len(tous),
                "chunks": len(pedagogie["chunks"]),
                "grammarPoints": len(pedagogie["grammarPoints"]),
                "complete": complete}, []


# ---------------------------------------------------------------------------
# Audio anglais publié
# ---------------------------------------------------------------------------
def nom_audio_original(slug):
    return f"{slug}.mp3"


def nom_audio_en_tts(slug):
    return f"{slug}.audio-en.mp3"


def fichier_audio_publication(slug, meta):
    """Nom du fichier audio ANGLAIS à publier (publishAudioFile).
    Renvoie (nom, erreur). Jamais l'audio original d'une source FR."""
    source = langue_source(meta)
    if source == "en":
        nom = nom_audio_original(slug)
    elif source == "fr":
        nom = nom_audio_en_tts(slug)
    else:
        return None, "langue source inconnue"
    if source == "fr" and nom == nom_audio_original(slug):
        return None, "refus : l'audio original français ne peut pas être publié"
    return nom, None


def audio_lisible(chemin_audio):
    """Fichier non vide commençant par un en-tête MP3 (ID3 ou synchro)."""
    try:
        if os.path.getsize(chemin_audio) < 1024:
            return False
        with open(chemin_audio, "rb") as f:
            debut = f.read(3)
    except OSError:
        return False
    return debut == b"ID3" or (len(debut) >= 2 and debut[0] == 0xFF
                               and debut[1] & 0xE0 == 0xE0)


def enregistrer_tts(slug, hash_en, voix):
    """À appeler après un TTS réussi : mémorise l'empreinte du texte
    anglais synthétisé (détection d'audio obsolète)."""
    meta = bundles.lire_meta(slug) or {}
    processing = meta.get("processing") or {}
    processing["ttsProvider"] = f"kokoro ({voix})"
    _maj_meta(slug, ttsEnglishTextHash=hash_en,
              ttsGeneratedFromEnglishRevision=meta.get("englishTextRevision", 0),
              ttsVoice=voix, processing=processing,
              tts={"status": "done", "finishedAt": bundles.maintenant(),
                   "lastError": None})


def marquer_tts(slug, statut, erreur=None):
    """Persiste l'état du TTS (generating | failed | interrupted) pour
    qu'il survive à un redémarrage de l'application."""
    meta = bundles.lire_meta(slug) or {}
    tts = dict(meta.get("tts") or {})
    tts.update({"status": statut, "lastError": erreur,
                "updatedAt": bundles.maintenant()})
    _maj_meta(slug, tts=tts)


# ---------------------------------------------------------------------------
# canPublish
# ---------------------------------------------------------------------------
def revision_contenu(segments, pedagogie, audio, segmentation_version=1,
                     timings=None):
    """contentRevision : empreinte de tout ce qui est publié pour la
    variante (textes EN/FR, pédagogie, segmentationVersion, audioRevision,
    timings publiés). Sert à l'idempotence et à savoir si la version
    publiée est à jour."""
    morceaux = [texte_complet(segments, "en"), texte_complet(segments, "fr"),
                json.dumps(pedagogie or {}, sort_keys=True, ensure_ascii=False),
                f"segmentation:{segmentation_version}",
                f"audio:{revision_audio(chemin_bundle(audio)) if audio else ''}",
                json.dumps(timings or [], sort_keys=True)]
    return empreinte("\x1e".join(morceaux))


def lire_timings_kokoro(slug, segments):
    """Timings de l'audio Kokoro s'ils correspondent au texte anglais
    actuel (même empreinte, mêmes segments) ; sinon None : ils sont
    obsolètes avec l'audio (v1.2 EA-03)."""
    donnees = lire_json(chemin(slug, "audio-en.timings.json"))
    if not donnees or not isinstance(donnees.get("timings"), list):
        return None
    if donnees.get("textHash") != empreinte(texte_complet(segments, "en")):
        return None
    if [t.get("id") for t in donnees["timings"]] != [s["id"] for s in segments]:
        return None
    return donnees["timings"]


def timings_publication(slug, segments, source, duree_s=None):
    """Timings publiés pour l'audio anglais : SRT pour une source anglaise,
    Kokoro pour une source française ; contrôlés (v1.2 § 6.1).
    Renvoie {"timings": [{startMs, endMs, wordsPerMinute}] | None,
    "timingSource", "timingStatus", "raisons", "wordsPerMinute"}."""
    infos = lire_infos_segments(slug)
    timings, origine = None, None
    if source == "en" and infos["timingSource"] == horodatage.TIMING_SRT:
        timings = [{"startMs": s.get("startMs"), "endMs": s.get("endMs")} for s in segments]
        origine = horodatage.TIMING_SRT
    elif source == "fr":
        kokoro = lire_timings_kokoro(slug, segments)
        if kokoro:
            timings = [{"startMs": t.get("startMs"), "endMs": t.get("endMs")} for t in kokoro]
            origine = horodatage.TIMING_KOKORO
    if not timings:
        return {"timings": None, "timingSource": None, "timingStatus": "absent",
                "raisons": [], "wordsPerMinute": None}
    controle = [{"id": s["id"], **t} for s, t in zip(segments, timings)]
    statut, raisons = horodatage.verifier_timings(
        controle, duree_s * 1000 if duree_s else None)
    if statut != "valid":
        # Publiable quand même, mais sans timings : pas d'écoute active
        return {"timings": None, "timingSource": origine, "timingStatus": statut,
                "raisons": raisons, "wordsPerMinute": None}
    for s, t in zip(segments, timings):
        t["wordsPerMinute"] = horodatage.mots_par_minute(s.get("en"), t["startMs"], t["endMs"])
    avec_en = [{**s, **t} for s, t in zip(segments, timings)]
    return {"timings": timings, "timingSource": origine, "timingStatus": "valid",
            "raisons": [], "wordsPerMinute": horodatage.debit_global(avec_en)}


_CACHE_DUREES = {}


def duree_audio_secondes(chemin_audio):
    """Durée d'un MP3 lue par ffmpeg (« Duration: hh:mm:ss.cc »), ou None.
    Mise en cache par (taille, date de modification) du fichier."""
    try:
        infos = os.stat(chemin_audio)
    except (OSError, TypeError):
        return None
    cle = (chemin_audio, infos.st_size, infos.st_mtime_ns)
    if cle not in _CACHE_DUREES:
        _CACHE_DUREES[cle] = _mesurer_duree(chemin_audio)
    return _CACHE_DUREES[cle]


def _mesurer_duree(chemin_audio):
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    try:
        sortie = subprocess.run([ffmpeg, "-hide_banner", "-i", chemin_audio],
                                capture_output=True, text=True, timeout=30).stderr
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", sortie)
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def libelle_duree(secondes):
    """« 45 s », « 12 min », « 1 h 05 » — affiché par la PWA."""
    secondes = round(secondes)
    if secondes < 60:
        return f"{secondes} s"
    minutes = round(secondes / 60)
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d}"


def chemin_bundle(nom):
    return os.path.join(bundles.DOSSIER_BUNDLES, nom)


def etat_publication(slug, import_en_cours=False):
    """Calcule l'état d'un bundle. `ok` vaut True seulement si tout est
    prêt (cahier des charges §8.1). Renvoie un dict sérialisable."""
    meta = bundles.lire_meta(slug)
    badges = {"audioEn": False, "texteEn": False, "texteFr": False,
              "pedagogie": False, "meta": False, "publication": False}
    raisons = []
    etat = {"ok": False, "statut": "invalide", "raisons": raisons,
            "badges": badges, "sourceLanguage": None,
            "publishAudioFile": None, "revision": None, "ancienFormat": False,
            "audioEnObsolete": False, "pedagogieObsolete": False}
    if not meta:
        raisons.append("meta.json manquant ou illisible")
        return etat

    source = langue_source(meta)
    etat["sourceLanguage"] = source
    badges["meta"] = bool(source and meta.get("id") and meta.get("title"))
    if not badges["meta"]:
        raisons.append("métadonnées invalides (langue source fr/en, id, titre)")

    segments = lire_segments(slug)
    if segments is None and (bundles.decrire_fichiers(slug)["translation"]
                             or meta.get("status") == "imported"):
        etat["ancienFormat"] = True
    if segments:
        badges["texteEn"] = all((s.get("en") or "").strip() for s in segments)
        badges["texteFr"] = all((s.get("fr") or "").strip() for s in segments)
    if not (badges["texteEn"] and badges["texteFr"]):
        if etat["ancienFormat"]:
            raisons.append("bundle ancien format : refaire la traduction "
                           "segmentée (les fichiers existants sont conservés)")
        elif source:
            manque = "anglaise" if source == "fr" else "française"
            raisons.append(f"traduction {manque} manquante ou incomplète")

    hash_en = empreinte(texte_complet(segments, "en")) if badges["texteEn"] else None
    pedagogie = lire_pedagogie(slug)
    if badges["texteEn"] and badges["texteFr"]:
        if not pedagogie:
            raisons.append("analyse pédagogique non faite")
        elif not _pedagogie_a_jour(pedagogie, hash_en):
            etat["pedagogieObsolete"] = True
            raisons.append("analyse pédagogique à revalider (texte anglais modifié)")
        elif pedagogie.get("lotsAnalyses", 0) < len(
                lots(segments, TAILLE_LOT_PEDAGOGIE)):
            raisons.append(f"analyse pédagogique incomplète "
                           f"(section {pedagogie.get('lotsAnalyses', 0)}/"
                           f"{len(lots(segments, TAILLE_LOT_PEDAGOGIE))})")
        else:
            badges["pedagogie"] = True

    audio, erreur = fichier_audio_publication(slug, meta)
    etat["publishAudioFile"] = audio
    if erreur:
        raisons.append(erreur)
    elif not os.path.exists(chemin_bundle(audio)):
        if source != "fr":
            raisons.append("audio anglais original manquant")
        elif (meta.get("tts") or {}).get("status") in ("failed", "interrupted"):
            raisons.append("génération de l'audio anglais interrompue : "
                           "relancez-la")
        else:
            raisons.append("audio anglais à générer (Kokoro)")
    elif not audio_lisible(chemin_bundle(audio)):
        raisons.append(f"audio {audio} vide ou illisible")
    elif source == "fr" and hash_en and meta.get("ttsEnglishTextHash") != hash_en:
        etat["audioEnObsolete"] = True
        raisons.append("audio anglais obsolète : régénérez-le (texte anglais modifié)")
    elif source == "fr" and not hash_en:
        raisons.append("audio anglais en attente du texte anglais validé")
    else:
        badges["audioEn"] = True

    if import_en_cours:
        raisons.append("import déjà en cours")
    if meta.get("status") == "failed" and meta.get("erreur"):
        raisons.append(f"erreur de préparation : {meta['erreur']}")

    etat["ok"] = not raisons
    publication = meta.get("publication") or {}
    infos_segments = lire_infos_segments(slug)
    etat["segmentationVersion"] = infos_segments["segmentationVersion"]
    etat["horodatage"] = {"timingSource": None, "timingStatus": "absent", "raisons": []}
    if etat["ok"] or badges["texteEn"]:
        audio_present = audio if audio and os.path.exists(chemin_bundle(audio)) else None
        horo = timings_publication(slug, segments, source,
                                   duree_audio_secondes(chemin_bundle(audio_present))
                                   if audio_present and badges["audioEn"] else None)
        etat["horodatage"] = {k: horo[k] for k in ("timingSource", "timingStatus", "raisons")}
        etat["revision"] = revision_contenu(segments, pedagogie, audio_present,
                                            infos_segments["segmentationVersion"],
                                            horo["timings"])
    badges["publication"] = bool(
        publication.get("status") == "published"
        and publication.get("contentRevision") == etat["revision"])

    # Statut de traitement (§5.3)
    if meta.get("status") == "failed" and meta.get("erreur"):
        etat["statut"] = "failed"
    elif import_en_cours:
        etat["statut"] = "publishing"
    elif not (badges["texteEn"] and badges["texteFr"]):
        etat["statut"] = "awaiting_translation"
    elif not badges["pedagogie"]:
        etat["statut"] = "awaiting_pedagogy"
    elif not badges["audioEn"]:
        etat["statut"] = "awaiting_tts" if source == "fr" else "awaiting_audio"
    elif badges["publication"]:
        etat["statut"] = "published"
    elif publication.get("status") == "failed":
        etat["statut"] = "publish_failed"
    else:
        etat["statut"] = "ready_to_publish"
    etat["publication"] = publication
    return etat


# ---------------------------------------------------------------------------
# Payload distant (POST /content — schéma existant, metadata enrichie)
# ---------------------------------------------------------------------------
def payload_distant(slug):
    """Construit le payload publié. Aucun chemin local, aucun secret,
    aucun audio français. Renvoie (payload, etat, erreur)."""
    etat = etat_publication(slug)
    if not etat["ok"]:
        return None, etat, "bundle non publiable : " + " ; ".join(etat["raisons"])
    meta = bundles.lire_meta(slug)
    segments = lire_segments(slug)
    pedagogie = lire_pedagogie(slug) or {}
    audio = etat["publishAudioFile"]
    audio_revision = revision_audio(chemin_bundle(audio))
    cle_r2 = cle_audio_r2(meta["id"], audio_revision)
    duree = duree_audio_secondes(chemin_bundle(audio))
    horo = timings_publication(slug, segments, etat["sourceLanguage"], duree)
    timings = horo["timings"] or [{"startMs": None, "endMs": None}] * len(segments)
    texte_en = texte_complet(segments, "en")
    texte_fr = texte_complet(segments, "fr")
    payload = {
        "profileId": "default",
        "id": meta["id"],
        "type": "podcast",
        "title": meta.get("title", meta["id"]),
        "level": meta.get("targetLevel", "B1"),
        "topic": meta.get("topic", "other"),
        "body": texte_en,
        "audioR2Key": cle_r2,
        "metadata": {
            # Champs historiques conservés pour l'app mobile actuelle
            "sourceType": meta.get("sourceType", "youtube"),
            "sourceUrl": meta.get("sourceUrl", ""),
            "audioLanguage": "en",
            "transcriptLanguage": etat["sourceLanguage"],
            "transcriptText": texte_complet(segments, etat["sourceLanguage"]),
            # Format bilingue v2
            "schemaVersion": 2,
            "sourceLanguage": etat["sourceLanguage"],
            "learningLanguage": "en",
            "targetLocale": "en-GB",
            "audioOrigin": "kokoro_tts" if etat["sourceLanguage"] == "fr" else "original",
            "contentRevision": etat["revision"],
            # Versions (AUDIT_LOT0.md § 8)
            "variantId": id_variante(meta["id"]),
            "variantKind": VARIANTE_FIDELE,
            "sourceRevision": revision_source_bundle(slug, meta),
            "segmentationVersion": etat["segmentationVersion"],
            "audioRevision": audio_revision,
            "timingSource": horo["timingSource"],
            "timingStatus": horo["timingStatus"],
            "wordsPerMinute": horo["wordsPerMinute"],
            "textEn": texte_en,
            "textFr": texte_fr,
            "segments": [_segment_publie(s, t) for s, t in zip(segments, timings)],
            "chunks": pedagogie.get("chunks", []),
            "grammarPoints": pedagogie.get("grammarPoints", []),
        },
    }
    if duree:
        payload["metadata"]["durationSeconds"] = round(duree)
        payload["metadata"]["durationLabel"] = libelle_duree(duree)
    return payload, etat, None


def _segment_publie(segment, timing):
    publie = {"id": segment["id"], "en": segment["en"], "fr": segment["fr"],
              "startMs": timing.get("startMs"), "endMs": timing.get("endMs")}
    if timing.get("wordsPerMinute") is not None:
        publie["wordsPerMinute"] = timing["wordsPerMinute"]
    return publie


def marquer_publication(slug, ok, revision=None, erreur=None, cle_audio=None):
    meta = bundles.lire_meta(slug) or {}
    publication = dict(meta.get("publication") or {})
    instant = bundles.maintenant()
    if ok:
        publication.update({"status": "published", "remoteId": meta.get("id"),
                            "remoteVersion": revision, "contentRevision": revision,
                            "audioR2Key": cle_audio,
                            "publishedAt": instant, "lastError": None})
    else:
        publication.update({"status": "failed", "lastError": erreur,
                            "failedAt": instant,
                            "failedRevision": revision})
    _maj_meta(slug, publication=publication)


def publier(slug, signal=None):
    """Publie le bundle : upload de l'audio ANGLAIS vers R2 puis
    POST /content (upsert sur l'id → un retry ne crée pas de doublon).
    N'est marqué publié qu'après succès des deux étapes.
    Renvoie (ok, message)."""
    payload, etat, erreur = payload_distant(slug)
    if erreur:
        return False, erreur
    config, erreur = bundles.charger_config_import()
    if erreur:
        return False, erreur
    url = config["workerUrl"]
    payload["profileId"] = config["profileId"]
    # Persisté : un redémarrage pendant l'envoi est détecté (reprendre)
    meta = bundles.lire_meta(slug) or {}
    publication = dict(meta.get("publication") or {})
    publication.update({"status": "publishing",
                        "startedAt": bundles.maintenant()})
    _maj_meta(slug, publication=publication)
    autorisation = f"Bearer {config['apiSecret']}"

    chemin_audio = chemin_bundle(etat["publishAudioFile"])
    try:
        with open(chemin_audio, "rb") as f:
            donnees_audio = f.read()
    except OSError as e:
        return False, f"audio illisible : {e}"
    try:
        if signal:
            signal(f"Publication : upload audio EN "
                   f"({len(donnees_audio) / 1048576:.1f} Mo)…")
        # Clé immuable + contentId : le Worker l'enregistre en `pending`
        # puis l'active (et retire l'ancienne) au POST /content.
        bundles._requete_worker(
            f"{url}/content/audio?key="
            + bundles.urllib.parse.quote(payload["audioR2Key"], safe="")
            + "&contentId=" + bundles.urllib.parse.quote(payload["id"], safe=""),
            donnees=donnees_audio,
            entetes={"Authorization": autorisation,
                     "Content-Type": "audio/mpeg"},
            methode="POST", timeout=600)
        if signal:
            signal("Publication : envoi du contenu…")
        bundles._requete_worker(
            f"{url}/content",
            donnees=json.dumps(payload).encode("utf-8"),
            entetes={"Authorization": autorisation,
                     "Content-Type": "application/json"},
            methode="POST")
    except RuntimeError as e:
        marquer_publication(slug, False, revision=etat["revision"],
                            erreur=str(e))
        return False, f"échec de publication : {e}"

    marquer_publication(slug, True, revision=etat["revision"],
                        cle_audio=payload["audioR2Key"])
    origine = "Kokoro" if etat["sourceLanguage"] == "fr" else "original"
    return True, f"publié avec l'audio anglais ({origine})"


# ---------------------------------------------------------------------------
# Auto-publication et reprise après redémarrage
# ---------------------------------------------------------------------------
def doit_auto_publier(slug, import_en_cours=False):
    """True si le bundle doit partir tout seul : option autoPublish active,
    tous les prérequis réunis et version courante pas encore publiée.
    Un échec de publication n'est pas relancé automatiquement (le retry
    reste manuel). Renvoie (bool, raison)."""
    meta = bundles.lire_meta(slug) or {}
    if not meta.get("autoPublish"):
        return False, "auto-publication désactivée"
    etat = etat_publication(slug, import_en_cours=import_en_cours)
    if not etat["ok"]:
        return False, " ; ".join(etat["raisons"])
    if etat["badges"]["publication"]:
        return False, "version déjà publiée"
    publication = meta.get("publication") or {}
    if (publication.get("status") == "failed"
            and publication.get("failedRevision") == etat["revision"]):
        return False, "dernier envoi en échec : réessai manuel"
    return True, None


FICHIERS_TEMPORAIRES = (".tts.wav", ".tts-input.en.txt", ".tts-input.en.json",
                        ".tts-timings.json", ".audio-en.tmp.mp3")


def reprendre_apres_redemarrage(slug):
    """Remet un bundle dans un état cohérent après un arrêt brutal :
    publication ou TTS « en cours » → interrompus (action Réessayer),
    fichiers temporaires supprimés. Renvoie la liste des actions."""
    actions = []
    for suffixe in FICHIERS_TEMPORAIRES:
        temporaire = chemin_bundle(slug + suffixe)
        if os.path.exists(temporaire):
            os.remove(temporaire)
            actions.append(f"supprimé {slug}{suffixe}")
    meta = bundles.lire_meta(slug)
    if not meta:
        return actions
    if (meta.get("publication") or {}).get("status") == "publishing":
        marquer_publication(slug, False, erreur="publication interrompue par "
                                                "un redémarrage : réessayez")
        actions.append("publication interrompue")
    if (meta.get("tts") or {}).get("status") == "generating":
        marquer_tts(slug, "interrupted",
                    "génération interrompue par un redémarrage")
        actions.append("TTS interrompu")
    return actions
