"""Portable exports and scientific figures; failed points are never interpolated."""
import csv
import html
import io
import json

import numpy as np

from src.gibbs import _plot_lock
from src.storage import atomic_json, atomic_write


def csv_file(path, rows, fallback):
    fields = list(dict.fromkeys(key for row in rows for key in row)) or fallback
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    atomic_write(path, buffer.getvalue())


def ternary_xy(composition, components):
    return composition[components[1]] + .5*composition[components[2]], np.sqrt(3)/2*composition[components[2]]


def plot_diagram(result, folder):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.colors import ListedColormap, BoundaryNorm
    from matplotlib.patches import Patch
    from matplotlib import colormaps
    mode, req = result["mode"], result["request"]
    rows = result["rows"]
    labels = result["summary"]["assemblages"]
    colors = {label: colormaps["tab20"](i % 20) for i, label in enumerate(labels)}
    with _plot_lock:
        fig = Figure(figsize=(10.8, 6.6), constrained_layout=True)
        FigureCanvasAgg(fig)
        ax = fig.subplots()
        if mode in {"binary", "isopleth"}:
            xs = sorted({r["path_coordinate"] for r in rows})
            ts = req["temperatures"]
            z = np.array([labels.index(r["assemblage"]) if r["status"] == "accepted" else np.nan for r in rows]).reshape(len(ts), len(xs))
            cmap = ListedColormap([colors[label] for label in labels] or ["#ddd"])
            ax.pcolormesh(xs, ts, np.ma.masked_invalid(z), cmap=cmap,
                          norm=BoundaryNorm(np.arange(max(1, len(labels))+1)-.5, max(1, len(labels))), shading="nearest", alpha=.5, rasterized=True)
            for row in rows:
                if row["status"] == "failed":
                    ax.plot(row["path_coordinate"], row["T_K"], "rx", markersize=4)
            xc = req["x_component"] or req["components"][-1]
            ax.set_xlabel(f"X({xc}) (atomic fraction)" if mode == "binary" else "Bulk composition path fraction")
            ax.set_ylabel("Temperature (K)")
            ax.set_xlim(xs[0], xs[-1]); ax.set_ylim(ts[0], ts[-1])
        elif mode == "ternary":
            for label in labels:
                xy = np.array([ternary_xy(r["composition"], result["components"]) for r in rows if r["assemblage"] == label])
                ax.scatter(xy[:, 0], xy[:, 1], c=[colors[label]], s=max(5, 1200/req["points"]), alpha=.65)
            for row in rows:
                if row["status"] == "failed":
                    ax.plot(*ternary_xy(row["composition"], result["components"]), "rx", markersize=4)
            ax.plot([0, 1, .5, 0], [0, 0, np.sqrt(3)/2, 0], color="#25364b", linewidth=1)
            for c, xy in zip(result["components"], [(-.025, -.035), (1.025, -.035), (.5, .9)]):
                ax.text(*xy, c, ha="center", fontsize=12)
            ax.set_aspect("equal"); ax.axis("off")
        else:
            for phase in result["active_phases"]:
                # Plot total amount of a phase; individual composition sets remain
                # separate in phases.csv and JSON even across a miscibility gap.
                values = [sum(s["amount"] for s in r["phases"] if s["phase"] == phase)
                          if r["status"] == "accepted" else np.nan for r in rows]
                if mode == "point":
                    ax.bar(phase, values[0])
                else:
                    ax.plot([r["T_K"] for r in rows], values, label=phase, marker=".", linewidth=1.6)
            ax.set_ylim(0, 1.04)
            ax.set_ylabel("Phase fraction (moles of atoms)")
            if mode != "point":
                ax.set_xlabel("Temperature (K)"); ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1))
            ax.grid(alpha=.18)

        def coordinates(point, state):
            if mode == "binary":
                return state["composition"][req["x_component"] or req["components"][-1]], point["T_K"]
            return ternary_xy(state["composition"], result["components"])

        if mode in {"binary", "ternary"}:
            # Actual coexisting compositions, never bulk coordinates disguised
            # as tie-line endpoints. Deduplicate for a readable figure.
            seen = set()
            ties = []
            for row in rows:
                states = [s for s in row["phases"] if s["amount"] > 1e-8]
                if len(states) < 2:
                    continue
                key = (row["T_K"], tuple(sorted(tuple(round(s["composition"][c], 4) for c in result["components"]) for s in states)))
                if key in seen:
                    continue
                seen.add(key); ties.append((row, states))
            for row, states in ties[::max(1, len(ties)//35)]:
                xy = np.array([coordinates(row, s) for s in states])
                if len(xy) > 2:
                    center = xy.mean(axis=0)
                    xy = xy[np.argsort(np.arctan2(xy[:, 1]-center[1], xy[:, 0]-center[0]))]
                    xy = np.vstack([xy, xy[0]])
                ax.plot(xy[:, 0], xy[:, 1], color="#586e81", linewidth=.55, alpha=.35)
            for line in result["boundaries"]["lines"]:
                names = {s["instance"] for p in line["points"] if p for s in p["phases"]}
                for name in names:
                    xy = []
                    for point in line["points"]:
                        state = next((s for s in point["phases"] if s["instance"] == name), None) if point else None
                        xy.append(coordinates(point, state) if state else (np.nan, np.nan))
                    if xy:
                        xy = np.array(xy)
                        ax.plot(xy[:, 0], xy[:, 1], color="#172a3a", linewidth=1.1)
            for point in result["boundaries"]["invariants"]:
                xy = np.array([coordinates(point, s) for s in point["phases"]])
                if mode == "binary":
                    xy = xy[np.argsort(xy[:, 0])]
                else:
                    xy = np.vstack([xy, xy[0]])
                ax.plot(xy[:, 0], xy[:, 1], color="#172a3a", linewidth=1.3)
        if mode in {"binary", "ternary", "isopleth"} and labels:
            ax.legend(handles=[Patch(facecolor=colors[label], alpha=.65, label=label) for label in labels],
                      loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8, title="Phase assemblages")
        title = {"binary": "Binary phase diagram", "ternary": "Ternary isothermal section",
                 "isopleth": "Multi-component isopleth", "property": "Equilibrium phase fractions", "point": "Equilibrium point"}[mode]
        summary = result["summary"]
        extra = f"; T={req['temperatures'][0]:g} K" if mode in {"ternary", "point"} else ""
        ax.set_title(f"{'–'.join(result['components'])} | {title}\nP={req['pressure']:g} Pa{extra}", fontsize=12)
        fig.supxlabel(f"{summary['accepted_points']}/{summary['total_points']} audited points | "
                      f"density-sensitive/unconfirmed: {summary['needs_refinement_points']} | "
                      f"boundary tracing: {result['boundaries']['status']}\n"
                      "Colors: sampled bulk equilibria. Lines: coexistence / traced boundaries. Numerical search; no global certificate.",
                      fontsize=8, color="#4c6171")
        fig.savefig(folder / "diagram.png", dpi=170)
        fig.savefig(folder / "diagram.svg")


def save_diagram(result, folder):
    bulk, phases, boundary_rows = [], [], []
    for row in result["rows"]:
        common = {"point_id": row["point_id"], "T_K": row["T_K"], "P_Pa": row["P_Pa"],
                  "path_coordinate": row["path_coordinate"], "status": row["status"]}
        bulk.append({**common, "assemblage": row["assemblage"], "G_J_mol_atoms": row.get("G_J_mol_atoms"),
                     "sampling_verified": row.get("sampling_verified", False), "needs_refinement": row.get("needs_refinement", False),
                     **{"X_"+c: x for c, x in row["composition"].items()},
                     **{"solver_X_"+c: x for c, x in row.get("solver_composition", {}).items()},
                     **{"MU_"+c: mu for c, mu in row.get("chemical_potentials_J_mol_atoms", {}).items()},
                     **row.get("audit", {}), "attempts": json.dumps(row["attempts"], ensure_ascii=False)})
        for state in row["phases"]:
            phases.append({**common, "phase": state["phase"], "instance": state["instance"], "NP": state["amount"],
                           "G_J_mol_atoms": state["G_J_mol_atoms"],
                           **{"X_"+c: x for c, x in state["composition"].items()}, **state["site_fractions"]})
    for kind, groups in [("line", result["boundaries"]["lines"]),
                         ("invariant", [{"points": [p]} for p in result["boundaries"]["invariants"]])]:
        for group_id, group in enumerate(groups):
            for point_id, point in enumerate(group["points"]):
                if point is None:
                    boundary_rows.append({"kind": kind, "group_id": group_id, "point_id": point_id, "status": "rejected"})
                    continue
                for state in point["phases"]:
                    boundary_rows.append({"kind": kind, "group_id": group_id, "point_id": point_id, "status": "accepted",
                                          "T_K": point["T_K"], "phase": state["phase"], "instance": state["instance"],
                                          "NP": state["amount"], **{"X_"+c: x for c, x in state["composition"].items()},
                                          **state["site_fractions"]})
    csv_file(folder / "diagram.csv", bulk, ["point_id", "status"])
    csv_file(folder / "phases.csv", phases, ["point_id", "phase", "NP"])
    csv_file(folder / "boundaries.csv", boundary_rows, ["kind", "group_id", "point_id", "status"])
    atomic_json(folder / "request.json", result["request"])
    plot_diagram(result, folder)
    result["files"] = {kind: str(folder / filename) for kind, filename in
                       [("json", "diagram.json"), ("csv", "diagram.csv"), ("phases", "phases.csv"),
                        ("boundaries", "boundaries.csv"), ("request", "request.json"),
                        ("png", "diagram.png"), ("svg", "diagram.svg"), ("html", "report.html")]}
    esc = html.escape
    links = " · ".join(f'<a href="{esc(path.rsplit(str(folder), 1)[-1].lstrip(chr(92)+chr(47)))}">{esc(kind.upper())}</a>'
                       for kind, path in result["files"].items() if kind != "html")
    summary = result["summary"]
    atomic_write(folder / "report.html", f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>AL-TDB 相图</title>
<style>body{{font:16px system-ui,sans-serif;max-width:1200px;margin:32px auto;padding:0 24px;color:#172a3a;background:#f4f7fa}}img{{width:100%;background:white}}pre{{white-space:pre-wrap;background:white;padding:20px;border-radius:8px}}a{{color:#1a5f9c}}.warning{{color:#9d391f}}</style>
<h1>{esc('–'.join(result['components']))} · 多相平衡相图</h1>
<p>{summary['accepted_points']}/{summary['total_points']} 个点通过数值审查；{summary['failed_points']} 个失败；
{summary['needs_refinement_points']} 个需要加密复查。相界追踪：{esc(result['boundaries']['status'])}。</p>
<p class="warning">相分数为原子摩尔分数。采样与相界追踪不能证明找全所有相区；缺少竞争相时仅是受限相图。</p>
<p>{links}</p><img src="diagram.png" alt="多相平衡相图">
<h2>计算范围</h2><pre>{esc(json.dumps(result['request'], ensure_ascii=False, indent=2))}</pre>
<h2>候选相与排除原因</h2><pre>{esc(json.dumps({'active': result['active_phases'], 'excluded': result['excluded_phases']}, ensure_ascii=False, indent=2))}</pre>
<p>JSON 保留总 Gibbs 能、元素化学势、每个组成集的相成分/占位/相分数、采样复查与数据库哈希。CSV 可直接供脚本使用。</p></html>''')
