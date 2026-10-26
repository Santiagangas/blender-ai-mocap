"""Blender integration test (background mode):

    blender -b --factory-startup --python test_persistence.py -- <result.blend> <engine_out_dir> <tmp_dir>

Checks, on a file produced by the closed-loop evaluation:
* the generated Action survived save + reopen, with keys on every frame;
* the original (ground-truth) Action is untouched;
* the joints actually move (pose differs from rest);
* generating a second animation creates a NEW Action and keeps the first;
* both survive another save + reopen.
Exit code 0 when all checks pass.
"""

import os
import sys

import bpy
import numpy as np

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "addon"))

from ai_mocap.anim.writer import _channelbag  # noqa: E402
from ai_mocap.core.apply import apply_motion  # noqa: E402

failures = []


def check(cond, msg):
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond:
        failures.append(msg)


def fcurves(action, obj):
    return list(_channelbag(action, obj.animation_data.action_slot).fcurves)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    blend, engine_dir, tmp = (os.path.realpath(a) for a in argv[:3])
    os.makedirs(tmp, exist_ok=True)

    bpy.ops.wm.open_mainfile(filepath=blend)
    arm = bpy.data.objects.get("Mocap_Armature")
    first = bpy.data.actions.get("Mocap_closed_loop")
    check(arm is not None and first is not None, "reopened file has armature and generated Action")
    check(arm.animation_data.action == first, "generated Action is still assigned after reopen")
    check(first.use_fake_user, "generated Action has fake user (survives when unassigned)")
    fcs = fcurves(first, arm)
    check(len(fcs) == 18 * 4 + 3, f"75 F-Curves (18 bones x quaternion + root location), got {len(fcs)}")
    check(all(len(fc.keyframe_points) == 180 for fc in fcs), "180 keyframes per F-Curve")
    check("GT_closed_loop" in bpy.data.actions and
          bpy.data.objects["GT_Armature"].animation_data.action.name == "GT_closed_loop",
          "pre-existing Action untouched")

    scene = bpy.context.scene
    scene.frame_set(31)
    moved = max(np.degrees(pb.rotation_quaternion.angle) for pb in arm.pose.bones)
    check(moved > 20, f"joints respond to the capture (max bone rotation {moved:.1f} deg at frame 31)")

    # Editing a key like a user would.
    kp = fcs[0].keyframe_points[10]
    kp.co.y += 0.1
    fcs[0].update()
    check(abs(fcs[0].evaluate(kp.co.x) - kp.co.y) < 1e-5, "keyframes are editable")

    second, report = apply_motion(arm, engine_dir, frame_start=1, action_name="Mocap_closed_loop")
    check(second.name == "Mocap_closed_loop.001", f"second generation creates a new Action ({second.name})")
    check("Mocap_closed_loop" in bpy.data.actions, "first generated Action still exists")
    check(arm.animation_data.action == second, "second Action is assigned")

    path2 = os.path.join(tmp, "persistence_roundtrip.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path2)
    bpy.ops.wm.open_mainfile(filepath=path2)
    names = set(bpy.data.actions.keys())
    check({"Mocap_closed_loop", "Mocap_closed_loop.001", "GT_closed_loop"} <= names,
          f"all three Actions persist after second save/reopen ({sorted(names)})")
    arm = bpy.data.objects["Mocap_Armature"]
    check(abs(fcurves(arm.animation_data.action, arm)[0].keyframe_points[10].co.y
              - fcurves(bpy.data.actions['Mocap_closed_loop.001'], arm)[0].keyframe_points[10].co.y) < 1e-6,
          "reopened second Action has its keys")

    print(f"RESULT {'OK' if not failures else 'FAILED'} ({len(failures)} failures)")
    sys.exit(1 if failures else 0)


try:
    main()
except SystemExit:
    raise
except Exception:
    import traceback
    traceback.print_exc()
    sys.exit(1)
