"""Synthetic test models. These are not assessed material databases."""
import itertools

REFERENCE = """$ SYNTHETIC VALIDATION ONLY - NOT AN ASSESSED DATABASE
ELEMENT AL FCC_A1 26.9815 0 0 !
ELEMENT NI FCC_A1 58.6934 0 0 !
ELEMENT MO BCC_A2 95.95 0 0 !
FUNCTION GHSERAL 298.15 1000-8*T; 6000 N !
FUNCTION GHSERNI 298.15 3000-12*T; 6000 N !
FUNCTION GHSERMO 298.15 2000-10*T; 6000 N !
TYPE_DEFINITION % SEQ * !
"""


def cef_tdb(n, kind="ideal", ratios=None, groups=None, phase="TEST", ordering_keyword="DISORDERED_PART"):
    ratios = ratios or [1]*n
    groups = groups or [["AL", "NI"] for _ in range(n)]
    total = sum(ratios)
    text = REFERENCE
    partitioned = kind == "partitioned"
    if partitioned:
        text += "PHASE DIS % 1 1 !\nCONSTITUENT DIS :AL,NI: !\n"
        for element in ("AL", "NI"):
            text += f"PARAMETER G(DIS,{element};0) 298.15 GHSER{element}#; 6000 N !\n"
        text += "PARAMETER G(DIS,AL,NI;0) 298.15 3000-0.5*T; 6000 N !\n"
        text += f"TYPE_DEFINITION & GES AMEND_PHASE_DESCRIPTION {phase} {ordering_keyword} DIS !\n"
    text += f"PHASE {phase} %{'&' if partitioned else ''} {n} " + " ".join(map(str, ratios)) + " !\n"
    text += f"CONSTITUENT {phase} :" + ":".join(",".join(group) for group in groups) + ": !\n"
    # Equivalent sites with unlike-pair chemical preference. A complete graph
    # preserves permutation symmetry, including for odd numbers of sites.
    # Scale the pair energy so the disordering temperature is comparable for n.
    pairs = list(itertools.combinations(range(n), 2))
    for member in itertools.product(*groups):
        energy = 0
        if kind in {"ordered", "partitioned"}:
            energy = -12000 * (n-1) * total * sum(member[a] != member[b] for a, b in pairs) / len(pairs)
        elif kind == "nonideal":
            energy = total * sum((i+1)*250*(element == "NI") for i, element in enumerate(member))
        reference = "+".join(f"{ratio}*GHSER{element}#" for ratio, element in zip(ratios, member))
        text += f"PARAMETER G({phase},{':'.join(member)};0) 298.15 {reference}{energy:+.15g}; 6000 N !\n"
    if kind == "nonideal":
        for i, group in enumerate(groups):
            if not {"AL", "NI"} <= set(group):
                continue
            # Explicit spectator endmembers keep this fixture independent of
            # wildcard-parameter conventions in different parsers.
            spectators = [(["AL,NI"] if j == i else g) for j, g in enumerate(groups)]
            for member in itertools.product(*spectators):
                text += f"PARAMETER G({phase},{':'.join(member)};0) 298.15 {ratios[i]*(2000+300*i)}-0.1*T; 6000 N !\n"
    return text


def cases():
    results = []
    for n in (3, 4, 5):
        for kind, ratios in (("ideal", [1]*n), ("weighted", list(range(1, n+1))),
                             ("nonideal", list(range(1, n+1)))):
            request = {"mode": "gx", "temperatures": [600, 1600], "points": 5, "starts": 24,
                       "composition_start": {"AL": 1}, "composition_end": {"NI": 1}}
            results.append({"name": f"{n}sl_{kind}", "n": n, "kind": kind,
                            "tdb": cef_tdb(n, "ideal" if kind == "weighted" else kind, ratios), "request": request})
        for kind in ("ordered", "partitioned"):
            fraction = (n-n//2)/n
            request = {"mode": "gt", "temperatures": [400, 800, 1200, 1600, 2200, 3200],
                       "composition": {"AL": 1-fraction, "NI": fraction}, "starts": 32}
            results.append({"name": f"{n}sl_{kind}", "n": n, "kind": kind,
                            # Pandat requires matching total site ratios for
                            # linked phases; normalize the ordered formula unit.
                            "tdb": cef_tdb(n, kind, ratios=[1/n]*n if kind == "partitioned" else None,
                                           ordering_keyword="DISORDER_PART"), "request": request})
        groups = [["AL", "NI"] for _ in range(n-1)] + [["NI"]]
        request = {"mode": "gx", "temperatures": [700, 1700], "points": 3, "starts": 24,
                   "composition_start": {"AL": (n-1)/n, "NI": 1/n}, "composition_end": {"NI": 1}}
        results.append({"name": f"{n}sl_restricted", "n": n, "kind": "restricted",
                        "tdb": cef_tdb(n, "nonideal", groups=groups), "request": request})
    results.append({"name": "3sl_ternary", "n": 3, "kind": "ternary",
                    "tdb": cef_tdb(3, "nonideal", groups=[["AL", "NI", "MO"]]*3),
                    "request": {"mode": "gx", "temperatures": [700, 1700], "points": 3, "starts": 32,
                                "composition_start": {"AL": .5, "MO": .5},
                                "composition_end": {"NI": .5, "MO": .5}}})
    return results
