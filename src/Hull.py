"""Lower convex envelopes. Energies and returned distances use the same units."""
import numpy as np
from scipy.spatial import ConvexHull


def generate_lower_hull_hyperplanes(hull, points=None):
    """Use Qhull's outward normals; downward-facing facets form the lower hull."""
    equations = np.asarray(hull.equations, dtype=float)
    lower = equations[equations[:, -2] < -1e-12]
    if not len(lower):
        raise ValueError("The hull has no lower facets")
    normals, offsets = lower[:, :-1], lower[:, -1]
    return normals, offsets, np.linalg.norm(normals, axis=1)


def batch_min_distance(points, w, b, block_size=1024):
    """Signed vertical energy difference to the lower envelope, including zero.

    Query compositions must lie in the hull's composition domain. Negative values
    mean the query is below the reference hull, not an unsigned geometric distance.
    """
    points = np.asarray(points, dtype=float)
    w = np.asarray(w, dtype=float)
    b = np.asarray(b, dtype=float)
    if points.ndim != 2 or w.ndim != 2 or w.shape[1] != points.shape[1]:
        raise ValueError("Points and facet normals have incompatible dimensions")
    if b.shape != (len(w),) or not all(np.isfinite(a).all() for a in (points, w, b)):
        raise ValueError("Hull inputs must be finite and have matching dimensions")
    lower = w[:, -1] < -1e-12
    w, b = w[lower], b[lower]
    if not len(w):
        raise ValueError("The hull has no lower facets")
    result = np.empty(len(points))
    for start in range(0, len(points), block_size):
        block = points[start:start + block_size]
        planes = -(block[:, :-1] @ w[:, :-1].T + b) / w[:, -1]
        result[start:start + len(block)] = block[:, -1] - planes.max(axis=1)
    result[np.abs(result) <= 1e-8] = 0.0
    return result


def energy_above_hull(points):
    """Energy above the sample envelope, including rank-deficient compositions.

    Project only the composition coordinates onto their affine span. Artificial
    upper points make flat-energy datasets full-dimensional without perturbing
    the lower hull or adding unobserved zero-energy reference phases.
    """
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or not len(points) or not np.isfinite(points).all():
        raise ValueError("Expected a non-empty finite point matrix")
    energy = points[:, -1]
    compositions = points[:, :-1]
    centered = compositions - compositions.mean(axis=0)
    if centered.shape[1] == 0:
        return energy - energy.min()
    _, singular, axes = np.linalg.svd(centered, full_matrices=False)
    tolerance = max(centered.shape) * np.finfo(float).eps * (singular[0] if len(singular) else 1)
    rank = int(np.sum(singular > tolerance))
    if rank == 0:
        return energy - energy.min()
    coords = centered @ axes[:rank].T
    query = np.column_stack((coords, energy))
    ceiling = energy.max() + max(float(np.ptp(energy)), 1.0)
    caps = np.column_stack((coords, np.full(len(coords), ceiling)))
    hull = ConvexHull(np.unique(np.vstack((query, caps)), axis=0))
    normals, offsets, _ = generate_lower_hull_hyperplanes(hull)
    distances = batch_min_distance(query, normals, offsets)
    if np.any(distances < -1e-7):
        raise ValueError("Numerically inconsistent lower hull")
    return np.maximum(distances, 0.0)
