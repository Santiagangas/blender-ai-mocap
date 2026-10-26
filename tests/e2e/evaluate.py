"""Closed-loop test, step 2 (run inside Blender):

    blender -b --factory-startup --python evaluate.py -- <gt.blend> <engine_out_dir> <out_dir> [--render]

Duplicates the ground-truth character, applies the engine result through the
real add-on code path (contract -> retarget -> Action), then compares both
armatures frame by frame using Blender's own pose evaluation:

* direction error: angle between GT and captured bone Y axes (swing)
* rotation error: full geodesic angle between bone orientations (incl. twist)
* root error: distance between hip positions (metres)

Also saves ``result.blend`` for the save/reopen check and, with --render,
a side-by-side contact sheet (GT left, capture right).
"""

import json
import os
import sys

import bpy
import numpy as np

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "addon"))

from ai_mocap.core.apply import apply_motion  # noqa: E402
from ai_mocap.retarget.solver import SolverSettings  # noqa: E402
from ai_mocap.rig.mapping import auto_map  # noqa: E402

EVAL_SLOTS = ("hips", "spine2", "head", "upper_arm.L", "forearm.L", "hand.L",
              "upper_arm.R", "forearm.R", "hand.R", "thigh.L", "shin.L", "foot.L",
              "thigh.R", "shin.R", "foot.R")
OFFSET_X = 1.1


def duplicate_character(src_arm):
    arm = src_arm.copy()
    arm.name = "Mocap_Armature"
    arm.animation_data_clear()
    arm.location.x += OFFSET_X
    bpy.context.scene.collection.objects.link(arm)
    for child in src_arm.children:
        c = child.copy()
        c.parent = arm
        for mod in c.modifiers:
            if mod.type == 'ARMATURE':
                mod.object = arm
        bpy.context.scene.collection.objects.link(c)
    return arm


def bone_rot(pb):
    m = np.array(pb.matrix)[:3, :3]
    return m / np.linalg.norm(m, axis=0, keepdims=True)


def geodesic(a, b):
    return np.degrees(np.arccos(np.clip((np.trace(a.T @ b) - 1) / 2, -1, 1)))


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    gt_blend, engine_dir, out_dir = (os.path.realpath(a) for a in argv[:3])
    render = "--render" in argv
    # --set name=value overrides SolverSettings fields (numbers only), for tuning.
    overrides = {a.split("=")[0]: float(a.split("=")[1])
                 for a, prev in zip(argv[1:], argv) if prev == "--set"}
    os.makedirs(out_dir, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=gt_blend)
    scene = bpy.context.scene
    gt = bpy.data.objects["GT_Armature"]
    mc = duplicate_character(gt)

    action, report = apply_motion(mc, engine_dir, frame_start=1, action_name="Mocap_closed_loop",
                                  settings=SolverSettings(**overrides), scene_fps=scene.render.fps)
    mapping, _ = auto_map([b.name for b in gt.data.bones])
    scale = float(np.mean(np.array(gt.matrix_world.to_scale())))

    frames = range(scene.frame_start, int(report["frame_end"]) + 1)
    dir_err = {s: [] for s in EVAL_SLOTS}
    rot_err = {s: [] for s in EVAL_SLOTS}
    rest_dir_err = {s: [] for s in EVAL_SLOTS}
    root_err = []
    for f in frames:
        scene.frame_set(f)
        for s in EVAL_SLOTS:
            bname = mapping.get(s)
            if bname is None:
                continue
            a, b = gt.pose.bones[bname], mc.pose.bones[bname]
            ra, rb = bone_rot(a), bone_rot(b)
            rest = np.array(a.bone.matrix_local)[:3, :3]
            dir_err[s].append(np.degrees(np.arccos(np.clip(ra[:, 1] @ rb[:, 1], -1, 1))))
            rot_err[s].append(geodesic(ra, rb))
            rest_dir_err[s].append(np.degrees(np.arccos(np.clip(ra[:, 1] @ (rest[:, 1] / np.linalg.norm(rest[:, 1])), -1, 1))))
        hb = mapping["hips"]
        root_err.append(np.linalg.norm(np.array(gt.pose.bones[hb].head) - np.array(mc.pose.bones[hb].head)) * scale)

    def stats(v):
        v = np.asarray(v)
        return {"mean": round(float(v.mean()), 2), "median": round(float(np.median(v)), 2),
                "p95": round(float(np.percentile(v, 95)), 2), "max": round(float(v.max()), 2)}

    metrics = {
        "engine_dir": engine_dir,
        "report": report,
        "direction_error_deg": {s: stats(v) for s, v in dir_err.items() if v},
        "rotation_error_deg": {s: stats(v) for s, v in rot_err.items() if v},
        "baseline_rest_pose_direction_error_deg": {s: stats(v) for s, v in rest_dir_err.items() if v},
        "root_error_m": stats(root_err),
    }
    all_dir = np.concatenate([v for v in dir_err.values() if v])
    metrics["overall_direction_error_deg"] = stats(all_dir)
    metrics["overall_rest_baseline_deg"] = stats(np.concatenate([v for v in rest_dir_err.values() if v]))
    np.savez(os.path.join(out_dir, "per_frame.npz"), slots=np.array(EVAL_SLOTS),
             direction=np.array([dir_err[s] for s in EVAL_SLOTS]),
             rotation=np.array([rot_err[s] for s in EVAL_SLOTS]), root=np.array(root_err))
    with open(os.path.join(out_dir, "metrics.json"), "w") as fh:
        json.dump(metrics, fh, indent=1)

    scene.camera.location.x += OFFSET_X / 2
    scene.camera.location.y -= 0.6
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "result.blend"))

    if render:
        scene.render.image_settings.media_type = 'IMAGE'
        scene.render.image_settings.file_format = 'PNG'
        scene.render.resolution_x, scene.render.resolution_y = 960, 720
        for f in (1, 31, 61, 96, 126, 151):
            scene.frame_set(f)
            scene.render.filepath = os.path.join(out_dir, f"cmp_{f:03d}.png")
            bpy.ops.render.render(write_still=True)

    print("EVAL_OVERALL", json.dumps(metrics["overall_direction_error_deg"]),
          "baseline", json.dumps(metrics["overall_rest_baseline_deg"]),
          "root", json.dumps(metrics["root_error_m"]))
    for s in EVAL_SLOTS:
        if s in metrics["direction_error_deg"]:
            print(f"EVAL {s:12s} dir {metrics['direction_error_deg'][s]}  rot {metrics['rotation_error_deg'][s]}")
    print("EVAL_REPORT", json.dumps(report))


main()
