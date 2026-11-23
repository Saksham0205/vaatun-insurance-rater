from __future__ import annotations

import hashlib
import json
from pathlib import Path


EXPECTED_POLICY_FILES = (
    "pvt-car-comprehensive-hdfc-ergo.pdf",
    "pvt-car-satp-go-digit.pdf",
    "pvt-car-comprehensive-reliance.pdf",
    "pvt-car-satp-tata-aig.pdf",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_audit(repository_root: str | Path) -> dict:
    root = Path(repository_root)
    cards_dir = root / "backend" / "rate_cards"
    actual_cards = sorted(p for p in cards_dir.rglob("*") if p.is_file()) if cards_dir.exists() else []
    policy_dir = root / "sample-policies"
    manifest = root / "MANIFEST.json"
    missing = [f"sample-policies/{name}" for name in EXPECTED_POLICY_FILES
               if not (policy_dir / name).is_file()]
    actual_hashes = {p.relative_to(root).as_posix(): sha256_file(p) for p in actual_cards}
    manifest_entries: list[dict] = []
    if manifest.is_file():
        raw = json.loads(manifest.read_text(encoding="utf-8"))

        def collect(node):
            if isinstance(node, dict):
                file_name = node.get("path") or node.get("file") or node.get("name")
                checksum = node.get("sha256") or node.get("SHA256") or node.get("checksum")
                if isinstance(file_name, str) and isinstance(checksum, str):
                    manifest_entries.append({"file": file_name.replace("\\", "/"), "sha256": checksum.lower()})
                for value in node.values():
                    collect(value)
            elif isinstance(node, list):
                for value in node:
                    collect(value)

        collect(raw)
    checks = []
    aliases = {
        "README.md": root / "BUNDLE_README.md",
        "challenge.md": root / "CHALLENGE.md",
    }
    for entry in manifest_entries:
        actual = actual_hashes.get(entry["file"])
        if actual is None:
            rel = entry["file"]
            candidate = aliases.get(rel)
            if candidate is None and rel.startswith("raters/"):
                candidate = root / "backend" / "rate_cards" / rel.removeprefix("raters/")
            if candidate is None:
                candidate = root / rel
            actual = sha256_file(candidate) if candidate.is_file() else None
        checks.append({**entry, "actual_sha256": actual,
                       "matches": actual == entry["sha256"] if actual is not None else False})
    return {
        "rate_cards": [{"file": p.relative_to(root).as_posix(), "sha256": sha256_file(p)}
                       for p in actual_cards],
        "missing_policy_files": missing,
        "manifest_present": manifest.is_file(),
        "manifest_checks": checks,
        "manifest_unparsed": bool(manifest.is_file() and not manifest_entries),
    }
