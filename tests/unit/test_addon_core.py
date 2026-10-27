"""Pure-Python parts of the add-on: cache keys, presets, key reduction, paths."""

import os

import numpy as np

from ai_mocap import engine_env as E
from ai_mocap.core import cache
from ai_mocap.core.apply import sample_indices
from ai_mocap.core.workers import path_too_long
from ai_mocap.rig import presets as P
from ai_mocap.rig.mapping import MIXAMO


def test_cache_key_changes_with_video_and_settings(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x" * 100)
    params = {"smoothing": 0.5, "target_fps": 30}
    k1 = cache.make_key(str(video), params, "0.2.0", "abc")
    assert k1 == cache.make_key(str(video), dict(params), "0.2.0", "abc")
    assert k1 != cache.make_key(str(video), {**params, "smoothing": 0.6}, "0.2.0", "abc")
    assert k1 != cache.make_key(str(video), params, "0.3.0", "abc")
    assert k1 != cache.make_key(str(video), params, "0.2.0", "other-model")
    video.write_bytes(b"y" * 101)          # edited video -> new analysis
    assert k1 != cache.make_key(str(video), params, "0.2.0", "abc")


def test_cache_store_and_lookup(tmp_path):
    root = str(tmp_path / "cache")
    work = cache.new_work_dir(root)
    assert cache.lookup(root, "k") is None
    for f in cache.RESULT_FILES:
        open(os.path.join(work, f), "w").close()
    final = cache.store(root, "k", work)
    assert cache.lookup(root, "k") == final and not os.path.exists(work)
    assert cache.entries(root) == [final]
    cache.clear(root)
    assert cache.entries(root) == []


def test_sample_indices_keeps_last_frame():
    assert sample_indices(10, 1).tolist() == list(range(10))
    assert sample_indices(10, 3).tolist() == [0, 3, 6, 9]
    assert sample_indices(11, 3).tolist() == [0, 3, 6, 9, 10]
    assert sample_indices(1, 4).tolist() == [0]


def test_presets_roundtrip_and_prefix_resolution(tmp_path):
    user = str(tmp_path / "presets")
    mapping = {s: "mixamorig:" + b for s, b in MIXAMO.items()}
    path = P.save_preset(user, "Mi rig/raro", mapping)
    assert os.path.basename(path) == "Mi rig_raro.json"
    loaded = P.load_preset(path)
    assert loaded["hips"] == "Hips"            # stored without namespace
    bones = ["mixamorig9:" + b for b in MIXAMO.values()]
    resolved, unmatched = P.resolve(loaded, bones)
    assert resolved["upper_arm.L"] == "mixamorig9:LeftArm" and not unmatched
    listed = P.list_presets(user)
    assert listed[0][3] is True and listed[0][1] == "Mixamo"   # built-in first
    assert any(p[1] == "Mi rig/raro" and not p[3] for p in listed)


def test_windows_path_limit():
    short = E.Paths(r"C:\AIMocap")
    assert path_too_long(short, platform="win32") == ""
    deep = E.Paths("C:\\" + "x" * 150)
    assert "demasiado larga" in path_too_long(deep, platform="win32")
    assert path_too_long(deep, platform="linux") == ""


def test_models_table_is_consistent():
    for key, info in E.MODELS.items():
        assert info["file"] == f"pose_landmarker_{key}.task"
        assert len(info["sha256"]) == 64 and info["size"] > 1_000_000
    with open(E.REQUIREMENTS_FILE) as fh:
        reqs = [l.split("==")[0] for l in fh if l.strip() and not l.startswith("#")]
        assert sum(r == "numpy" for r in reqs) == 2   # one pin per Python range
    assert {"mediapipe", "numpy", "opencv-contrib-python"} <= set(reqs)
