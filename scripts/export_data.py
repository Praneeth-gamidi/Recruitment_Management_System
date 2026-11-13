from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils.dataset_io import dataset_json, load_dataset, write_csv_exports
from src.validation.dataset_validation import validate_dataset


def main() -> None:
    dataset_path = ROOT / "data" / "processed" / "dataset.json"
    if not dataset_path.is_file():
        raise SystemExit("No dataset found; run scripts/generate_data.py first.")
    dataset = load_dataset(dataset_path)
    errors = validate_dataset(dataset)
    if errors:
        raise SystemExit("Refusing to export an invalid dataset: " + "; ".join(errors[:10]))

    export_dir = ROOT / "data" / "exports"
    csv_hashes = write_csv_exports(dataset, export_dir)
    json_text = dataset_json(dataset)
    json_path = export_dir / "dataset.json"
    json_path.write_bytes(json_text.encode("utf-8"))
    manifest = {
        "dataset_name": dataset["metadata"]["dataset_name"],
        "seed": dataset["metadata"]["seed"],
        "scale": dataset["metadata"]["scale"],
        "record_counts": dataset["metadata"]["record_counts"],
        "dataset_sha256": hashlib.sha256(json_text.encode("utf-8")).hexdigest(),
        "csv_sha256": csv_hashes,
    }
    (export_dir / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Exported validated dataset JSON and {len(csv_hashes)} table CSV files to data/exports.")


if __name__ == "__main__":
    main()
