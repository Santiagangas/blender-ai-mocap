"""Engine result -> retarget -> Blender Action."""

import time

from ..anim.writer import write_action
from ..retarget.solver import SolverSettings, solve
from ..rig.detect import extract_rest
from ..rig.mapping import auto_map, REQUIRED
from .contract import load_motion


class RetargetError(Exception):
    pass


def apply_motion(arm_obj, motion_dir, frame_start=1, action_name="Mocap",
                 settings=None, mapping=None, scene_fps=None):
    """Create a new Action on ``arm_obj`` from an engine result directory.

    Returns (action, report dict).
    """
    t0 = time.perf_counter()
    motion = load_motion(motion_dir)
    names = [b.name for b in arm_obj.data.bones]
    if mapping is None:
        mapping, map_report = auto_map(names)
    else:
        map_report = {"missing_required": [s for s in REQUIRED if s not in mapping]}
    if map_report["missing_required"]:
        raise RetargetError("Faltan huesos obligatorios en el mapeo: "
                            + ", ".join(map_report["missing_required"]))
    rig = extract_rest(arm_obj, mapping)
    result = solve(rig, motion.world, motion.root, settings or SolverSettings())
    t_solve = time.perf_counter() - t0
    step = (scene_fps / motion.fps) if scene_fps else 1.0
    action = write_action(arm_obj, result, frame_start, action_name, frame_step=step)
    report = {
        "frames": motion.frame_count,
        "keyed_bones": len(result.quaternions),
        "frame_start": frame_start,
        "frame_end": frame_start + (motion.frame_count - 1) * step,
        "detected_ratio": motion.meta["quality"]["detected_ratio"],
        "scale_factor": result.scale_factor,
        "diagnostics": result.diagnostics,
        "timing_s": {"engine": motion.meta.get("timing_s", {}),
                     "solve": round(t_solve, 3),
                     "write": round(time.perf_counter() - t0 - t_solve, 3)},
    }
    return action, report
