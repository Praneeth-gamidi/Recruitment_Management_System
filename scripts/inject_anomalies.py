from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.generators.anomaly_injector import inject_anomalies, validate_anomaly_ground_truth
from src.utils.dataset_io import dataset_json, json_default, load_dataset
from src.validation.dataset_validation import validate_dataset


def main() -> None:
    dataset_path = ROOT / "data" / "processed" / "dataset.json"
    if not dataset_path.is_file():
        raise SystemExit("No dataset found; run scripts/generate_data.py first.")
    dataset = load_dataset(dataset_path)
    errors = validate_dataset(dataset)
    if errors:
        raise SystemExit("Refusing to inject anomalies into an invalid baseline dataset.")

    original = dataset_json(dataset)
    cases, ground_truth = inject_anomalies(dataset)
    errors = validate_anomaly_ground_truth(cases, ground_truth)
    if errors:
        raise SystemExit("Anomaly fixture validation failed: " + "; ".join(errors))
    if dataset_json(dataset) != original:
        raise SystemExit("Anomaly generation modified the clean baseline dataset.")

    anomaly_dir = ROOT / "data" / "anomalies"
    truth_dir = ROOT / "data" / "ground_truth"
    anomaly_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)
    (anomaly_dir / "anomaly_cases.json").write_text(
        json.dumps(cases, default=json_default, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (truth_dir / "anomalies.json").write_text(
        json.dumps(ground_truth, default=json_default, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Generated {len(cases)} isolated anomaly cases and separate ground-truth records.")


if __name__ == "__main__":
    main()
