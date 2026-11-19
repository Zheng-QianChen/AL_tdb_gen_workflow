"""Read a homogeneous phase point from OpenCalphad output."""
import re

NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?"


def parse_output(output, phase, composition):
    text = output.replace("\r", "")
    def number(value):
        return float(value.upper().replace("D", "E"))
    values = re.findall(r"\bGM=\s*("+NUMBER+r")", text)
    phase_rows = re.findall(r"^([A-Z0-9_#]+)\.{2,}\s+([EFSDB])\s+("+NUMBER+r")", text, re.M)
    active = [(name, number(amount)) for name, status, amount in phase_rows if number(amount) > 1e-8]
    x = {c: number(m[-1]) for c in composition if (m := re.findall(
        r"\bX\("+re.escape(phase)+","+c+r"\)=\s*("+NUMBER+r")", text))}
    comp_error = max(abs(x[c]-composition[c]) for c in composition) if len(x) == len(composition) else None
    site_rows = re.findall(r"Sublattice\s+(\d+)\s+with\s+(\d+)\s+constituents[^\n]*sites\s*\n([^\n]+)", text)
    sites, site_errors, site_counts_valid = {}, [], True
    for index, count, line in site_rows:
        constituents = re.findall(r"\b([A-Z][A-Z0-9_]*)\s+("+NUMBER+r")", line)
        site_counts_valid &= len(constituents) == int(count)
        site_errors.append(abs(sum(number(y) for _, y in constituents)-1))
        sites.update({f"Y_{int(index)-1}_{c}": number(y) for c, y in constituents})
    site_error = max(site_errors) if site_errors else None
    site_valid = bool(sites and site_counts_valid and site_error < 1e-5
                      and min(sites.values()) >= 0 and max(sites.values()) <= 1)
    calculated = "Equilibrium result:" in text and "does not represent a calculated equilibrium" not in text
    comparable = bool(calculated and values and len(active) == 1 and active[0][0] == phase
                      and abs(active[0][1]-1) < 1e-7 and comp_error is not None and comp_error < 1e-7 and site_valid)
    return {"calculated": calculated, "comparable": comparable,
            "G": number(values[-1]) if values else None, "active_phases": active,
            "X": x, "max_composition_error": comp_error,
            "site_fractions_printed_precision": sites, "max_printed_site_sum_error": site_error,
            "site_count": len(site_rows),
            "reader_parameter_counts": re.findall(r"Out of\s+(\d+) model parameters\s+(\d+) have been entered", text),
            "diagnostic_lines": [line.strip() for line in text.splitlines()
                if any(word in line.lower() for word in ("warning", "error", "rejected", "missing"))][:25]}
