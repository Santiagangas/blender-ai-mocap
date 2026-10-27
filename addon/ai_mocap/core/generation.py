"""Generate an animation: settings -> (cached) engine result -> new Action.

Runs on the main thread. The AI part is delegated to a background task
(``workers.capture``); everything that touches Blender data happens here.
"""

import json
import math
import os
import time

import bpy

from .. import common
from .. import engine_env as E
from ..retarget.solver import SolverSettings
from ..rig.detect import find_armature
from ..rig.mapping import auto_map
from . import cache, tasks, workers
from .apply import apply_motion

PREVIEW_SECONDS = 3.0
ACTION_TAG = "ai_mocap"


class GenerateError(Exception):
    pass


def resolve_target(context):
    """Armature to animate: the panel's target, else the active object's armature."""
    s = context.scene.ai_mocap
    if s.target is not None and s.target.name in context.scene.objects:
        return s.target
    return find_armature(context.active_object)


def ensure_mapping(arm):
    rig = arm.data.ai_mocap
    if not rig.analyzed or not rig.slots:
        mapping, report = auto_map([b.name for b in arm.data.bones])
        rig.set_mapping(mapping)
        rig.is_mixamo = report["is_mixamo"]
    missing = rig.missing_required(arm.data)
    if missing:
        from ..properties import SLOT_LABELS
        raise GenerateError("Faltan huesos obligatorios en el mapeo: "
                            + ", ".join(SLOT_LABELS.get(m, m) for m in missing)
                            + ". Asígnalos en el panel Personaje → Mapeo de huesos.")
    return rig.mapping()


def video_path(s):
    path = bpy.path.abspath(s.video_path) if s.video_path else ""
    return os.path.realpath(path) if path else ""


def engine_job(scene, preview=False):
    """Engine settings (everything that changes the AI result)."""
    s = scene.ai_mocap
    if s.fps_mode == 'SCENE':
        target_fps = round(common.scene_fps(scene), 4)
    elif s.fps_mode == 'CUSTOM':
        target_fps = float(s.custom_fps)
    else:
        target_fps = None
    start = float(s.trim_start) if s.use_trim else 0.0
    end = float(s.trim_end) if s.use_trim else None
    if end is not None and end <= start:
        raise GenerateError("El fin del recorte debe ser posterior al inicio.")
    if preview:
        end = start + PREVIEW_SECONDS if end is None else min(end, start + PREVIEW_SECONDS)
    return {
        "backend": "mediapipe",
        "start_s": round(start, 4),
        "end_s": None if end is None else round(end, 4),
        "target_fps": target_fps,
        "rotation": int(s.rotation),
        "mirror": bool(s.mirror),
        "min_confidence": round(float(s.min_confidence), 4),
        "max_gap_s": round(float(s.max_gap), 4),
        "smoothing": round(float(s.smoothing), 4),
        "hfov_deg": round(float(s.hfov), 3),
        "assume_upright": bool(s.assume_upright),
        "initial_facing": "camera" if s.initial_facing == 'CAMERA' else "auto",
    }


def output_snapshot(scene, video, preview=False):
    """Retarget + output settings, captured when the user presses Generate."""
    s = scene.ai_mocap
    if s.frame_start_mode == 'SCENE':
        frame_start = scene.frame_start
    elif s.frame_start_mode == 'CURRENT':
        frame_start = scene.frame_current
    else:
        frame_start = s.frame_start
    name = s.action_name.strip() or "Mocap_" + os.path.splitext(os.path.basename(video))[0]
    if preview:
        name += "_preview"
    return {
        "frame_start": int(frame_start),
        "action_name": name,
        "set_scene_range": bool(s.set_scene_range),
        "key_step": int(s.key_step),
        "interpolation": None if s.interpolation == 'AUTO' else s.interpolation,
        "push_to_nla": bool(s.push_to_nla),
        "solver": {
            "root_mode": s.root_mode,
            "root_scale": float(s.root_scale),
            "facing_offset_deg": float(s.facing_offset),
            "hand_weight": float(s.hand_weight),
            "neck_share": float(s.neck_share),
            "head_pitch_offset_deg": float(s.head_pitch_offset),
        },
    }


def generated_actions():
    return [a for a in bpy.data.actions if ACTION_TAG in a.keys()]


def action_meta(action):
    try:
        return json.loads(action[ACTION_TAG])
    except (KeyError, ValueError, TypeError):
        return {}


def apply_result(scene, arm, result_dir, out, video="", engine_params=None):
    """Create the Action from an engine result and apply output options."""
    rig = arm.data.ai_mocap
    mapping = ensure_mapping(arm)
    ad = arm.animation_data
    previous = ad.action if ad else None
    if previous is not None and ACTION_TAG not in previous.keys() and not rig.original_action:
        rig.original_action = previous.name
        previous.use_fake_user = True   # never lose the user's own animation

    settings = SolverSettings(**out["solver"])
    action, report = apply_motion(arm, result_dir, frame_start=out["frame_start"],
                                  action_name=out["action_name"], settings=settings,
                                  mapping=mapping, scene_fps=common.scene_fps(scene),
                                  key_step=out["key_step"], interpolation=out["interpolation"])
    action[ACTION_TAG] = json.dumps({
        "video": os.path.basename(video), "video_path": video,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "engine": engine_params or {}, "output": out, "result_dir": result_dir,
    }, ensure_ascii=False)

    frame_end = int(math.ceil(report["frame_end"]))
    if out["set_scene_range"]:
        scene.frame_start = out["frame_start"]
        scene.frame_end = max(frame_end, out["frame_start"])
    if out["push_to_nla"]:
        push_to_nla(arm, action)
    scene.frame_set(scene.frame_current)

    s = scene.ai_mocap
    s.last_result_dir = result_dir
    q = report.get("quality", {})
    s.last_report = json.dumps({
        "action": action.name, "armature": arm.name,
        "frames": report["frames"], "keys": report["keys_per_curve"],
        "frame_start": out["frame_start"], "frame_end": frame_end,
        "bones": report["keyed_bones"], "fps": report["fps"],
        "detected": round(100 * report["detected_ratio"], 1),
        "never_seen": q.get("never_seen_joints", []),
        "flipped": q.get("front_back_flipped_frames", 0),
        "engine_s": report["timing_s"]["engine"].get("total"),
        "solve_s": report["timing_s"]["solve"], "write_s": report["timing_s"]["write"],
    })
    return action, report


