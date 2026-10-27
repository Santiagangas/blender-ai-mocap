"""Cache of engine results, so a video is analysed by the AI only once.

Key = video identity (path, size, modification time) + every engine setting
that changes the result + engine version + model. Re-generating the Action
with other retargeting or output settings reuses the cached analysis.
"""

import hashlib
import json
import os
import shutil
import uuid

RESULT_FILES = ("result.json", "motion.npz")


def video_identity(path):
    path = os.path.realpath(path)
    st = os.stat(path)
    norm = os.path.normcase(path)
    return {"path": norm, "size": st.st_size, "mtime_ns": st.st_mtime_ns}


def make_key(video_path, engine_params, engine_version, model_sha256):
    payload = {
        "video": video_identity(video_path),
        "params": engine_params,
        "engine": engine_version,
        "model": model_sha256,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:20]


def entry_dir(cache_root, key):
    return os.path.join(cache_root, key)


def is_complete(path):
    return bool(path) and all(os.path.isfile(os.path.join(path, f)) for f in RESULT_FILES)


def lookup(cache_root, key):
    path = entry_dir(cache_root, key)
    return path if is_complete(path) else None


def new_work_dir(cache_root):
    path = os.path.join(cache_root, "_work_" + uuid.uuid4().hex[:10])
    os.makedirs(path, exist_ok=True)
    return path


def purge_work_dirs(cache_root):
    """Remove leftovers of interrupted captures (only call when no task runs)."""
    if not os.path.isdir(cache_root):
        return
    for d in os.listdir(cache_root):
        if d.startswith("_work_"):
            shutil.rmtree(os.path.join(cache_root, d), ignore_errors=True)


def store(cache_root, key, work_dir):
    """Move a finished engine output into the cache; returns the final folder."""
    final = entry_dir(cache_root, key)
    if os.path.isdir(final):
        shutil.rmtree(final, ignore_errors=True)
    os.replace(work_dir, final)
    return final


def discard(path):
    if path and os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def entries(cache_root):
    if not os.path.isdir(cache_root):
        return []
    return [os.path.join(cache_root, d) for d in os.listdir(cache_root)
            if not d.startswith("_work_") and is_complete(os.path.join(cache_root, d))]


def clear(cache_root):
    if os.path.isdir(cache_root):
        shutil.rmtree(cache_root, ignore_errors=True)
