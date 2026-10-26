"""Automatic bone mapping: canonical humanoid slots -> armature bone names.

Pure Python (no bpy) so it can be unit-tested outside Blender.
"""

import re

# Canonical slots in hierarchy order. "required" slots must be mapped for
# retargeting to run; the rest improve quality when present.
SLOTS = (
    "hips", "spine", "spine1", "spine2", "neck", "head",
    "shoulder.L", "upper_arm.L", "forearm.L", "hand.L",
    "shoulder.R", "upper_arm.R", "forearm.R", "hand.R",
    "thigh.L", "shin.L", "foot.L", "toe.L",
    "thigh.R", "shin.R", "foot.R", "toe.R",
    # Auxiliary end points (used only to measure rest-pose geometry).
    "toe_end.L", "toe_end.R", "index1.L", "index1.R", "pinky1.L", "pinky1.R",
)
REQUIRED = ("hips", "upper_arm.L", "forearm.L", "upper_arm.R", "forearm.R",
            "thigh.L", "shin.L", "thigh.R", "shin.R")
SPINE_SLOTS = ("spine", "spine1", "spine2")

MIXAMO = {
    "hips": "Hips", "spine": "Spine", "spine1": "Spine1", "spine2": "Spine2",
    "neck": "Neck", "head": "Head",
    "shoulder.L": "LeftShoulder", "upper_arm.L": "LeftArm", "forearm.L": "LeftForeArm",
    "hand.L": "LeftHand", "shoulder.R": "RightShoulder", "upper_arm.R": "RightArm",
    "forearm.R": "RightForeArm", "hand.R": "RightHand",
    "thigh.L": "LeftUpLeg", "shin.L": "LeftLeg", "foot.L": "LeftFoot", "toe.L": "LeftToeBase",
    "thigh.R": "RightUpLeg", "shin.R": "RightLeg", "foot.R": "RightFoot", "toe.R": "RightToeBase",
    "toe_end.L": "LeftToe_End", "toe_end.R": "RightToe_End",
    "index1.L": "LeftHandIndex1", "index1.R": "RightHandIndex1",
    "pinky1.L": "LeftHandPinky1", "pinky1.R": "RightHandPinky1",
}

# Side-less aliases (normalised: lowercase, alphanumerics only) for other rigs.
ALIASES = {
    "hips": ("hips", "hip", "pelvis", "root", "cog"),
    "spine": ("spine", "spine0", "spine01", "abdomen", "waist", "lowerback"),
    "spine1": ("spine1", "spine02", "chest", "torso", "midspine"),
    "spine2": ("spine2", "spine03", "upperchest", "chest1", "upperback"),
    "neck": ("neck", "neck1", "neck01"),
    "head": ("head",),
    "shoulder": ("shoulder", "clavicle", "collar", "collarbone"),
    "upper_arm": ("arm", "upperarm", "uparm", "humerus"),
    "forearm": ("forearm", "lowerarm", "elbow", "radius"),
    "hand": ("hand", "wrist"),
    "thigh": ("upleg", "upperleg", "thigh", "femur"),
    "shin": ("leg", "lowerleg", "calf", "shin", "knee", "tibia"),
    "foot": ("foot", "ankle"),
    "toe": ("toebase", "toe", "toes", "ball"),
    "toe_end": ("toeend", "toetip", "toesend"),
    "index1": ("handindex1", "index1", "indexfinger1", "index01"),
    "pinky1": ("handpinky1", "pinky1", "little1", "pinkyfinger1", "pinky01"),
}

def strip_prefix(name):
    """'mixamorig:LeftArm' -> 'LeftArm', 'mixamorig9:Hips' -> 'Hips'."""
    return name.rsplit(":", 1)[-1].rsplit("|", 1)[-1]


def split_side(name):
    """Return (side, base) where side is 'L', 'R' or None and base is normalised."""
    raw = strip_prefix(name)
    # CamelCase prefixes: LeftArm / RightUpLeg
    m = re.match(r"^(Left|Right)(?=[A-Z_ .\-]|$)", raw)
    if m:
        side = "L" if m.group(1) == "Left" else "R"
        return side, _norm(raw[len(m.group(1)):])
    low = raw.lower()
    for token, side in (("left", "L"), ("right", "R")):
        if token in low:
            return side, _norm(low.replace(token, ""))
    # Suffix/prefix single-letter conventions: upper_arm.L, Arm_L, L_Arm, thigh_l
    m = re.match(r"^(.*?)[\._\- ]([LlRr])$", raw)
    if m:
        return m.group(2).upper(), _norm(m.group(1))
    m = re.match(r"^([LlRr])[\._\- ](.*)$", raw)
    if m:
        return m.group(1).upper(), _norm(m.group(2))
    return None, _norm(raw)


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def auto_map(bone_names):
    """Map canonical slots to bone names. Returns (mapping, report).

    Exact Mixamo names (ignoring namespace prefixes) are tried first, then
    generic aliases. A bone is used at most once.
    """
    by_stripped = {}
    for b in bone_names:
        by_stripped.setdefault(strip_prefix(b), b)
    mapping, used = {}, set()

    for slot, mixamo_name in MIXAMO.items():
        b = by_stripped.get(mixamo_name)
        if b and b not in used:
            mapping[slot] = b
            used.add(b)

    parsed = [(b, *split_side(b)) for b in bone_names if b not in used]
    for slot in SLOTS:
        if slot in mapping:
            continue
        base, _, side = slot.partition(".")
        side = side or None
        aliases = ALIASES.get(base, (base,))
        best = None
        for b, b_side, b_base in parsed:
            if b in used or b_side != side:
                continue
            if b_base in aliases:
                rank = aliases.index(b_base)
                if best is None or rank < best[0]:
                    best = (rank, b)
        if best:
            mapping[slot] = best[1]
            used.add(best[1])

    missing_required = [s for s in REQUIRED if s not in mapping]
    report = {
        "mapped": len(mapping),
        "total_slots": len(SLOTS),
        "missing_required": missing_required,
        "missing_optional": [s for s in SLOTS if s not in mapping and s not in REQUIRED],
        "is_mixamo": all(s in mapping and strip_prefix(mapping[s]) == MIXAMO[s] for s in REQUIRED),
        "ok": not missing_required,
    }
    return mapping, report
