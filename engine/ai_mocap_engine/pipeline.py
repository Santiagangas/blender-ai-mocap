"""Video -> motion pipeline and contract writer."""

import json
import os
import time

import numpy as np

from . import CONTRACT_VERSION, ENGINE_VERSION
from .backends import create_backend
from .errors import EngineError
from .root import estimate_root
from .skeleton import JOINT_NAMES, LR_AXIS_PAIRS, NUM_JOINTS, SWAP_LR, camera_to_contract
from .temporal import (fill_gaps, flip_front_back, resolve_facing, smoothing_to_cutoff,
                       trust_long_gaps, zero_phase_one_euro)
from . import video_io

DEFAULT_JOB = {
    "video": None,
    "out_dir": None,
    "backend": "mediapipe",
    "model_path": None,
    "start_s": 0.0,
    "end_s": None,
    "target_fps": None,          # None -> source fps
    "rotation": 0,               # extra clockwise rotation (0/90/180/270)
    "mirror": False,             # selfie footage: flip frames horizontally
    "min_confidence": 0.5,       # joints below this are treated as missing
    "max_gap_s": 0.25,           # longer low-confidence stretches keep the detector's estimate
    "smoothing": 0.5,            # 0..1
    "hfov_deg": 60.0,            # assumed camera horizontal field of view
    "assume_upright": True,      # reject upside-down detections (disable for handstands)
    "initial_facing": "camera",  # "camera": subject faces the camera at the start; "auto"
}

# Torso pointing more than this away from image-up counts as an inverted detection.
_INVERTED_COS = -0.342  # cos(110 deg)

def is_inverted(image_xy, width, height):
    """True when the hip->shoulder vector points down in the image."""
    px = image_xy * (width, height)
    torso = 0.5 * (px[11] + px[12]) - 0.5 * (px[23] + px[24])
    norm = np.linalg.norm(torso)
    return norm > 1e-6 and (-torso[1] / norm) < _INVERTED_COS


class Progress:
    """Writes JSON-lines progress events to a stream (stdout for the add-on)."""

    def __init__(self, stream=None, min_interval=0.2):
        self.stream = stream
        self.min_interval = min_interval
        self._last = 0.0

    def emit(self, event, force=False):
        if self.stream is None:
            return
        now = time.monotonic()
        if not force and now - self._last < self.min_interval:
            return
        self._last = now
        self.stream.write(json.dumps(event) + "\n")
        self.stream.flush()


