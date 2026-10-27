"""Integration test of the installable add-on (Phase 3).

Runs with Blender in background or with the ``bpy`` module from PyPI:

    blender -b --factory-startup --python tests/blender/test_addon.py -- [--engine] [--video clip.mp4]
    python tests/blender/test_addon.py [--engine] [--video clip.mp4]      # pip install bpy==5.1.2

What it does, like a user would:
* enables the add-on, builds a Mixamo character from the real X Bot rest
  pose (tests/fixtures/xbot_rest.npz) with the FBX import transform;
* detects the rig, edits the mapping, saves and loads presets;
* generates animations (from a cached analysis), with every output option;
* switches, restores, pushes to NLA and deletes Actions;
* saves and reopens the file;
* draws every panel and the preferences with a strict fake layout (catches
  wrong property / operator names);
* runs the background task system with real child processes (progress,
  errors, cancel);
* ``--engine``: installs the real engine from the preferences (network,
  ~470 MB), verifies it and runs a capture through the UI operator.
Exit code 0 when all checks pass.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import types

import numpy as np

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "addon"))

import bpy  # noqa: E402
import addon_utils  # noqa: E402
from mathutils import Matrix  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
WITH_ENGINE = "--engine" in argv
VIDEO = argv[argv.index("--video") + 1] if "--video" in argv else None

failures = []


def check(cond, msg):
    print(("PASS  " if cond else "FAIL  ") + msg, flush=True)
    if not cond:
        failures.append(msg)


# --- Scene helpers ----------------------------------------------------------------

def build_xbot():
    """Mixamo X Bot armature from the fixture, with the FBX import transform."""
    data = np.load(os.path.join(ROOT, "tests", "fixtures", "xbot_rest.npz"))
    names = [str(n) for n in data["names"]]
    arm_data = bpy.data.armatures.new("Armature")
    arm = bpy.data.objects.new("Armature", arm_data)
    bpy.context.scene.collection.objects.link(arm)
    arm.scale = (0.01, 0.01, 0.01)
    arm.rotation_euler = (np.pi / 2, 0, 0)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    ebs = []
    for i, name in enumerate(names):
        eb = arm_data.edit_bones.new(name)
        eb.head = data["heads"][i]
        eb.tail = data["tails"][i]
        eb.matrix = Matrix(data["rest"][i].tolist())
        ebs.append(eb)
    for i, p in enumerate(data["parents"]):
        if p >= 0:
            ebs[i].parent = ebs[p]
    bpy.ops.object.mode_set(mode='OBJECT')
    # Pre-existing (Mixamo-style) action that must be preserved.
    act = bpy.data.actions.new("Armature|mixamo.com|Layer0")
    arm.animation_data_create().action = act
    arm.keyframe_insert("location", frame=1)
    return arm


def rest_landmarks(rig, S):
    """33 contract-space landmarks matching the rest pose (same as tests/unit/test_solver.py)."""
    rc = S.capture_to_armature_matrix(rig)
    left, up, fwd = S.canonical_axes(rig)
    pts = {}
    for side, ids in {"L": (11, 13, 15, 19, 17, 23, 25, 27, 31),
                      "R": (12, 14, 16, 20, 18, 24, 26, 28, 32)}.items():
        for j, slot in zip(ids, ("upper_arm", "forearm", "hand", "index1", "pinky1", "thigh",
                                 "shin", "foot", "toe_end")):
            pts[j] = rig.head(f"{slot}.{side}")
    head = rig.head("head")
    pitch = np.radians(S.SolverSettings().head_pitch_offset_deg)
    pts[7], pts[8] = head + 8 * left, head - 8 * left
    pts[0] = head + 10 * (np.cos(pitch) * fwd - np.sin(pitch) * up)
    hip_mid = 0.5 * (pts[23] + pts[24])
    arm = np.array([pts.get(j, hip_mid) for j in range(33)])
    return ((arm - hip_mid) * 0.01) @ rc


def rotate_points(world, ids, center, rot):
    out = world.copy()
    for j in ids:
        out[:, j] = (world[:, j] - center) @ rot.T + center
    return out


def synthetic_result(out_dir, frames=60, fps=30.0):
    """An engine result (contract v1) where the left arm rises and the body walks."""
    from ai_mocap.retarget import solver as S
    from ai_mocap.rig.mapping import auto_map
    data = np.load(os.path.join(ROOT, "tests", "fixtures", "xbot_rest.npz"))
    names = [str(n) for n in data["names"]]
    rig = S.RigRest(names=names, parents=data["parents"], rest=data["rest"], heads=data["heads"],
                  tails=data["tails"], mapping=auto_map(names)[0])
    base = rest_landmarks(rig, S)
    world = np.repeat(base[None], frames, axis=0)
    for f in range(frames):
        a = np.radians(-70.0 * f / (frames - 1))        # raise left arm in the image plane
        rot = np.array([[np.cos(a), 0, -np.sin(a)], [0, 1, 0], [np.sin(a), 0, np.cos(a)]])
        world[f:f + 1] = rotate_points(world[f:f + 1], (13, 15, 17, 19, 21), world[f, 11], rot)
    root = np.zeros((frames, 3))
    root[:, 0] = np.linspace(0, 0.5, frames)
    root[:, 2] = 1.0
    os.makedirs(out_dir, exist_ok=True)
    np.savez_compressed(os.path.join(out_dir, "motion.npz"), world=world.astype(np.float32),
                        root=root.astype(np.float32), confidence=np.ones((frames, 33), np.float32),
                        valid=np.ones(frames, bool))
    meta = {"contract_version": 1, "fps": fps, "frame_count": frames,
            "joint_names": ["j%d" % i for i in range(33)],
            "source": {"path": "synthetic.mp4"}, "settings": {},
            "quality": {"detected_ratio": 1.0, "never_seen_joints": [],
                        "front_back_flipped_frames": 0},
            "timing_s": {"pose": 1.0, "total": 1.2}}
    with open(os.path.join(out_dir, "result.json"), "w") as fh:
        json.dump(meta, fh)
    return out_dir


def fcurves(action, arm):
    from ai_mocap.anim.writer import _channelbag
    slot = arm.animation_data.action_slot if arm.animation_data.action == action else action.slots[0]
    return list(_channelbag(action, slot).fcurves)


# --- Strict fake UI layout ------------------------------------------------------------

VALID_ICONS = {i.identifier for i in
               bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"].enum_items}


class FakeLayout:
    """Accepts every layout call, but validates property and operator names."""

    def __init__(self, errors):
        object.__setattr__(self, "_errors", errors)

    def __setattr__(self, key, value):
        object.__setattr__(self, key, value)

    def _icon(self, kw):
        icon = kw.get("icon")
        if icon and icon not in VALID_ICONS:
            self._errors.append(f"icon {icon!r} does not exist")

    def _child(self, *a, **k):
        return FakeLayout(self._errors)

    row = column = box = split = grid_flow = column_flow = _child

    def prop(self, data, prop, **kw):
        self._icon(kw)
        if data is None or prop not in data.bl_rna.properties:
            self._errors.append(f"prop {prop!r} not on {data!r}")

    def prop_search(self, data, prop, search_data, search_prop, **kw):
        self.prop(data, prop)
        if search_prop not in search_data.bl_rna.properties:
            self._errors.append(f"search {search_prop!r} not on {search_data!r}")

    def operator(self, idname, **kw):
        self._icon(kw)
        mod, _, name = idname.partition(".")
        try:
            getattr(getattr(bpy.ops, mod), name).get_rna_type()
        except Exception:
            self._errors.append(f"operator {idname!r} does not exist")
        return types.SimpleNamespace()

    def label(self, **kw):
        self._icon(kw)

    def progress(self, **kw):
        pass

    def separator(self, **kw):
        pass


def draw_all_panels(label):
    import ai_mocap.ui as ui
    import ai_mocap.common as common
    errors = []
    ctx = types.SimpleNamespace(scene=bpy.context.scene, active_object=bpy.context.active_object,
                                screen=None, preferences=bpy.context.preferences,
                                window_manager=bpy.context.window_manager)
    for cls in ui.classes:
        if hasattr(cls, "poll") and not cls.poll(ctx):
            continue
        panel = types.SimpleNamespace(layout=FakeLayout(errors))
        try:
            cls.draw(panel, ctx)
        except Exception as exc:
            errors.append(f"{cls.__name__}: {type(exc).__name__}: {exc}")
    prefs = common.prefs()
    try:
        class PrefsProxy:  # real preferences, fake layout
            layout = FakeLayout(errors)

            def __getattr__(self, name):
                return getattr(prefs, name)
        type(prefs).draw(PrefsProxy(), ctx)
    except Exception as exc:
        errors.append(f"prefs: {type(exc).__name__}: {exc}")
    check(not errors, f"all panels draw without errors ({label})" + ("" if not errors else f": {errors}"))


# --- Tests --------------------------------------------------------------------

def drive(timeout=600):
    """Pump the task timer by hand (the bpy module has no event loop)."""
    from ai_mocap.core import tasks
    t0 = time.monotonic()
    while tasks.tick():
        if time.monotonic() - t0 > timeout:
            tasks.cancel()
        time.sleep(0.05)
    return tasks.last()


def test_tasks(tmp):
    from ai_mocap.core import tasks
    py = sys.executable if os.path.basename(sys.executable).startswith("python") else shutil.which("python3")
    script = ("import json,sys,time\n"
              "for i in range(5):\n"
              "    print(json.dumps({'type':'progress','done':i+1,'total':5})); sys.stdout.flush(); time.sleep(0.05)\n"
              "print('plain text line'); print(json.dumps({'type':'done'}))\n")
    seen = []

    def worker(ctx):
        events = []

        def on_line(line):
            if line.startswith("{"):
                ev = json.loads(line)
                events.append(ev)
                if ev["type"] == "progress":
                    ctx.progress(stage="test", done=ev["done"], total=ev["total"])
                return True
            return False
        code = ctx.run([py, "-c", script], on_line=on_line)
        return {"code": code, "events": events}

    tasks.start(tasks.Task("fake", worker, lambda t: seen.append(t.state), kind="test", log_dir=tmp))
    check(tasks.busy(), "task runs in background (start returns immediately)")
    try:
        tasks.start(tasks.Task("second", lambda c: None, kind="test", log_dir=tmp))
        check(False, "a second task is refused while one runs")
    except tasks.TaskError:
        check(True, "a second task is refused while one runs")
    task = drive()
    check(task.state == tasks.DONE and task.result["code"] == 0 and len(task.result["events"]) == 6,
          f"child process progress parsed ({task.state}, {task.result})")
    check(seen == [tasks.DONE], "on_finish called once on the main thread")
    with open(task.log_path, encoding="utf-8") as fh:
        check("plain text line" in fh.read(), "non-JSON output goes to the log")

    # Cancel a long-running child.
    def slow(ctx):
        ctx.run([py, "-c", "import time; print('start', flush=True); time.sleep(60)"])
    tasks.start(tasks.Task("slow", slow, kind="capture", log_dir=tmp))
    time.sleep(0.5)
    tasks.tick()
    draw_all_panels("task running")
    t0 = time.monotonic()
    tasks.cancel()
    task = drive()
    check(task.state == tasks.CANCELLED and time.monotonic() - t0 < 5,
          f"cancel kills the child process quickly ({task.state}, {time.monotonic() - t0:.1f}s)")

    def failing(ctx):
        raise tasks.TaskError("mensaje de prueba", "TEST")
    tasks.start(tasks.Task("fail", failing, kind="test", log_dir=tmp))
    task = drive()
    check(task.state == tasks.ERROR and task.error == "mensaje de prueba", "TaskError reported to the UI")
    task.kind = "capture"
    draw_all_panels("last task failed")

    def crashing(ctx):
        return 1 / 0
    tasks.start(tasks.Task("crash", crashing, kind="test", log_dir=tmp))
    task = drive()
    check(task.state == tasks.ERROR and "ZeroDivisionError" in task.error, "crash reported, Blender unaffected")
    tasks.clear_last()


def main():
    from ai_mocap.core import tasks
    tmp = tempfile.mkdtemp(prefix="ai_mocap_test_")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon_utils.enable("ai_mocap", default_set=True, handle_error=None)
    import ai_mocap.common as common
    import ai_mocap.engine_env as E
    from ai_mocap.core import cache, generation
    prefs = common.prefs()
    check(prefs is not None, "add-on enabled with preferences")
    prefs.data_dir = os.path.join(tmp, "data")
    paths = common.paths()
    check(paths.data_dir == os.path.realpath(os.path.join(tmp, "data")), "data folder override")
    scene = bpy.context.scene
    scene.render.fps = 30
    s = scene.ai_mocap
    check(E.engine_state(paths)[0] == "NOT_INSTALLED", "engine reported as not installed")
    draw_all_panels("empty scene")

    test_tasks(tmp)

    # A · Character
    arm = build_xbot()
    original = arm.animation_data.action
    bpy.context.view_layer.objects.active = arm
    check(bpy.ops.ai_mocap.use_active() == {'FINISHED'}, "use active object as character")
    rig = arm.data.ai_mocap
    check(s.target == arm and rig.analyzed and rig.is_mixamo, "Mixamo rig detected")
    check(not rig.missing_required(arm.data), "all required bones mapped")
    check(rig.mapping()["upper_arm.L"] == "mixamorig:LeftArm", "LeftArm mapped to upper_arm.L")
    draw_all_panels("character")

    # Mapping edits and presets
    check(bpy.ops.ai_mocap.preset_save(name="X Bot test") == {'FINISHED'}, "save mapping preset")
    item = next(i for i in rig.slots if i.slot == "forearm.R")
    item.bone = ""
    check(rig.missing_required(arm.data) == ["forearm.R"], "cleared bone reported missing")
    video = os.path.join(tmp, "clip.mp4")
    with open(video, "wb") as fh:
        fh.write(b"\0" * 1024)
    s.video_path = video
    try:
        generation.start_generation(bpy.context)
        check(False, "generate refuses an incomplete mapping")
    except generation.GenerateError as exc:
        check("Antebrazo D" in str(exc), f"generate refuses an incomplete mapping ({exc})")
    from ai_mocap.rig import presets as P
    user = [p for p in P.list_presets(paths.presets) if not p[3]]
    check(len(user) == 1 and user[0][1] == "X Bot test", "user preset listed")
    check(bpy.ops.ai_mocap.preset_load(preset=user[0][0]) == {'FINISHED'}
          and not rig.missing_required(arm.data), "load user preset restores mapping")
    item.bone = ""
    builtin = [p for p in P.list_presets(paths.presets) if p[3]]
    check(bpy.ops.ai_mocap.preset_load(preset=builtin[0][0]) == {'FINISHED'}
          and rig.mapping()["forearm.R"] == "mixamorig:RightForeArm",
          "built-in Mixamo preset resolves the mixamorig: prefix")

    # Engine missing and nothing cached -> clear message
    try:
        generation.start_generation(bpy.context)
        check(False, "generate without engine explains how to install it")
    except generation.GenerateError as exc:
        check("Preferencias" in str(exc), "generate without engine explains how to install it")

    # C · Generate from a cached analysis (as if the AI had run before)
    job = generation.engine_job(scene)
    key = cache.make_key(video, job, E.engine_version(), E.MODELS[s.model_variant]["sha256"])
    synthetic_result(cache.entry_dir(paths.cache, key))
    scene.frame_start, scene.frame_end = 1, 250
    check(bpy.ops.ai_mocap.generate() == {'FINISHED'}, "generate (cache hit) finishes")
    act = arm.animation_data.action
    check(act is not None and act.name == "Mocap_clip" and generation.ACTION_TAG in act.keys(),
          f"new tagged Action assigned ({act.name if act else None})")
    fcs = fcurves(act, arm)
    check(len(fcs) > 60 and all(len(fc.keyframe_points) == 60 for fc in fcs),
          f"one key per frame on {len(fcs)} F-Curves")
    check(scene.frame_start == 1 and scene.frame_end == 60, f"scene range set ({scene.frame_end})")
    check(original.name in bpy.data.actions and original.use_fake_user
          and rig.original_action == original.name, "original Action kept and remembered")
    scene.frame_set(60)
    la = arm.pose.bones["mixamorig:LeftArm"].rotation_quaternion
    check(np.degrees(la.angle) > 40, f"left arm raised at the end ({np.degrees(la.angle):.0f} deg)")
    check(arm.pose.bones["mixamorig:Hips"].location.length > 1.0, "root motion applied")
    rep = s.report_dict()
    check(rep.get("frames") == 60 and rep.get("detected") == 100.0, "report stored for the Output panel")
    draw_all_panels("after generation")

    # Output options via «Regenerar sin IA»
    s.key_step = 3
    s.root_mode = 'VERTICAL'
    s.frame_start_mode = 'CUSTOM'
    s.frame_start = 101
    s.action_name = "Paso"
    check(bpy.ops.ai_mocap.regenerate() == {'FINISHED'}, "regenerate without AI")
    act2 = arm.animation_data.action
    fcs = fcurves(act2, arm)
    n = len(fcs[0].keyframe_points)
    check(act2.name == "Paso" and n == 21, f"key reduction: 21 keys every 3 frames ({n})")
    check(fcs[0].keyframe_points[0].interpolation == 'BEZIER' and fcs[0].keyframe_points[0].co.x == 101,
          "reduced keys are Bezier and start at the custom frame")
    check("Mocap_clip" in bpy.data.actions, "previous generated Action kept")
    hips = arm.pose.bones["mixamorig:Hips"]
    scene.frame_set(101)
    p0 = arm.matrix_world @ hips.head
    scene.frame_set(160)
    p1 = arm.matrix_world @ hips.head
    check(abs(p1.x - p0.x) + abs(p1.y - p0.y) < 0.01,
          f"vertical-only root mode keeps the character in place ({(p1 - p0).length:.3f} m)")

    s.key_step = 1
    s.push_to_nla = True
    s.action_name = "NLA"
    bpy.ops.ai_mocap.regenerate()
    ad = arm.animation_data
    check(ad.action is None and any(st.action and st.action.name == "NLA"
                                    for t in ad.nla_tracks for st in t.strips),
          "push to NLA option creates a strip")
    s.push_to_nla = False

    # F · Controls
    check(bpy.ops.ai_mocap.assign_action(action="Mocap_clip") == {'FINISHED'}
          and arm.animation_data.action.name == "Mocap_clip", "switch between generated Actions")
    bpy.ops.ai_mocap.toggle_rest()
    check(arm.data.pose_position == 'REST', "toggle rest pose")
    bpy.ops.ai_mocap.toggle_rest()
    check(bpy.ops.ai_mocap.restore_original() == {'FINISHED'}
          and arm.animation_data.action == original, "restore original Action")
    bpy.ops.ai_mocap.delete_action(action="Paso")
    check("Paso" not in bpy.data.actions, "delete generated Action")
    bpy.ops.ai_mocap.delete_action(action=original.name)
    check(original.name in bpy.data.actions, "delete refuses non-generated Actions")
    check(len(generation.generated_actions()) == 2, "generated Actions listed")
    draw_all_panels("controls")

    # Persistence
    blend = os.path.join(tmp, "addon_test.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    bpy.ops.wm.open_mainfile(filepath=blend)
    arm = bpy.data.objects["Armature"]
    s = bpy.context.scene.ai_mocap
    check(arm.data.ai_mocap.analyzed and arm.data.ai_mocap.mapping()["hips"] == "mixamorig:Hips",
          "mapping saved in the .blend")
    check(s.target == arm and s.video_path == video and s.root_mode == 'VERTICAL',
          "scene settings saved in the .blend")
    check({"Mocap_clip", "NLA"} <= set(bpy.data.actions.keys()), "generated Actions saved")
    meta = generation.action_meta(bpy.data.actions["Mocap_clip"])
    check(meta.get("video") == "clip.mp4" and "engine" in meta, "Action metadata saved")
    draw_all_panels("reopened")

    if WITH_ENGINE:
        test_engine(tmp, video_path=VIDEO)

    tasks.shutdown()
    addon_utils.disable("ai_mocap")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"RESULT {'OK' if not failures else 'FAILED'} ({len(failures)} failures)")
    sys.exit(1 if failures else 0)


def test_engine(tmp, video_path=None):
    """Real install from the preferences + capture through the UI."""
    import ai_mocap.common as common
    import ai_mocap.engine_env as E
    from ai_mocap.core import tasks
    common.online = lambda: True       # the bpy module has no «Allow Online Access» preference
    paths = common.paths()
    t0 = time.monotonic()
    check(bpy.ops.ai_mocap.install_engine() == {'FINISHED'}, "install engine started")
    task = drive(timeout=1800)
    check(task.state == tasks.DONE, f"engine installed in {time.monotonic() - t0:.0f}s "
                                    f"({task.state}: {task.error[:300]})")
    E.invalidate_status()
    check(E.engine_state(paths)[0] == "READY", f"engine ready: {E.engine_state(paths)[1]}")
    check(paths.model_ok("full"), "default model downloaded and verified")
    print("venv size:", E.human_size(E.folder_size(paths.venv)))
    bpy.ops.ai_mocap.verify_engine()
    check(drive().state == tasks.DONE, "verify engine")
    draw_all_panels("engine ready")

    s = bpy.context.scene.ai_mocap
    arm = bpy.data.objects["Armature"]
    if video_path is None:
        return
    s.video_path = os.path.realpath(video_path)
    s.use_trim = False
    s.root_mode = 'FULL'
    s.frame_start_mode = 'SCENE'
    s.action_name = ""
    check(bpy.ops.ai_mocap.probe_video() == {'FINISHED'}, "probe video started")
    task = drive()
    info = s.video_info_dict()
    check(task.state == tasks.DONE and info.get("fps", 0) > 0, f"probe video ({info})")
    before = len(bpy.data.actions)
    t0 = time.monotonic()
    check(bpy.ops.ai_mocap.generate() == {'FINISHED'} and tasks.busy(), "capture started in background")
    task = drive()
    dt = time.monotonic() - t0
    check(task.state == tasks.DONE, f"capture finished in {dt:.1f}s ({task.state}: {task.error})")
    check(len(bpy.data.actions) == before + 1 and arm.animation_data.action is not None,
          f"capture created a new Action: {task.finish_note}")
    print("REPORT", s.last_report)
    # Second run hits the cache: no AI
    t0 = time.monotonic()
    bpy.ops.ai_mocap.generate()
    check(not tasks.busy() and time.monotonic() - t0 < 5, f"second generation reuses the cache "
                                                           f"({time.monotonic() - t0:.2f}s)")
    # Cancel mid-capture leaves the character untouched
    s.use_cache = False
    current = arm.animation_data.action
    n = len(bpy.data.actions)
    bpy.ops.ai_mocap.generate()
    time.sleep(2.0)
    tasks.cancel()
    task = drive()
    check(task.state == tasks.CANCELLED and arm.animation_data.action == current
          and len(bpy.data.actions) == n, "cancelled capture leaves the character untouched")
    s.use_cache = True


try:
    main()
except SystemExit:
    raise
except Exception:
    import traceback
    traceback.print_exc()
    sys.exit(1)
