"""Shared energy and composition conventions."""
import numpy as np

EV_PER_ATOM_TO_KJ_PER_MOL = 96.48533212331002


def formation_energy(total_energy_ev, atom_count, reference_ev_per_atom):
    if atom_count <= 0:
        raise ValueError("Atom count must be positive")
    total = np.asarray(total_energy_ev, dtype=float)
    reference = np.asarray(reference_ev_per_atom, dtype=float)
    if not np.isfinite(total).all() or not np.isfinite(reference).all():
        raise ValueError("Energies must be finite")
    return (total / atom_count - reference) * EV_PER_ATOM_TO_KJ_PER_MOL


def site_fractions(counts):
    counts = np.asarray(counts, dtype=float)
    if counts.ndim != 1 or not len(counts) or not np.isfinite(counts).all() or np.any(counts <= 0):
        raise ValueError("Sublattice site counts must be finite and positive")
    return counts / counts.sum()
