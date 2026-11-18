"""Data consumed by LocalApplication and its matching forecast backup calculator."""

from collections.abc import Iterator
from pathlib import Path


def runtime_data_files(data_root: Path) -> Iterator[Path]:
    # Keep runtime references, including their required provenance artifacts.
    # Unprocessed source archives (reference/aip) are repository evidence, not inputs.
    source_archives = data_root / "reference/aip"
    for folder in ("performance", "reference"):
        for path in sorted((data_root / folder).rglob("*")):
            if path.is_file() and not path.is_relative_to(source_archives):
                yield path
