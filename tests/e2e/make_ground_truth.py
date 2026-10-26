"""Closed-loop test, step 1 (run inside Blender):

    blender -b --factory-startup --python make_ground_truth.py -- <character.fbx> <out_dir>

Animates the character with a KNOWN motion (arms, elbows, torso twist/bend,
head, squat, leg lift, sideways step), saves it as ``gt.blend`` and renders
a front-camera video ``gt.mp4``. The mocap pipeline is later run on that
video and its result compared against this ground truth.
"""

import math
import os
import sys

import bpy
import numpy as np

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "addon"))

from ai_mocap.anim.writer import write_action  # noqa: E402
from ai_mocap.retarget import rotations as R  # noqa: E402
from ai_mocap.retarget import solver  # noqa: E402
from ai_mocap.rig.detect import extract_rest, find_armature  # noqa: E402

FPS = 30
FRAMES = 180
CAMERA_LENS_MM = 35.0
SENSOR_MM = 36.0


def rot(axis, deg):
    return R.axis_angle_matrix(np.array(axis, dtype=float), np.radians(deg))


I3 = np.eye(3)
X, Y, Z = (1, 0, 0), (0, 1, 0), (0, 0, 1)

# Pose keys in contract space (subject facing -Y, +X = subject's left, +Z up).
# Angles: elbows/knees flex (deg), ankles dorsiflex (deg). root in metres.
BASE = dict(pelvis=I3, torso=I3, head=I3, arm_L=I3, arm_R=I3, elbow_L=0.0, elbow_R=0.0,
            hip_L=I3, hip_R=I3, knee_L=0.0, knee_R=0.0, ankle_L=0.0, ankle_R=0.0,
            root=(0.0, 0.0, 0.0))
KEYS = [
    (0, dict(arm_L=rot(Y, 70), arm_R=rot(Y, -70), elbow_L=15, elbow_R=15)),
    (30, dict(arm_L=rot(Y, -50), arm_R=rot(Y, 50), elbow_L=80, elbow_R=80, head=rot(Z, 25))),
    (60, dict(arm_L=rot(Z, -90), arm_R=rot(Z, 90), elbow_L=20, elbow_R=20,
              torso=rot(Z, 30), head=rot(Z, -30))),
    (95, dict(arm_L=rot(Z, -80), arm_R=rot(Z, 80), elbow_L=10, elbow_R=10, torso=rot(X, 30),
              hip_L=rot(X, -80), hip_R=rot(X, -80), knee_L=100, knee_R=100,
              ankle_L=-20, ankle_R=-20, root=(0.0, 0.28, -0.39))),
    (125, dict(pelvis=rot(Z, 25), torso=rot(Y, 15), hip_L=rot(X, -70), knee_L=80)),
    (150, dict(arm_L=rot(Y, 60), arm_R=rot(Y, -60), head=rot(X, 20), root=(0.35, 0.0, 0.0))),
    (179, dict(arm_L=rot(Y, 70), arm_R=rot(Y, -70), elbow_L=15, elbow_R=15, root=(0.35, 0.0, 0.0))),
]


def pose_at(frame):
    keys = [(f, {**BASE, **p}) for f, p in KEYS]
    for (fa, a), (fb, b) in zip(keys, keys[1:]):
        if fa <= frame <= fb:
            s = (frame - fa) / (fb - fa)
            s = s * s * (3 - 2 * s)  # smoothstep easing
            out = {}
            for k in BASE:
                va, vb = a[k], b[k]
                if isinstance(va, np.ndarray):
                    out[k] = va @ R.fraction(va.T @ vb, s)
                else:
                    out[k] = (1 - s) * np.asarray(va, dtype=float) + s * np.asarray(vb, dtype=float)
            return out
    return keys[-1][1]


