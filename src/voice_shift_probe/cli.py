"""CPU evidence audit or optional offline GPU inference."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit", help="Recalculate frozen results without audio/GPU")
    audit.add_argument("--evidence", type=Path, default=Path("evidence"))
    predict = commands.add_parser("predict", help="Diagnostic four-view inference with an external frozen baseline")
    predict.add_argument("--audio", type=Path, required=True)
    predict.add_argument("--baseline-dir", type=Path, required=True)
    predict.add_argument("--ffmpeg", type=Path)
    predict.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "audit":
        from .evidence import audit_evidence
        print(json.dumps(audit_evidence(args.evidence), ensure_ascii=False, indent=2))
        return
    if args.out.exists():
        parser.error("Output already exists; use a new --out path")
    from .audio import decode, file_hash, resolve_ffmpeg
    from .model import FrozenDFBackend, probe
    executable = resolve_ffmpeg(args.ffmpeg)
    wave = decode(args.audio, executable)
    if len(wave) < 4096:
        parser.error("Research protocol requires at least 4096 decoded samples")
    result = probe(wave, FrozenDFBackend(args.baseline_dir), executable)
    result["input_sha256"] = file_hash(args.audio)
    result["sample_rate"] = 16000
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"research_only": True, "mean_score": result["mean_score"], "output": str(args.out)}))


if __name__ == "__main__":
    main()
