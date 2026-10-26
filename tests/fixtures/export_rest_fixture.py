"""Export an armature's rest pose to an .npz fixture for unit tests (run in Blender):

    blender -b --factory-startup --python export_rest_fixture.py -- <character.fbx> <out.npz>
"""

import os
import sys

import bpy
import numpy as np

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "addon"))

from ai_mocap.rig.detect import extract_rest, find_armature  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=os.path.realpath(argv[0]))
arm = next(find_armature(o) for o in bpy.data.objects if find_armature(o))
rig = extract_rest(arm)
np.savez(argv[1], names=np.array(rig.names), parents=rig.parents, rest=rig.rest,
         heads=rig.heads, tails=rig.tails, matrix_world=np.array(arm.matrix_world))
print("FIXTURE", argv[1], len(rig.names))
