from __future__ import annotations

import argparse
import gc
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import DEFAULT_SEED
from src.generators.master_data_generator import generate_dataset
from src.utils.dataset_io import dataset_json, write_csv_exports
from src.validation.dataset_validation import validate_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify deterministic synthetic dataset output.")
    parser.add_argument("--scale", choices=["starter", "full"], default="starter")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="recruitment-repro-") as temp_dir:
        export_a = Path(temp_dir) / "a"
        export_b = Path(temp_dir) / "b"

        dataset_a = generate_dataset(seed=DEFAULT_SEED, scale=args.scale)
        errors_a = validate_dataset(dataset_a)
        counts_a = dataset_a["metadata"]["record_counts"]
        json_hash_a = hashlib.sha256(dataset_json(dataset_a).encode("utf-8")).hexdigest()
        hashes_a = write_csv_exports(dataset_a, export_a)
        del dataset_a
        gc.collect()

        dataset_b = generate_dataset(seed=DEFAULT_SEED, scale=args.scale)
        errors_b = validate_dataset(dataset_b)
        counts_b = dataset_b["metadata"]["record_counts"]
        json_hash_b = hashlib.sha256(dataset_json(dataset_b).encode("utf-8")).hexdigest()
        hashes_b = write_csv_exports(dataset_b, export_b)

    report = {
        "seed": DEFAULT_SEED,
        "scale": args.scale,
        "valid_a": not errors_a,
        "valid_b": not errors_b,
        "json_equal": json_hash_a == json_hash_b,
        "dataset_sha256_a": json_hash_a,
        "dataset_sha256_b": json_hash_b,
        "csv_hashes_equal": hashes_a == hashes_b,
        "record_counts": counts_a,
        "record_counts_equal": counts_a == counts_b,
        "errors": errors_a + errors_b,
    }
    report["reproducible"] = (
        report["valid_a"]
        and report["valid_b"]
        and report["json_equal"]
        and report["csv_hashes_equal"]
        and report["record_counts_equal"]
    )
    report_path = ROOT / "data" / "processed" / "reproducibility.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{args.scale.title()} dataset reproducible: {report['reproducible']}")
    print(f"SHA-256: {report['dataset_sha256_a']}")
    if not report["reproducible"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
