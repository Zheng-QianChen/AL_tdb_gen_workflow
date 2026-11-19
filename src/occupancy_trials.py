"""Compare site-occupancy restrictions against the original endmember energy hull."""
import hashlib
from io import BytesIO
from math import prod
from uuid import uuid4

import numpy as np
import pandas as pd
from scipy.spatial import ConvexHull

from src.generate import get_model_site_elements
from src.storage import atomic_json


def lower_envelope(compositions, energy, probes):
    """Minimum mixture energy at each composition; NaN outside the composition domain."""
    center = compositions.mean(axis=0)
    _, singular, basis = np.linalg.svd(compositions - center, full_matrices=False)
    axes = basis[singular > 1e-10]
    points = (compositions - center) @ axes.T
    coords = (probes - center) @ axes.T
    covered = np.max(abs(probes - center - coords @ axes), axis=1) < 1e-8
    if not len(axes):
        return np.where(covered, min(energy), np.nan)
    if len(axes) == 1:
        covered &= (coords[:, 0] >= points.min() - 1e-9) & (coords[:, 0] <= points.max() + 1e-9)
    else:
        faces = ConvexHull(points).equations
        for face in faces:
            covered &= coords @ face[:-1] + face[-1] <= 1e-9
    # An upper apex at the centroid makes even an affine energy surface full rank.
    apex = [*points.mean(axis=0), energy.max() + max(1., np.ptp(energy))]
    hull = ConvexHull(np.vstack([np.column_stack([points, energy]), apex]))
    values = np.full(len(probes), -np.inf)
    for face in hull.equations:
        if face[-2] < -1e-12:
            values = np.maximum(values, -(coords @ face[:-2] + face[-1]) / face[-2])
    if not np.all(np.isfinite(values[covered])):
        raise ValueError("Could not resolve the lower energy surface")
    return np.where(covered, values, np.nan)


def compare_occupancies(analyzer, model, choices):
    source = analyzer.vasp_ml_data_path.read_bytes()
    data = pd.read_csv(BytesIO(source))
    labels = model[1].split(':')
    groups = list(dict.fromkeys(labels))
    allowed = get_model_site_elements(model, analyzer.site_elements)
    if len(labels) != len(analyzer.site_weight) or any(len(choices[key]) != len(groups)
            for key in ('fix', 'need_del', 'analys')):
        raise ValueError('Element groups do not match this model')
    keep = []
    for index, site in enumerate(allowed):
        fixed, removed, optional = (choices[k][index] for k in ('fix','need_del','analys'))
        all_choices = fixed + removed + optional
        if sorted(all_choices) != sorted(site) or not (fixed or optional):
            raise ValueError('Assign each allowed constituent once and retain at least one per site')
        keep.append([e for e in site if e not in removed])

    members = data.endmember.str.split(':', expand=True)
    if members.shape[1] != len(labels) or data.endmember.duplicated().any():
        raise ValueError('Expected unique original endmembers matching the site model')
    composition = data[analyzer.elements_list].to_numpy(dtype=float)
    energies = data.Energy.to_numpy(dtype=float)
    if (not np.isfinite(energies).all() or not np.isfinite(composition).all()
            or (composition < -1e-8).any() or not np.allclose(composition.sum(axis=1), 1)):
        raise ValueError('Expected finite energies and normalized atomic fractions')
    probes = np.unique(composition, axis=0)
    protected = choices.get('protected', [])
    for item in protected:
        fractions = item['composition']
        if (not fractions or not set(fractions) <= set(analyzer.elements_list)
                or any(not np.isfinite(x) or x < 0 for x in fractions.values())
                or abs(sum(fractions.values()) - 1) > 1e-8):
            raise ValueError('Protected compositions must use the selected elements and sum to one')
    extra = [[item['composition'].get(e, 0.) for e in analyzer.elements_list] for item in protected]
    all_probes = np.vstack([probes, extra]) if extra else probes
    reference_mask = None
    reference = None
    candidates = []
    seen = set()

    def evaluate(sites, label):
        nonlocal reference, reference_mask
        key = tuple(tuple(sorted(site)) for site in sites)
        if key in seen:
            return
        seen.add(key)
        mask = np.ones(len(data), dtype=bool)
        for j, group in enumerate(labels):
            mask &= members[j].isin(sites[groups.index(group)]) & (members[j] == members[labels.index(group)])
        count = int(mask.sum())
        candidate = dict(label=label, sites=sites, endmembers=count,
                         missing=prod(map(len, sites)) - count)
        candidates.append(candidate)
        if not count and reference is None:
            raise ValueError('No original endmember energies for this model')
        values = (lower_envelope(composition[mask], energies[mask], all_probes)
                  if count else np.full(len(all_probes), np.nan))
        if reference is None:
            reference, reference_mask = values.copy(), mask.copy()
        candidate['removed_sources'] = {
            str(k): int(v) for k,v in data.loc[reference_mask & ~mask, 'from'].value_counts().items()}
        candidate['protected_points'] = [
            {**item, 'baseline_covered':bool(np.isfinite(reference[j])),
             'candidate_covered':bool(np.isfinite(values[j]))}
            for j,item in enumerate(protected, start=len(probes))]
        original = reference[:len(probes)]
        values = values[:len(probes)]
        lost = np.isfinite(original) & ~np.isfinite(values)
        candidate['lost_binary_edges'] = sorted({'–'.join(e for e,x in zip(analyzer.elements_list,c) if x>1e-8)
                                                for c in probes[lost] if sum(c>1e-8)==2})
        comparable = np.isfinite(values) & np.isfinite(original)
        delta = np.maximum(0., values[comparable] - original[comparable])
        candidate.update(covered=int(comparable.sum()),
                         lost=int(lost.sum()),
                         max_rise=float(delta.max()) if len(delta) else None,
                         rms_rise=float(np.sqrt(np.mean(delta**2))) if len(delta) else None)

    evaluate(allowed, '原模型')
    if reference is None:
        raise ValueError('No original endmember energies for this model')
    evaluate(keep, '按指定范围保留')
    for i, optional in enumerate(choices['analys']):
        for element in optional:
            if len(keep[i]) > 1:
                trial = [list(s) for s in keep]
                trial[i].remove(element)
                evaluate(trial, f'{groups[i]} 位去掉 {element}')
    report = dict(id=uuid4().hex, model=model, groups=groups,
                  ratios=analyzer.sum_elements([*model, ':'.join(map(str, analyzer.site_weight))], groups),
                  source_sha256=hashlib.sha256(source).hexdigest(), choices=choices,
                  compositions=len(probes), candidates=candidates)
    atomic_json(analyzer.working_path / 'occupancy_trials' / report['id'] / 'comparison.json', report)
    return report
