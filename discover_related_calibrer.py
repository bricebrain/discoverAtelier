"""Exporter un échantillon de paires locales ou évaluer un CSV annoté, sans réseau."""
import argparse
import csv
import random
from collections import defaultdict

from discover_related_store import Store
from discover_related_similarity import cosine, within

FIELDS = ['type_a', 'id_a', 'titre_a', 'editeur_a', 'date_a', 'type_b', 'id_b', 'titre_b', 'editeur_b', 'date_b', 'langues', 'score', 'meme_evenement']


def export(root, path, model='bge-m3', per_bin=20):
    from discover_related_similarity import fingerprint, text
    store = Store(root)
    try:
        rows = [(i, store.vector(fingerprint(model, text(i)))) for _, i, _ in store.all()]
        bins = defaultdict(list)
        rng = random.Random(24)
        counts = defaultdict(int)
        for pos, (a, va) in enumerate(rows):
            for b, vb in rows[pos+1:]:
                if va is None or vb is None or not within(a, b, 72):
                    continue
                score = cosine(va, vb)
                if score < .4:
                    continue
                lang = 'same' if a.get('language') == b.get('language') else 'cross'
                key = (lang, int(score*20))
                entry = [a['type'], a['id'], a.get('title'), a.get('publisher'), a.get('publishedAt'),
                         b['type'], b['id'], b.get('title'), b.get('publisher'), b.get('publishedAt'), lang, score, '']
                counts[key] += 1
                if len(bins[key]) < per_bin:
                    bins[key].append(entry)
                else:
                    index = rng.randrange(counts[key])
                    if index < per_bin:
                        bins[key][index] = entry
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(FIELDS)
            for key in sorted(bins):
                writer.writerows(bins[key])
    finally:
        store.close()


def evaluate(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        rows = [r for r in csv.DictReader(f) if r['meme_evenement'].strip().lower() in ('0', '1', 'oui', 'non')]
    if not rows:
        print('Aucune paire annotée : aucun seuil proposé.')
        return
    for lang in ('same', 'cross'):
        subset = [r for r in rows if r['langues'] == lang]
        if not subset:
            continue
        best = None
        for n in range(50, 86, 2):
            threshold = n/100
            tp = fp = fn = 0
            for r in subset:
                actual = r['meme_evenement'].strip().lower() in ('1', 'oui')
                predicted = float(r['score']) >= threshold
                tp += actual and predicted
                fp += not actual and predicted
                fn += actual and not predicted
            precision = tp/(tp+fp) if tp+fp else 0
            recall = tp/(tp+fn) if tp+fn else 0
            print(f'{lang} seuil={threshold:.2f} précision paires={precision:.3f} rappel paires={recall:.3f}')
            if precision >= .9 and (best is None or recall > best[1]):
                best = (threshold, recall)
        print(f'{lang} seuil proposé (précision ≥ 90 %) : {best[0] if best else "échantillon insuffisant"}')
    # Les composantes peuvent créer des relations transitives : mesurer aussi ces relations.
    for threshold in (.60, .64, .68, .72, .76, .80):
        parent = {}
        def root(k):
            parent.setdefault(k, k)
            while parent[k] != k:
                k = parent[k]
            return k
        for r in rows:
            a, b = r['type_a']+':'+r['id_a'], r['type_b']+':'+r['id_b']
            if float(r['score']) >= threshold:
                parent[root(b)] = root(a)
        tp = fp = fn = 0
        for r in rows:
            predicted = root(r['type_a']+':'+r['id_a']) == root(r['type_b']+':'+r['id_b'])
            actual = r['meme_evenement'].strip().lower() in ('1', 'oui')
            tp += predicted and actual
            fp += predicted and not actual
            fn += not predicted and actual
        print(f'groupes seuil={threshold:.2f} précision={tp/(tp+fp) if tp+fp else 0:.3f} rappel={tp/(tp+fn) if tp+fn else 0:.3f}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['export', 'evaluate'])
    parser.add_argument('csv')
    parser.add_argument('--root', default='.discover-queue')
    parser.add_argument('--model', default='bge-m3')
    args = parser.parse_args()
    export(args.root, args.csv, args.model) if args.action == 'export' else evaluate(args.csv)
