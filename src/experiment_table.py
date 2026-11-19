"""Read delimited experimental tables without changing their source units or cells."""

import csv
import hashlib
import io
import math
from collections import defaultdict
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from src import project_catalog as cat


class Mapping(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    paper: str
    phase: str = ""
    keep_unmapped: bool = False
    system: list[str] = Field(default_factory=list)
    locator: str = Field(default="", max_length=500)
    phase_col: str = ""
    locator_col: str = ""
    quantity_col: str = ""
    value_col: str = ""
    unit_col: str = ""
    unit: str = Field(default="", max_length=160)
    temp_col: str = ""
    temp_unit: Literal["", "K", "°C"] = ""


def parse(raw):
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16")
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("gb18030")
    if "\0" in text or not text.strip():
        raise ValueError("请选择含表头的 CSV 或 TSV 文本文件")
    leading = len(text) - len(text.lstrip("\r\n"))
    offset = len(text[:leading].splitlines())
    text = text[leading:]
    first = text.splitlines()[0]
    delimiter = max(
        (",", "\t", ";"), key=lambda sep: len(next(csv.reader([first], delimiter=sep)))
    )
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    try:
        headers = [v.strip() for v in next(reader)]
        if not all(headers) or len(set(headers)) != len(headers) or len(headers) > 128:
            raise ValueError("表头需非空、互不重复，最多 128 列")
        rows = []
        while True:
            line = offset + reader.line_num + 1
            cells = next(reader, None)
            if cells is None:
                break
            if not any(v.strip() for v in cells):
                continue
            if len(cells) != len(headers):
                raise ValueError(
                    f"第 {line} 行有 {len(cells)} 列，表头有 {len(headers)} 列"
                )
            rows.append((line, dict(zip(headers, cells))))
            if len(rows) > 2000:
                raise ValueError("每次最多导入 2000 行，请拆分表格")
    except csv.Error as exc:
        raise ValueError(f"第 {reader.line_num} 行 CSV 引号或字段格式错误") from exc
    if not rows:
        raise ValueError("表头下没有数据行")
    return headers, rows


def mapped_rows(db, pid, mapping, filename, digest, headers, rows):
    cat.owned(db, "papers", pid, mapping.paper)
    system = cat.checked_system(db, pid, mapping.system) if mapping.system else []
    columns = [
        mapping.phase_col,
        mapping.locator_col,
        mapping.quantity_col,
        mapping.value_col,
        mapping.unit_col,
        mapping.temp_col,
    ]
    if any(c and c not in headers for c in columns):
        raise ValueError("列名已改变，请重新选择映射")
    if mapping.temp_col and not mapping.temp_unit:
        raise ValueError("请选择温度列的单位")
    phases = defaultdict(set)
    labels = {}
    for r in db.execute("SELECT id,name,alias FROM phases WHERE project=?", (pid,)):
        labels[r["id"]] = r["name"] or r["alias"]
        for name in (r["id"], r["name"], r["alias"]):
            if name:
                phases[name.casefold()].add(r["id"])
    if mapping.phase and mapping.phase not in labels:
        raise ValueError("默认相不属于本项目")
    # Identify an original row by its source paper, file digest and physical line.
    # Later edits to a measurement must not cause the same file to insert it again.
    seen = set()
    for row in db.execute(
        """SELECT json_extract(payload,'$.csv_source.line') FROM observations
        WHERE project=? AND paper=? AND json_extract(payload,'$.csv_source.sha256')=?""",
        (pid, mapping.paper, digest),
    ):
        seen.add(row[0])
    results = []
    for line, cells in rows:

        def cell(column):
            return cells.get(column, "").strip()

        name = cell(mapping.phase_col)
        candidates = (
            phases.get(name.casefold(), set()) if name else {mapping.phase} - {""}
        )
        if len(candidates) != 1 and not mapping.keep_unmapped:
            raise ValueError(
                f"第 {line} 行无法确定项目相「{name}」，请核对相名或选择默认相"
            )
        phase = next(iter(candidates)) if len(candidates) == 1 else None
        locator = cell(mapping.locator_col) or mapping.locator
        if not locator or len(locator) > 500:
            raise ValueError(f"第 {line} 行需要图、表或页码，最多 500 字")
        unit = cell(mapping.unit_col) or mapping.unit
        value = (
            cell(mapping.value_col)
            if mapping.value_col
            else "；".join(
                f"{key} = {v}"
                for key, v in cells.items()
                if key not in columns and v.strip()
            )
        )
        if not value:
            raise ValueError(f"第 {line} 行没有测量值，请检查数值列")
        payload = {
            "kind": "experiment",
            "value": value,
            "unit": unit,
            "csv_source": {
                "file": filename,
                "sha256": digest,
                "line": line,
                "cells": cells,
            },
        }
        quantity = cell(mapping.quantity_col) or mapping.value_col
        if system:
            payload["system"] = system
        if name:
            payload["reported_phase"] = name
        if quantity:
            payload["quantity"] = quantity
        temp = cell(mapping.temp_col)
        if temp:
            try:
                kelvin = float(temp) + (273.15 if mapping.temp_unit == "°C" else 0)
                if not math.isfinite(kelvin) or kelvin <= 0:
                    raise ValueError()
            except ValueError as exc:
                raise ValueError(f"第 {line} 行温度无效，请检查数值和单位") from exc
            payload["T_K"] = kelvin
        results.append(
            {
                "line": line,
                "phase": phase,
                "phase_label": labels.get(phase) or ((name + " · ") if name else "") + "待映射",
                "locator": locator,
                "payload": payload,
                "duplicate": line in seen,
            }
        )
    token = hashlib.sha256(
        cat.pack(
            [
                pid,
                filename,
                digest,
                mapping.model_dump(),
                [(r["phase"], r["phase_label"]) for r in results],
            ]
        ).encode()
    ).hexdigest()
    return results, token
