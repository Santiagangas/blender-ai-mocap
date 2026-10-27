"""Build the installable extension ZIP.

    python tools/build_zip.py [--out dist]

Packs ``addon/ai_mocap`` with the manifest at the ZIP root and bundles the
capture engine source as ``engine_src/ai_mocap_engine`` (it is copied to
the user's machine and run in the engine's own venv, never imported by
Blender). The result installs with Blender → Edit → Preferences → Get
Extensions → Install from Disk.
"""

import argparse
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
ADDON = os.path.join(ROOT, "addon", "ai_mocap")
ENGINE = os.path.join(ROOT, "engine", "ai_mocap_engine")
SKIP_DIRS = {"__pycache__", ".pytest_cache", "engine_src"}
SKIP_EXT = {".pyc", ".pyo", ".blend1"}


def manifest_version():
    with open(os.path.join(ADDON, "blender_manifest.toml"), "r", encoding="utf-8") as fh:
        m = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.M)
    return m.group(1)


def walk(src, arc_prefix):
    for root, dirs, files in os.walk(src):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for f in sorted(files):
            if os.path.splitext(f)[1] in SKIP_EXT:
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(full, src).replace(os.sep, "/")
            yield full, (arc_prefix + rel) if arc_prefix else rel


def build(out_dir):
    version = manifest_version()
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"ai_mocap-{version}.zip")
    names = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for full, arc in list(walk(ADDON, "")) + list(walk(ENGINE, "engine_src/ai_mocap_engine/")):
            zf.write(full, arc)
            names.append(arc)
    assert "blender_manifest.toml" in names and "__init__.py" in names
    assert "engine_src/ai_mocap_engine/cli.py" in names
    assert "engine_requirements.txt" in names and "presets/mixamo.json" in names
    print(f"{out}  ({len(names)} files, {os.path.getsize(out) / 1024:.0f} KB)")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    sys.exit(0 if build(ap.parse_args().out) else 1)
