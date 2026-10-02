"""Independently recompute historical metrics; hashes are integrity, not external attestation."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

from .metrics import summarize_rows


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def audit_evidence(directory):
    directory = Path(directory).resolve()
    index = json.loads((directory / "index.json").read_text(encoding="utf-8"))
    for relative, expected in index["sha256"].items():
        path = (directory / relative).resolve()
        if not path.is_relative_to(directory) or not path.is_file() or digest(path) != expected:
            raise ValueError("Evidence file missing, changed, or outside root: " + relative)
    root = directory / "frozen"
    result = json.loads((root / "results.json").read_text(encoding="utf-8"))
    saved = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    protocol = json.loads((root / "protocol.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "prep_manifest.json").read_text(encoding="utf-8"))
    provenance = result["provenance"]
    for key, name in (("prep_manifest_sha256", "prep_manifest.json"),
                      ("protocol_sha256", "protocol.json"),
                      ("runner_sha256", "gpu_inference.py")):
        if provenance[key] != digest(root / name):
            raise ValueError("Frozen provenance mismatch: " + key)
    if protocol["inputs"]["manifest_sha256"] != digest(root / "prep_manifest.json"):
        raise ValueError("Protocol refers to different inputs")
    if result["provenance"] != saved["provenance"] or result["runtime_runs"] != saved["runtime_runs"]:
        raise ValueError("Summary provenance or runtime differs")
    rows = result["rows"]
    expected = {(source["id"], view): (source, info)
                for source in manifest["rows"] for view, info in source["variants"].items()}
    if len(expected) != 256 or len(rows) != 256:
        raise ValueError("Expected 64 sources and 256 views")
    if set(protocol["inputs"]["ids"]) != {r["id"] for r in manifest["rows"]}:
        raise ValueError("Protocol and manifest source IDs differ")
    for row in rows:
        source, info = expected[(row["id"], row["variant"])]
        if (row["input_sha256"] != info["sha256"] or row["samples"] != info["samples"]
                or row["label"] != source["label"] or row["generator"] != source["generator"]):
            raise ValueError("Row differs from frozen input manifest")
    with (root / "results.csv").open(encoding="utf-8", newline="") as stream:
        csv_rows = list(csv.DictReader(stream))
    if len(csv_rows) != len(rows):
        raise ValueError("CSV row count differs")
    for text_row, row in zip(csv_rows, rows):
        if set(text_row) != set(row) or any(str(row[k]) != text_row[k] for k in row):
            raise ValueError("JSON and CSV differ")
    calculated = summarize_rows(rows)
    for view, values in calculated.items():
        for key, value in values.items():
            if not math.isclose(value, saved["metrics"][view][key], rel_tol=0, abs_tol=1e-12):
                raise ValueError(f"Recomputed metric differs: {view}/{key}")
    return {"status": "passed", "originals": 64, "views": 256,
            "scope": "CPU recomputation of archived raw-voice results; no fresh GPU or audio verification",
            "files_checked": len(index["sha256"]), "metrics": calculated}
