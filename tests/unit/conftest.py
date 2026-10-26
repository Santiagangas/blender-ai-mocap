import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "addon"))
sys.path.insert(0, os.path.join(ROOT, "engine"))

from ai_mocap.retarget.solver import RigRest  # noqa: E402
from ai_mocap.rig.mapping import auto_map  # noqa: E402


@pytest.fixture(scope="session")
def xbot_rig():
    """Rest pose of the Mixamo X Bot exported from Blender (tests/fixtures)."""
    data = np.load(os.path.join(ROOT, "tests", "fixtures", "xbot_rest.npz"))
    names = [str(n) for n in data["names"]]
    mapping, report = auto_map(names)
    assert report["ok"]
    return RigRest(names=names, parents=data["parents"], rest=data["rest"],
                   heads=data["heads"], tails=data["tails"], mapping=mapping)
