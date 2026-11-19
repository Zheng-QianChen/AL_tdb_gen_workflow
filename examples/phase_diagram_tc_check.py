"""Read global-equilibrium values from a Thermo-Calc check log."""
import re


def parse_checks(raw, rows, output, imported, completed):
    """Accept either observed local or global convergence message, never exit 0 alone."""
    blocks = re.split(r"POLY(?:_[0-9]+)?:\s*REINITIATE_MODULE", raw, flags=re.I)[1:]
    if len(blocks) != len(rows):
        blocks = re.split(r"POLY(?:_[0-9]+)?:\s*SET_CONDITION", raw, flags=re.I)[1:]
    checks = []
    for i, row in enumerate(rows):
        block = blocks[i] if i < len(blocks) else ""
        values = re.findall(r"\bGM\s*=\s*([-+0-9.Ee]+)", block)
        energy = float(values[-1]) if values else None
        calculated = bool(re.search(r"\b\d+\s+ITS,\s+CPU TIME USED|Calculated solution in\s+[0-9.]+\s+s using\s+\d+\s+iterations", block, re.I))
        calculated = calculated and not bool(re.search(r"\bERROR\b|NO SUCH COMMAND|NOT CONVERGED", block, re.I))
        error = None if energy is None else energy-row["G_J_mol_atoms"]
        checks.append({"point_id": row["point_id"], "T_K": row["T_K"], "composition": row["composition"],
                       "project_G": row["G_J_mol_atoms"], "thermocalc_G": energy, "delta_G": error,
                       "converged_marker": calculated, "result_file": str(output / f"point_{i:03}.txt"),
                       "energy_agrees": bool(imported and completed and (output / f"point_{i:03}.txt").is_file()
                                             and calculated and error is not None and abs(error) < .1)})
    return checks
