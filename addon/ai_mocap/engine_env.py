"""Where the capture engine lives and how to launch it.

The engine runs in its own virtual environment (created from Blender's
Python), never inside Blender's interpreter. This module only deals with
paths, versions and command lines; it has no UI and no threads.
"""

import hashlib
import json
import os
import re
import sys
import time

ADDON_DIR = os.path.dirname(os.path.realpath(__file__))
REQUIREMENTS_FILE = os.path.join(ADDON_DIR, "engine_requirements.txt")
STATUS_FILE = "engine_status.json"

# MediaPipe Pose Landmarker models (Apache-2.0). Hashes pinned so a corrupt or
# changed download is detected before it is used.
MODELS = {
    "lite": {
        "label": "Lite (rápido)",
        "file": "pose_landmarker_lite.task",
        "url": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
               "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
        "sha256": "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a",
        "size": 5777746,
    },
    "full": {
        "label": "Full (recomendado)",
        "file": "pose_landmarker_full.task",
        "url": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
               "pose_landmarker_full/float16/latest/pose_landmarker_full.task",
        "sha256": "4eaa5eb7a98365221087693fcc286334cf0858e2eb6e15b506aa4a7ecdcec4ad",
        "size": 9398198,
    },
    "heavy": {
        "label": "Heavy (preciso, lento)",
        "file": "pose_landmarker_heavy.task",
        "url": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
               "pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task",
        "sha256": "64437af838a65d18e5ba7a0d39b465540069bc8aae8308de3e318aad31fcbc7b",
        "size": 30664242,
    },
}


def engine_source_dir():
    """Folder that contains the ``ai_mocap_engine`` package.

    Packaged builds ship it as ``engine_src`` inside the add-on; in a
    development checkout it is ``<repo>/engine``.
    """
    bundled = os.path.join(ADDON_DIR, "engine_src")
    if os.path.isdir(os.path.join(bundled, "ai_mocap_engine")):
        return bundled
    dev = os.path.join(os.path.dirname(os.path.dirname(ADDON_DIR)), "engine")
    if os.path.isdir(os.path.join(dev, "ai_mocap_engine")):
        return dev
    return bundled


def engine_version():
    path = os.path.join(engine_source_dir(), "ai_mocap_engine", "__init__.py")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            m = re.search(r'ENGINE_VERSION\s*=\s*"([^"]+)"', fh.read())
        return m.group(1) if m else "?"
    except OSError:
        return "?"


def requirements_hash():
    try:
        with open(REQUIREMENTS_FILE, "rb") as fh:
            return hashlib.sha1(fh.read()).hexdigest()[:12]
    except OSError:
        return ""


def default_data_dir(package):
    """Per-user writable folder for the engine, models, cache and presets."""
    import bpy
    try:
        return bpy.utils.extension_path_user(package, create=True)
    except (ValueError, AttributeError):
        # Loaded as a legacy add-on or from a dev checkout.
        path = bpy.utils.user_resource('CONFIG', path="ai_mocap", create=True)
        return path


class Paths:
    """All engine-related locations for a given data folder."""

    def __init__(self, data_dir):
        self.data_dir = os.path.realpath(data_dir)
        self.venv = os.path.join(self.data_dir, "engine_venv")
        self.models = os.path.join(self.data_dir, "models")
        self.cache = os.path.join(self.data_dir, "cache")
        self.presets = os.path.join(self.data_dir, "presets")
        self.logs = os.path.join(self.data_dir, "logs")
        self.status = os.path.join(self.data_dir, STATUS_FILE)

    @property
    def python(self):
        if sys.platform == "win32":
            return os.path.join(self.venv, "Scripts", "python.exe")
        return os.path.join(self.venv, "bin", "python")

    def model(self, variant):
        return os.path.join(self.models, MODELS[variant]["file"])

    def model_ok(self, variant):
        path = self.model(variant)
        return os.path.isfile(path) and os.path.getsize(path) == MODELS[variant]["size"]


def base_python(override=""):
    """Interpreter used to create the venv: Blender's own Python by default."""
    if override and os.path.isfile(override):
        return os.path.realpath(override)
    return os.path.realpath(sys.executable)


def subprocess_env(with_engine=False):
    """Clean environment for child Python processes."""
    env = dict(os.environ)
    for key in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "VIRTUAL_ENV", "PYTHONEXECUTABLE",
                "__PYVENV_LAUNCHER__"):
        env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    if with_engine:
        env["PYTHONPATH"] = engine_source_dir()
    return env


def engine_command(paths, *args):
    return [paths.python, "-s", "-m", "ai_mocap_engine.cli", *args]


# --- Status -----------------------------------------------------------------

_status_cache = {"key": None, "t": 0.0, "value": None}


def read_status(paths):
    try:
        with open(paths.status, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def write_status(paths, data):
    os.makedirs(paths.data_dir, exist_ok=True)
    tmp = paths.status + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, paths.status)
    invalidate_status()


def invalidate_status():
    _status_cache["key"] = None


def engine_state(paths):
    """Return (state, detail). state: READY | NOT_INSTALLED | OUTDATED | UNVERIFIED.

    Cached for a couple of seconds because UI draw code calls it often.
    """
    now = time.monotonic()
    if _status_cache["key"] == paths.data_dir and now - _status_cache["t"] < 2.0:
        return _status_cache["value"]
    if not os.path.isfile(paths.python):
        value = ("NOT_INSTALLED", "El motor de captura no está instalado.")
    else:
        st = read_status(paths)
        if not st.get("verified"):
            value = ("UNVERIFIED", "El motor está instalado pero no se ha verificado.")
        elif st.get("requirements") != requirements_hash():
            value = ("OUTDATED", "Esta versión del addon necesita actualizar el motor.")
        else:
            value = ("READY", "MediaPipe {mediapipe} · Python {python}".format(
                mediapipe=st.get("versions", {}).get("mediapipe", "?"),
                python=st.get("versions", {}).get("python", "?")))
    _status_cache.update(key=paths.data_dir, t=now, value=value)
    return value


def folder_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
