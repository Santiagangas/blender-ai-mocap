"""Engine result -> retarget -> Blender Action."""

import time

import numpy as np

from ..retarget.solver import SolveResult, SolverSettings, solve
from ..rig.detect import extract_rest
from ..rig.mapping import auto_map, REQUIRED
from .contract import load_motion


class RetargetError(Exception):
    pass


def sample_indices(frame_count, key_step):
    """Indices of the samples that get a keyframe (always keeps the last one)."""
    key_step = max(1, int(key_step))
    idx = np.arange(0, frame_count, key_step)
    if idx[-1] != frame_count - 1:
        idx = np.append(idx, frame_count - 1)
    return idx


def _subsample(result, idx):
    out = SolveResult(diagnostics=result.diagnostics)
    out.quaternions = {k: v[idx] for k, v in result.quaternions.items()}
    out.root_bone = result.root_bone
    out.root_location = None if result.root_location is None else result.root_location[idx]
    out.scale_factor = getattr(result, "scale_factor", 1.0)
    return out


def apply_motion(arm_obj, motion_dir, frame_start=1, action_name="Mocap",
                 settings=None, mapping=None, scene_fps=None, key_step=1,
                 interpolation=None, assign=True):
    """Create a new Action on ``arm_obj`` from an engine result directory.

    ``key_step`` > 1 keeps one keyframe every N samples (Bezier by default,
    to stay smooth between keys). Returns (action, report dict).
    """
    from ..anim.writer import write_action  # needs bpy; keep this module importable without it
    t0 = time.perf_counter()
    motion = load_motion(motion_dir)
    names = [b.name for b in arm_obj.data.bones]
    if mapping is None:
        mapping, map_report = auto_map(names)
    else:
        mapping = {s: b for s, b in mapping.items() if b in names}
        map_report = {"missing_required": [s for s in REQUIRED if s not in mapping]}
    if map_report["missing_required"]:
        raise RetargetError("Faltan huesos obligatorios en el mapeo: "
                            + ", ".join(map_report["missing_required"]))
    rig = extract_rest(arm_obj, mapping)
    result = solve(rig, motion.world, motion.root, settings or SolverSettings())
    t_solve = time.perf_counter() - t0

    step = (scene_fps / motion.fps) if scene_fps else 1.0
    idx = sample_indices(motion.frame_count, key_step)
    frames = frame_start + idx.astype(np.float64) * step
    if interpolation is None:
        interpolation = 'LINEAR' if key_step <= 1 else 'BEZIER'
    action = write_action(arm_obj, _subsample(result, idx) if key_step > 1 else result,
                          frame_start, action_name, frames=frames,
                          interpolation=interpolation, assign=assign)
    report = {
        "frames": motion.frame_count,
        "keys_per_curve": int(len(idx)),
        "keyed_bones": len(result.quaternions),
        "frame_start": frame_start,
        "frame_end": float(frames[-1]),
        "fps": motion.fps,
        "detected_ratio": motion.meta["quality"]["detected_ratio"],
        "quality": motion.meta.get("quality", {}),
        "scale_factor": result.scale_factor,
        "diagnostics": result.diagnostics,
        "timing_s": {"engine": motion.meta.get("timing_s", {}),
                     "solve": round(t_solve, 3),
                     "write": round(time.perf_counter() - t0 - t_solve, 3)},
    }
    return action, report
