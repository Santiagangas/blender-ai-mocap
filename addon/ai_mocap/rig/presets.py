"""Bone-mapping presets stored as JSON (pure Python, no bpy).

A preset maps canonical slots to bone names *without* namespace prefixes
(``mixamorig:``, ``mixamorig1:``…), so one preset fits every variant of the
same rig. Built-in presets ship with the add-on; user presets live in the
add-on's user folder.
"""

import json
import os
import re

from .mapping import SLOTS, strip_prefix

BUILTIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "presets")
FORMAT_VERSION = 1


def _safe_filename(name):
    base = re.sub(r"[^\w\- ]", "_", name, flags=re.UNICODE).strip() or "preset"
    return base[:60] + ".json"


def list_presets(user_dir):
    """Return [(id, name, path, builtin)] sorted with built-ins first."""
    out = []
    for folder, builtin in ((BUILTIN_DIR, True), (user_dir, False)):
        if not folder or not os.path.isdir(folder):
            continue
        for fn in sorted(os.listdir(folder)):
            if not fn.lower().endswith(".json"):
                continue
            path = os.path.join(folder, fn)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    name = json.load(fh).get("name") or fn[:-5]
            except (OSError, ValueError):
                continue
            out.append((("B:" if builtin else "U:") + fn, name, path, builtin))
    return out


def save_preset(user_dir, name, mapping):
    os.makedirs(user_dir, exist_ok=True)
    data = {"format": FORMAT_VERSION, "name": name,
            "mapping": {s: strip_prefix(b) for s, b in mapping.items() if b}}
    path = os.path.join(user_dir, _safe_filename(name))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
    return path


def load_preset(path):
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    mapping = data.get("mapping")
    if not isinstance(mapping, dict):
        raise ValueError("El preset no contiene un mapeo válido.")
    return {s: str(b) for s, b in mapping.items() if s in SLOTS and b}


def resolve(preset_mapping, bone_names):
    """Match preset bone names (prefix-free) against the armature's bones.

    Returns (mapping, unmatched_slots).
    """
    by_exact = set(bone_names)
    by_stripped = {}
    for b in bone_names:
        by_stripped.setdefault(strip_prefix(b).lower(), b)
    mapping, unmatched = {}, []
    for slot, name in preset_mapping.items():
        if name in by_exact:
            mapping[slot] = name
        elif name.lower() in by_stripped:
            mapping[slot] = by_stripped[name.lower()]
        else:
            unmatched.append(slot)
    return mapping, unmatched
