"""Armature discovery and rest-pose extraction (Blender side)."""

import numpy as np

from .mapping import auto_map
from ..retarget.solver import RigRest


def find_armature(obj):
    """Return the armature for the selected object (armature, skinned mesh or child)."""
    if obj is None:
        return None
    if obj.type == 'ARMATURE':
        return obj
    if obj.type == 'MESH':
        for mod in obj.modifiers:
            if mod.type == 'ARMATURE' and mod.object is not None:
                return mod.object
    parent = obj.parent
    while parent is not None:
        if parent.type == 'ARMATURE':
            return parent
        parent = parent.parent
    return None


def ordered_bones(arm_obj):
    """Bones sorted so that every parent precedes its children."""
    out = []

    def visit(bone):
        out.append(bone)
        for child in bone.children:
            visit(child)

    for bone in arm_obj.data.bones:
        if bone.parent is None:
            visit(bone)
    return out


def extract_rest(arm_obj, mapping=None):
    """Build a RigRest from the armature's rest pose (non-destructive, read-only)."""
    bones = ordered_bones(arm_obj)
    names = [b.name for b in bones]
    index = {n: i for i, n in enumerate(names)}
    parents = np.array([index[b.parent.name] if b.parent else -1 for b in bones])
    rest = np.array([np.array(b.matrix_local) for b in bones], dtype=np.float64)
    heads = np.array([tuple(b.head_local) for b in bones], dtype=np.float64)
    tails = np.array([tuple(b.tail_local) for b in bones], dtype=np.float64)
    if mapping is None:
        mapping, _ = auto_map(names)
    return RigRest(names=names, parents=parents, rest=rest, heads=heads, tails=tails,
                   mapping=dict(mapping))
