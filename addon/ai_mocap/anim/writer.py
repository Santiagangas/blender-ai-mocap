"""Write solver output as a native Blender Action (Blender 4.4+ slotted actions).

Keys are inserted in bulk with ``keyframe_points.foreach_set`` (orders of
magnitude faster than ``keyframe_insert``). Existing actions are never
modified: every generation creates a new Action with a unique name and
``use_fake_user`` so it survives saving even when unassigned.
"""

import bpy
import numpy as np


def unique_action_name(base):
    if base not in bpy.data.actions:
        return base
    i = 1
    while f"{base}.{i:03d}" in bpy.data.actions:
        i += 1
    return f"{base}.{i:03d}"


def _channelbag(action, slot):
    try:
        from bpy_extras.anim_utils import action_ensure_channelbag_for_slot
        return action_ensure_channelbag_for_slot(action, slot)
    except ImportError:  # pragma: no cover - very old 4.4 builds
        layer = action.layers[0] if action.layers else action.layers.new("Layer")
        strip = layer.strips[0] if layer.strips else layer.strips.new(type='KEYFRAME')
        return strip.channelbag(slot, ensure=True)


def _write_curve(cbag, group, data_path, index, frames, values):
    fc = cbag.fcurves.new(data_path, index=index)
    fc.group = group
    kp = fc.keyframe_points
    kp.add(len(frames))
    co = np.empty(2 * len(frames), dtype=np.float32)
    co[0::2], co[1::2] = frames, values
    kp.foreach_set("co", co)
    # Every frame is keyed, so linear interpolation reproduces the solve exactly
    # and avoids Bezier overshoot; it can be changed freely in the Graph Editor.
    kp.foreach_set("interpolation", np.ones(len(frames), dtype=np.int32))  # 1 = LINEAR
    fc.update()
    return fc


def write_action(arm_obj, result, frame_start, name, frame_step=1.0, assign=True):
    """Create a new Action from a SolveResult and (optionally) assign it.

    Returns the Action. The previous action stays in bpy.data (and in the NLA
    if the user pushed it there); nothing is deleted.
    """
    action = bpy.data.actions.new(unique_action_name(name))
    action.use_fake_user = True
    slot = action.slots.new(id_type='OBJECT', name=arm_obj.name)
    if not action.layers:
        action.layers.new("Layer").strips.new(type='KEYFRAME')
    cbag = _channelbag(action, slot)

    any_q = next(iter(result.quaternions.values()))
    frames = frame_start + np.arange(len(any_q), dtype=np.float64) * frame_step
    for bone_name, quats in result.quaternions.items():
        pb = arm_obj.pose.bones.get(bone_name)
        if pb is None:
            continue
        if pb.rotation_mode != 'QUATERNION':
            pb.rotation_mode = 'QUATERNION'
        group = cbag.groups.get(bone_name) or cbag.groups.new(bone_name)
        path = f'pose.bones["{bpy.utils.escape_identifier(bone_name)}"].rotation_quaternion'
        for c in range(4):
            _write_curve(cbag, group, path, c, frames, quats[:, c])
    if result.root_location is not None:
        group = cbag.groups.get(result.root_bone) or cbag.groups.new(result.root_bone)
        path = f'pose.bones["{bpy.utils.escape_identifier(result.root_bone)}"].location'
        for c in range(3):
            _write_curve(cbag, group, path, c, frames, result.root_location[:, c])

    if assign:
        ad = arm_obj.animation_data or arm_obj.animation_data_create()
        ad.action = action
        ad.action_slot = slot
    return action