def push_to_nla(arm, action):
    ad = arm.animation_data or arm.animation_data_create()
    track = ad.nla_tracks.new()
    track.name = action.name
    start = int(action.frame_range[0])
    strip = track.strips.new(action.name, start, action)
    if hasattr(strip, "action_slot") and ad.action_slot is not None and ad.action == action:
        try:
            strip.action_slot = ad.action_slot
        except (AttributeError, TypeError, RuntimeError):
            pass
    if ad.action == action:
        ad.action = None
    return strip


def assign_action(arm, action):
    ad = arm.animation_data or arm.animation_data_create()
    ad.action = action
    if hasattr(ad, "action_slot") and ad.action_slot is None and len(action.slots):
        ad.action_slot = action.slots[0]


def start_generation(context, preview=False):
    """Validate, then either apply a cached result or start the AI task.

    Returns ("APPLIED", action, report) or ("STARTED", task, None).
    """
    scene = context.scene
    s = scene.ai_mocap
    arm = resolve_target(context)
    if arm is None:
        raise GenerateError("Elige el personaje (armature) en el panel Personaje.")
    if s.target is None:
        s.target = arm
    ensure_mapping(arm)
    video = video_path(s)
    if not video or not os.path.isfile(video):
        raise GenerateError("Elige un archivo de vídeo válido en el panel Vídeo.")
    if tasks.busy():
        raise GenerateError("Ya hay una tarea en curso; espera o cancélala.")

    job = engine_job(scene, preview)
    out = output_snapshot(scene, video, preview)
    paths = common.paths(context)
    variant = s.model_variant
    key = cache.make_key(video, job, E.engine_version(), E.MODELS[variant]["sha256"])
    hit = cache.lookup(paths.cache, key) if s.use_cache else None
    if hit:
        action, report = apply_result(scene, arm, hit, out, video, job)
        return "APPLIED", action, report

    state, detail = E.engine_state(paths)
    if state != "READY":
        raise GenerateError("El motor de captura no está listo (" + detail + "). Instálalo en "
                            "Editar → Preferencias → Complementos → AI Mocap.")
    cache.purge_work_dirs(paths.cache)
    work = cache.new_work_dir(paths.cache)
    full_job = dict(job, video=video, out_dir=work)
    online = common.online()
    scene_name, arm_name = scene.name, arm.name

    def worker(ctx):
        return workers.capture(ctx, paths, full_job, variant, online)

    def on_finish(task):
        if task.state != tasks.DONE:
            cache.discard(work)
            return
        final = cache.store(paths.cache, key, work)
        sc = bpy.data.scenes.get(scene_name)
        ob = bpy.data.objects.get(arm_name)
        if sc is None or ob is None or ob.type != 'ARMATURE':
            raise tasks.TaskError("El personaje o la escena ya no existen; el análisis quedó "
                                  "guardado en caché y se puede aplicar con «Regenerar».")
        sc.ai_mocap.last_result_dir = final
        try:
            action, report = apply_result(sc, ob, final, out, video, job)
        except Exception as exc:  # mapping / contract / retarget problems
            raise tasks.TaskError(f"El vídeo se analizó, pero no se pudo crear la animación: {exc}")
        task.finish_note = describe(report, action)
        try:
            bpy.ops.ed.undo_push(message="AI Mocap: generar animación")
        except Exception:
            pass

    title = "Vista previa" if preview else "Capturando movimiento"
    task = tasks.Task(title, worker, on_finish, kind="capture", log_dir=paths.logs)
    tasks.start(task)
    return "STARTED", task, None


def regenerate(context):
    """New Action from the last analysis, with the current retarget/output settings."""
    scene = context.scene
    s = scene.ai_mocap
    arm = resolve_target(context)
    if arm is None:
        raise GenerateError("Elige el personaje (armature) en el panel Personaje.")
    if not cache.is_complete(s.last_result_dir):
        raise GenerateError("No hay ningún análisis anterior disponible. Usa «Generar animación».")
    meta = {}
    try:
        with open(os.path.join(s.last_result_dir, "result.json"), "r", encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, ValueError):
        pass
    video = meta.get("source", {}).get("path", "") or video_path(s)
    out = output_snapshot(scene, video or "video")
    return apply_result(scene, arm, s.last_result_dir, out, video, meta.get("settings"))


def describe(report, action):
    return (f"Action «{action.name}»: {report['keyed_bones']} huesos, "
            f"{report['frames']} fotogramas, persona detectada en el "
            f"{100 * report['detected_ratio']:.0f} %")
