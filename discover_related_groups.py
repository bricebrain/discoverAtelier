"""Couverture déterministe des liens par des groupes dont chaque paire est validée."""
from itertools import combinations


def coherent_groups(keys, links, verifier=lambda: None):
    adjacent = {key: set() for key in keys}
    scores = {}
    for index, (a, b, score) in enumerate(links):
        if index % 64 == 0:
            verifier()
        if a == b:
            continue
        pair = tuple(sorted((a, b)))
        scores[pair] = max(score, scores.get(pair, score))
        adjacent[a].add(b)
        adjacent[b].add(a)

    uncovered = set(scores)
    groups, checks = [], 0
    for index, ((a, b), _) in enumerate(sorted(scores.items(), key=lambda edge: (-edge[1], edge[0]))):
        if index % 64 == 0:
            verifier()
        if (a, b) not in uncovered:
            continue
        members = {a, b}
        candidates = adjacent[a] & adjacent[b]
        def affinity(key):
            weights = [scores[tuple(sorted((key, seed)))] for seed in (a, b)]
            return (-min(weights), -sum(weights), key)
        for member in sorted(candidates, key=affinity):
            checks += 1
            if checks % 64 == 0:
                verifier()
            # Une paire absente, refusée ou hors fenêtre interdit l'ajout au groupe.
            if members.issubset(adjacent[member]):
                members.add(member)
        group = sorted(members)
        groups.append(group)
        for pair in combinations(group, 2):
            checks += 1
            if checks % 64 == 0:
                verifier()
            uncovered.discard(pair)
    verifier()
    return sorted(groups)
