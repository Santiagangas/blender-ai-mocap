from .base import PoseBackend, FramePose


def create_backend(name, **kwargs):
    if name == "mediapipe":
        from .mediapipe_backend import MediaPipeBackend
        return MediaPipeBackend(**kwargs)
    raise ValueError(f"Unknown pose backend: {name}")
