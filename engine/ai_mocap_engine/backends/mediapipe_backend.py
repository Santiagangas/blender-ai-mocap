"""MediaPipe Pose Landmarker backend (Tasks API, VIDEO running mode)."""

import hashlib
import os

import numpy as np

from ..errors import EngineError
from .base import FramePose, PoseBackend


class MediaPipeBackend(PoseBackend):
    name = "mediapipe"

    def __init__(self, model_path, min_detection=0.5, min_presence=0.5, min_tracking=0.5):
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision
        except ImportError as exc:
            raise EngineError("BACKEND_MISSING", f"MediaPipe no está instalado en el motor: {exc}")
        if not os.path.isfile(model_path):
            raise EngineError("MODEL_MISSING", f"No se encuentra el modelo: {model_path}")

        self._mp = mp
        self.version = getattr(mp, "__version__", "?")
        self.model = os.path.basename(model_path)
        with open(model_path, "rb") as fh:
            # Load from memory: MediaPipe's file loader fails on some non-ASCII Windows paths.
            buffer = fh.read()
        self.model_sha1 = hashlib.sha1(buffer).hexdigest()

        def make_options(mode):
            return vision.PoseLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_buffer=buffer),
                running_mode=mode,
                num_poses=1,
                min_pose_detection_confidence=min_detection,
                min_pose_presence_confidence=min_presence,
                min_tracking_confidence=min_tracking,
                output_segmentation_masks=False,
            )

        self._create = lambda mode: vision.PoseLandmarker.create_from_options(make_options(mode))
        self._video_mode = vision.RunningMode.VIDEO
        self._image_mode = vision.RunningMode.IMAGE
        self._landmarker = self._create(self._video_mode)
        self._single = None
        self._last_ts = -1

    def reset_tracking(self):
        """Drop the temporal tracking state (e.g. after it locked onto a wrong pose)."""
        self._landmarker.close()
        self._landmarker = self._create(self._video_mode)

    def process(self, rgb, timestamp_ms):
        ts = int(timestamp_ms)
        if ts <= self._last_ts:  # VIDEO mode requires strictly increasing timestamps
            ts = self._last_ts + 1
        self._last_ts = ts
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB,
                               data=np.ascontiguousarray(rgb))
        return self._to_pose(self._landmarker.detect_for_video(image, ts))

    def process_single(self, rgb):
        """Detect without temporal tracking (independent per-frame detection)."""
        if self._single is None:
            self._single = self._create(self._image_mode)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB,
                               data=np.ascontiguousarray(rgb))
        return self._to_pose(self._single.detect(image))

    @staticmethod
    def _to_pose(result):
        if not result.pose_world_landmarks:
            return None
        world_lms = result.pose_world_landmarks[0]
        image_lms = result.pose_landmarks[0]
        world = np.array([(l.x, l.y, l.z) for l in world_lms], dtype=np.float64)
        img = np.array([(l.x, l.y) for l in image_lms], dtype=np.float64)
        vis = np.array([l.visibility if l.visibility is not None else 0.0 for l in image_lms])
        pres = np.array([l.presence if l.presence is not None else 1.0 for l in image_lms])
        return FramePose(world=world, image=img, confidence=np.clip(vis * pres, 0.0, 1.0))

    def close(self):
        for lm in (self._landmarker, self._single):
            if lm is not None:
                lm.close()
        self._landmarker = self._single = None
