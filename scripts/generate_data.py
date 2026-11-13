from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import DEFAULT_SEED
from src.generators.master_data_generator import generate_dataset
from src.utils.dataset_io import write_dataset
from src.validation.dataset_validation import validate_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a schema-aligned recruitment dataset.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--scale", choices=["starter", "full"], default="starter")
    args = parser.parse_args()

    dataset = generate_dataset(seed=args.seed, scale=args.scale)
    errors = validate_dataset(dataset)
    if errors:
        print("Dataset validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        raise SystemExit(1)

    path = ROOT / "data" / "processed" / "dataset.json"
    write_dataset(path, dataset)
    print(f"Generated and validated {args.scale} dataset with seed {args.seed}.")
    for table_name, count in dataset["metadata"]["record_counts"].items():
        print(f"  {table_name}: {count}")
    print(f"JSON: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
