"""Phase 2 prototype, Blender side (run inside Blender):

    blender -b --factory-startup --python tools/apply_to_fbx.py -- <character.fbx> <engine_out_dir> <out.blend> [--fps 30]

Imports the character, applies an engine result as a new Action through the
add-on code path, sets the scene frame range and saves a .blend.
"""

import os
import sys

import bpy

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "addon"))

from ai_mocap.core.apply import apply_motion  # noqa: E402
from ai_mocap.rig.detect import find_armature  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
fbx, engine_dir, out_blend = (os.path.realpath(a) for a in argv[:3])
fps = int(argv[argv.index("--fps") + 1]) if "--fps" in argv else 30

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=fbx)
arm = next(find_armature(o) for o in bpy.data.objects if find_armature(o))
scene = bpy.context.scene
scene.render.fps = fps
name = "Mocap_" + os.path.splitext(os.path.basename(fbx))[0]
action, report = apply_motion(arm, engine_dir, frame_start=1, action_name=name, scene_fps=fps)
scene.frame_start, scene.frame_end = 1, int(report["frame_end"])
bpy.ops.wm.save_as_mainfile(filepath=out_blend)
print("APPLIED", action.name, report)