def run_job(job, progress=None):
    job = {**DEFAULT_JOB, **job}
    progress = progress or Progress(None)
    if not job["video"] or not job["out_dir"]:
        raise EngineError("BAD_JOB", "El trabajo debe indicar 'video' y 'out_dir'.")
    if not job["model_path"]:
        raise EngineError("MODEL_MISSING", "No se ha indicado el modelo de pose.")

    t0 = time.perf_counter()
    info = video_io.probe(job["video"])
    target_fps = float(job["target_fps"] or info.fps)
    total = video_io.expected_output_frames(info, job["start_s"], job["end_s"], target_fps)
    progress.emit({"type": "info", "video": info.to_dict(), "expected_frames": total}, force=True)

    world_cam, image, conf, times = [], [], [], []
    stats = {"inverted": 0, "recovered": 0}
    width, height = info.width, info.height
    with create_backend(job["backend"], model_path=job["model_path"]) as backend:
        for idx, t, rgb in video_io.iter_frames(info, job["start_s"], job["end_s"],
                                                target_fps, job["rotation"], job["mirror"]):
            height, width = rgb.shape[:2]
            pose = backend.process(rgb, t * 1000.0)
            if pose is not None and job["assume_upright"] and is_inverted(pose.image, width, height):
                # The tracker may lock onto an upside-down interpretation (raised arms
                # read as legs). Re-detect this frame from scratch and reset tracking.
                stats["inverted"] += 1
                retry = backend.process_single(rgb)
                backend.reset_tracking()
                if retry is not None and not is_inverted(retry.image, width, height):
                    pose = retry
                    stats["recovered"] += 1
                else:
                    pose = None
            times.append(t)
            if pose is None:
                world_cam.append(np.full((NUM_JOINTS, 3), np.nan))
                image.append(np.full((NUM_JOINTS, 2), np.nan))
                conf.append(np.zeros(NUM_JOINTS))
            else:
                world_cam.append(pose.world)
                image.append(pose.image)
                conf.append(pose.confidence)
            progress.emit({"type": "progress", "stage": "pose", "done": idx + 1,
                           "total": max(total, idx + 1)})
        backend_meta = {"name": backend.name, "version": backend.version,
                        "model": backend.model, "model_sha1": getattr(backend, "model_sha1", "")}
    t_pose = time.perf_counter() - t0

    F = len(times)
    if F == 0:
        raise EngineError("VIDEO_EMPTY", "No se ha leído ningún fotograma en el rango indicado.")
    world_cam = np.asarray(world_cam)
    image = np.asarray(image)
    conf = np.asarray(conf)
    detected = ~np.isnan(world_cam[:, 0, 0])
    if detected.sum() < max(2, 0.1 * F):
        raise EngineError("NO_PERSON",
                          f"Solo se detectó una persona en {int(detected.sum())} de {F} fotogramas.")

    progress.emit({"type": "progress", "stage": "temporal", "done": 0, "total": 1}, force=True)
    valid = detected[:, None] & (conf >= job["min_confidence"])
    max_gap = max(0, int(round(float(job["max_gap_s"]) * target_fps)))
    valid, trusted = trust_long_gaps(valid, detected, max_gap)
    world_cam, interpolated, never_seen = fill_gaps(world_cam, valid)
    image, _, _ = fill_gaps(image, valid)

    # Front/back ambiguity: keep the interpretation that is temporally continuous.
    flip = resolve_facing(world_cam, list(SWAP_LR), LR_AXIS_PAIRS, job["initial_facing"], target_fps)
    if flip.any():
        fw, fi, fc = flip_front_back(world_cam[flip], image[flip], conf[flip], list(SWAP_LR))
        world_cam[flip], image[flip], conf[flip] = fw, fi, fc
        interpolated[flip] = interpolated[flip][:, list(SWAP_LR)]
    raw_world = camera_to_contract(world_cam)

    cutoff = smoothing_to_cutoff(job["smoothing"])
    world_cam_s = zero_phase_one_euro(world_cam, target_fps, min_cutoff=cutoff, beta=0.6)
    image_s = zero_phase_one_euro(image, target_fps, min_cutoff=cutoff, beta=0.3)
    root, depth = estimate_root(world_cam_s, image_s, np.where(valid, conf, 0.0),
                                width, height, target_fps, hfov_deg=job["hfov_deg"])
    world = camera_to_contract(world_cam_s)

    out_dir = job["out_dir"]
    os.makedirs(out_dir, exist_ok=True)
    arrays = {
        "world": world.astype(np.float32),
        "world_raw": raw_world.astype(np.float32),
        "image": image_s.astype(np.float32),
        "confidence": conf.astype(np.float32),
        "valid": detected,
        "interpolated": interpolated,
        "root": root.astype(np.float32),
        "depth": depth.astype(np.float32),
        "times": np.asarray(times, dtype=np.float64),
    }
    tmp_npz = os.path.join(out_dir, "motion.tmp.npz")
    np.savez_compressed(tmp_npz, **arrays)
    os.replace(tmp_npz, os.path.join(out_dir, "motion.npz"))

    result = {
        "contract_version": CONTRACT_VERSION,
        "engine_version": ENGINE_VERSION,
        "coordinate_system": {
            "handedness": "right", "up": "+Z", "units": "meters",
            "description": "X image-right, Y away from camera, Z up; a subject facing "
                           "the camera faces -Y. 'world' is pelvis-relative, 'root' is the "
                           "pelvis trajectory (XY relative to first frame, Z above ground).",
        },
        "fps": target_fps,
        "frame_count": F,
        "start_s": job["start_s"],
        "joint_names": list(JOINT_NAMES),
        "source": info.to_dict(),
        "processed_size": [width, height],
        "backend": backend_meta,
        "settings": {k: job[k] for k in ("start_s", "end_s", "target_fps", "rotation", "mirror",
                                          "min_confidence", "max_gap_s", "smoothing", "hfov_deg",
                                          "assume_upright", "initial_facing")},
        "quality": {
            "detected_ratio": float(detected.mean()),
            "interpolated_ratio_per_joint": dict(zip(JOINT_NAMES, interpolated.mean(axis=0).round(4).tolist())),
            "estimated_ratio_per_joint": dict(zip(JOINT_NAMES, trusted.mean(axis=0).round(4).tolist())),
            "never_seen_joints": [JOINT_NAMES[i] for i in np.flatnonzero(never_seen)],
            "inverted_detections": stats["inverted"],
            "inverted_recovered": stats["recovered"],
            "front_back_flipped_frames": int(flip.sum()),
        },
        "timing_s": {"pose": round(t_pose, 3), "total": round(time.perf_counter() - t0, 3)},
    }
    tmp_json = os.path.join(out_dir, "result.tmp.json")
    with open(tmp_json, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, ensure_ascii=False)
    os.replace(tmp_json, os.path.join(out_dir, "result.json"))
    progress.emit({"type": "done", "out_dir": out_dir, "frames": F,
                   "timing_s": result["timing_s"]}, force=True)
    return result