def ground_truth_deltas(rig):
    rc = solver.capture_to_armature_matrix(rig)
    to_arm = lambda m: rc @ m @ rc.T  # noqa: E731
    spines = [s for s in ("spine", "spine1", "spine2") if rig.index(s) is not None]
    per_frame = []
    roots = []
    for f in range(FRAMES):
        p = pose_at(f)
        d = {}
        hips = to_arm(p["pelvis"])
        torso = to_arm(p["torso"])
        d["hips"] = hips
        for i, s in enumerate(spines):
            d[s] = hips @ R.fraction(torso, (i + 1) / len(spines))
        chest = hips @ torso
        head = to_arm(p["head"])
        d["neck"] = chest @ R.fraction(head, 0.5)
        d["head"] = chest @ head
        for side, flex_axis in (("L", (0, 0, -1)), ("R", (0, 0, 1))):
            upper = chest @ to_arm(p[f"arm_{side}"])
            fore = upper @ to_arm(rot(flex_axis, p[f"elbow_{side}"]))
            d[f"upper_arm.{side}"], d[f"forearm.{side}"], d[f"hand.{side}"] = upper, fore, fore
            thigh = hips @ to_arm(p[f"hip_{side}"])
            shin = thigh @ to_arm(rot(X, p[f"knee_{side}"]))
            d[f"thigh.{side}"], d[f"shin.{side}"] = thigh, shin
            d[f"foot.{side}"] = shin @ to_arm(rot(X, p[f"ankle_{side}"]))
        per_frame.append(d)
        roots.append(p["root"])
    deltas = {k: np.stack([d[k] for d in per_frame]) for k in per_frame[0]}
    return deltas, np.array(roots), rc


def build_scene(arm, out_dir):
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start, scene.frame_end = 1, FRAMES
    try:
        scene.render.engine = 'BLENDER_WORKBENCH'
    except TypeError:
        scene.render.engine = 'BLENDER_EEVEE'
    shading = scene.display.shading
    shading.light = 'STUDIO'
    shading.color_type = 'MATERIAL'
    shading.show_shadows = True
    shading.show_cavity = True
    world = bpy.data.worlds.new("GT_World")
    world.color = (0.55, 0.58, 0.62)
    scene.world = world

    bpy.ops.mesh.primitive_plane_add(size=30, location=(0, 0, 0))
    floor = bpy.context.active_object
    mat = bpy.data.materials.new("Floor")
    mat.diffuse_color = (0.25, 0.26, 0.28, 1.0)
    floor.data.materials.append(mat)

    cam_data = bpy.data.cameras.new("GT_Camera")
    cam_data.lens, cam_data.sensor_width, cam_data.sensor_fit = CAMERA_LENS_MM, SENSOR_MM, 'HORIZONTAL'
    cam = bpy.data.objects.new("GT_Camera", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0.0, -2.9, 0.95)
    cam.rotation_euler = (math.radians(90), 0.0, 0.0)
    scene.camera = cam

    r = scene.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = 720, 960, 100
    ims = r.image_settings
    if hasattr(ims, "media_type"):
        ims.media_type = 'VIDEO'
    ims.file_format = 'FFMPEG'
    r.ffmpeg.format = 'MPEG4'
    r.ffmpeg.codec = 'H264'
    r.ffmpeg.constant_rate_factor = 'HIGH'
    r.filepath = os.path.join(out_dir, "gt.mp4")
    hfov = math.degrees(2 * math.atan(SENSOR_MM / (2 * CAMERA_LENS_MM)))
    return hfov


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    fbx, out_dir = os.path.realpath(argv[0]), os.path.realpath(argv[1])
    os.makedirs(out_dir, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=fbx)
    arm = next(find_armature(o) for o in bpy.data.objects if find_armature(o))
    arm.name = "GT_Armature"
    rig = extract_rest(arm)

    deltas, roots, rc = ground_truth_deltas(rig)
    quats = solver.deltas_to_quaternions(rig, deltas, FRAMES)
    hips_i = rig.index("hips")
    arm_units_per_m = 1.0 / float(np.mean(np.array(arm.matrix_world.to_scale())))
    root_target = (arm_units_per_m * roots) @ rc.T
    result = solver.SolveResult(quaternions=quats, root_bone=rig.names[hips_i],
                                root_location=root_target @ rig.rot(hips_i))
    write_action(arm, result, 1, "GT_closed_loop")

    hfov = build_scene(arm, out_dir)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "gt.blend"))
    bpy.ops.render.render(animation=True)
    with open(os.path.join(out_dir, "gt_camera.txt"), "w") as fh:
        fh.write(f"hfov_deg={hfov:.4f}\n")
    print(f"GT_DONE hfov={hfov:.2f} video={bpy.context.scene.render.filepath}")


main()
