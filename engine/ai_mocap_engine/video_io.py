"""Video probing and frame iteration (OpenCV, which bundles its own FFmpeg)."""

import math
import os
from dataclasses import dataclass, asdict

import cv2

from .errors import EngineError

_ROTATE_CODES = {
    90: cv2.ROTATE_90_CLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_COUNTERCLOCKWISE,
}


@dataclass
class VideoInfo:
    path: str
    width: int          # after orientation metadata has been applied
    height: int
    fps: float
    frame_count: int    # as reported by the container (may be approximate)
    duration: float     # seconds
    orientation_meta: int  # rotation stored in the file metadata (degrees)

    def to_dict(self):
        return asdict(self)


def _open(path):
    if not os.path.isfile(path):
        raise EngineError("VIDEO_NOT_FOUND", f"No existe el archivo de vídeo: {path}")
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise EngineError("VIDEO_UNREADABLE",
                          f"OpenCV no puede abrir el vídeo (formato o códec no soportado): {path}")
    # Apply rotation metadata (phone videos) so frames are upright.
    cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)
    return cap


def probe(path):
    cap = _open(path)
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        meta_rot = int(cap.get(cv2.CAP_PROP_ORIENTATION_META) or 0)
        ok, frame = cap.read()
        if not ok or frame is None:
            raise EngineError("VIDEO_EMPTY", "El vídeo no contiene fotogramas legibles.")
        h, w = frame.shape[:2]
    finally:
        cap.release()
    if fps <= 1e-3 or fps > 1000:
        raise EngineError("VIDEO_BAD_FPS", f"FPS inválido en el vídeo: {fps}")
    return VideoInfo(path=path, width=w, height=h, fps=fps, frame_count=count,
                     duration=count / fps if count else 0.0, orientation_meta=meta_rot)


def iter_frames(info, start_s=0.0, end_s=None, target_fps=None, extra_rotation=0, mirror=False):
    """Yield ``(out_index, time_s, rgb_frame)`` resampled to ``target_fps``.

    Frames are read sequentially (no seeking) so timing stays exact for
    variable-keyframe codecs. When ``target_fps`` is higher than the source
    rate, source frames are repeated; the temporal filter smooths that.
    """
    target_fps = float(target_fps or info.fps)
    rot_code = _ROTATE_CODES.get(int(extra_rotation) % 360)
    cap = _open(info.path)
    try:
        src_dt = 1.0 / info.fps
        out_index = 0
        next_t = start_s
        src_index = 0
        while True:
            ok = cap.grab()
            if not ok:
                break
            t = src_index * src_dt
            src_index += 1
            if t + 0.5 * src_dt < next_t:
                continue
            if end_s is not None and next_t > end_s + 1e-9:
                break
            ok, bgr = cap.retrieve()
            if not ok or bgr is None:
                continue
            if rot_code is not None:
                bgr = cv2.rotate(bgr, rot_code)
            if mirror:  # un-mirror selfie footage so left/right labels are anatomical
                bgr = cv2.flip(bgr, 1)
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            while next_t <= t + 0.5 * src_dt and (end_s is None or next_t <= end_s + 1e-9):
                yield out_index, next_t, rgb
                out_index += 1
                next_t = start_s + out_index / target_fps
    finally:
        cap.release()


def expected_output_frames(info, start_s, end_s, target_fps):
    end = info.duration if end_s is None else min(end_s, info.duration or end_s)
    # Frames are sampled at t = start + k / fps for t < end.
    return max(0, int(math.ceil((end - start_s) * float(target_fps or info.fps) - 1e-6)))
