from dataclasses import dataclass

import numpy as np


@dataclass
class FramePose:
    """Pose of one person in one frame, in the backend's camera space."""
    world: np.ndarray       # (J, 3) metres, hip-centred, camera axes (x right, y down, z away)
    image: np.ndarray       # (J, 2) normalised image coordinates [0, 1]
    confidence: np.ndarray  # (J,) 0..1


class PoseBackend:
    name = "base"
    version = "0"
    model = ""

    def process(self, rgb, timestamp_ms):
        """Return a FramePose, or None when no person is detected."""
        raise NotImplementedError

    def process_single(self, rgb):
        """Per-frame detection without temporal tracking (None if unsupported)."""
        return None

    def reset_tracking(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
