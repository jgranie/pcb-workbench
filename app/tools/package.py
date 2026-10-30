"""Build a deterministic source-only archive from an explicit allowlist."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    files = [ROOT / name for name in ["README.md", "THIRD_PARTY.md", "requirements.lock", "config.json", "workshop",
                                     ".gitignore", ".python-version", ".node-version"]]
    for pattern in ["pcb_workshop/*.py", "web/*.html", "web/*.mjs", "web/core/*.mjs", "docs/*.md", "docs/*.json", "tests/*.py",
                    "tests/*.mjs", "tools/*.py", "examples/generate.py", "examples/synthetic.png", "examples/truth.json"]:
        files.extend(ROOT.glob(pattern))
    files = sorted(set(files))
    payloads = {str(p.relative_to(ROOT)): p.read_bytes() for p in files}
    for name, data in payloads.items():
        if Path(name).suffix in (".py", ".mjs", ".md", ".json", ".html", ".lock") or name == "workshop":
            if (b"/" + b"Users/") in data or (b"/" + b"Volumes/") in data:
                raise SystemExit(f"Chemin personnel interdit dans le paquet : {name}")
    payloads["bundle-manifest.json"] = (json.dumps({"files_sha256": {name: hashlib.sha256(data).hexdigest()
        for name, data in payloads.items()}, "private_artifacts_included": False, "license_selected": False}, sort_keys=True, indent=2) + "\n").encode()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise SystemExit("Archive existante : choisir un autre nom.")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(payloads.items()):
            item = zipfile.ZipInfo("pcb-workshop-repro/" + name, date_time=(2026, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = (0o100755 if name == "workshop" else 0o100644) << 16
            archive.writestr(item, data)
    print(json.dumps({"archive": str(output), "files": len(payloads), "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
