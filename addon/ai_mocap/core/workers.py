"""Background work: engine install, model download, self-test, video probe, capture.

Everything here runs in a worker thread (see ``core.tasks``) and must not
touch ``bpy``. Inputs are plain values captured on the main thread.
"""

import hashlib
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request

from .. import engine_env as E
from .tasks import TaskError

STAGE_LABELS = {"pose": "Detectando poses", "temporal": "Filtrado temporal"}


def _json_events(on_event):
    """stdout line handler: parse JSON lines, return True when consumed."""
    def handler(line):
        if not line.startswith("{"):
            return False
        try:
            event = json.loads(line)
        except ValueError:
            return False
        on_event(event)
        return True
    return handler


# --- Model download -----------------------------------------------------------

def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def model_verified(paths, variant):
    return paths.model_ok(variant) and _sha256(paths.model(variant)) == E.MODELS[variant]["sha256"]


def download_model(ctx, paths, variant, online):
    info = E.MODELS[variant]
    dest = paths.model(variant)
    if model_verified(paths, variant):
        return dest
    if not online:
        raise TaskError("Hace falta descargar el modelo «%s», pero Blender no tiene permitido el acceso "
                        "a internet. Actívalo en Preferencias → Sistema → Red → «Permitir acceso en "
                        "línea»." % info["label"], "OFFLINE")
    os.makedirs(paths.models, exist_ok=True)
    part = dest + ".part"
    total = info["size"]
    mb = 1024 * 1024
    ctx.progress(stage="Descargando modelo " + info["label"], done=0, total=total, message="")
    ctx.log(f"GET {info['url']}")
    h = hashlib.sha256()
    try:
        req = urllib.request.Request(info["url"], headers={"User-Agent": "ai-mocap-blender"})
        with urllib.request.urlopen(req, timeout=30) as resp, open(part, "wb") as fh:
            got = 0
            while True:
                ctx.check_cancel()
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                h.update(chunk)
                got += len(chunk)
                ctx.progress(done=got, message=f"{got / mb:.1f} / {total / mb:.1f} MB")
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        _remove(part)
        reason = getattr(exc, "reason", exc)
        raise TaskError(f"No se pudo descargar el modelo: {reason}. Comprueba la conexión a "
                        "internet o el cortafuegos.", "DOWNLOAD_FAILED")
    except BaseException:
        _remove(part)
        raise
    if h.hexdigest() != info["sha256"]:
        _remove(part)
        raise TaskError("El modelo descargado no coincide con la huella esperada (archivo dañado o "
                        "cambiado en el servidor). Vuelve a intentarlo.", "MODEL_HASH")
    os.replace(part, dest)
    ctx.log(f"model ok: {dest}")
    return dest


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


# --- Engine install / verify --------------------------------------------------

# Longest file inside site-packages after installing the pinned requirements
# (mediapipe/tasks/python/metadata/metadata_writers/__pycache__/…, measured).
LONGEST_PACKAGE_PATH = 101
WINDOWS_MAX_PATH = 259


def _windows_long_paths_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1
    except (OSError, ImportError):
        return False


def path_too_long(paths, platform=None):
    """Message if the venv would exceed Windows' 260-character path limit, else ''."""
    if (platform or sys.platform) != "win32":
        return ""
    site = os.path.join(paths.venv, "Lib", "site-packages") + "\\"
    if len(site) + LONGEST_PACKAGE_PATH <= WINDOWS_MAX_PATH or _windows_long_paths_enabled():
        return ""
    return ("La carpeta de instalación tiene una ruta demasiado larga para Windows "
            f"({len(site)} caracteres): algunos archivos de MediaPipe no cabrían. Elige una carpeta "
            "más corta (por ejemplo C:\\AIMocap) en «Carpeta de datos», más abajo, y vuelve a pulsar "
            "Instalar.")

def install_engine(ctx, paths, base_python, variant, online, reinstall=False):
    if not online:
        raise TaskError("Para instalar el motor, Blender necesita acceso a internet. Actívalo en "
                        "Preferencias → Sistema → Red → «Permitir acceso en línea».", "OFFLINE")
    if not os.path.isfile(E.REQUIREMENTS_FILE):
        raise TaskError("Falta engine_requirements.txt en el addon; reinstala el addon.", "BROKEN_ADDON")
    os.makedirs(paths.data_dir, exist_ok=True)
    too_long = path_too_long(paths)
    if too_long:
        raise TaskError(too_long, "PATH_TOO_LONG")
    if reinstall and os.path.isdir(paths.venv):
        ctx.progress(stage="Eliminando el motor anterior", done=0, total=0, message="")
        shutil.rmtree(paths.venv, ignore_errors=True)
        E.invalidate_status()

    if not os.path.isfile(paths.python):
        ctx.progress(stage="Creando entorno aislado (1/4)", done=0, total=0,
                     message="Python base: " + base_python)
        code = ctx.run([base_python, "-m", "venv", paths.venv], env=E.subprocess_env())
        if code != 0 or not os.path.isfile(paths.python):
            raise TaskError("No se pudo crear el entorno del motor con el Python de Blender.\n"
                            + ctx.log_tail(), "VENV_FAILED")

    ctx.progress(stage="Instalando dependencias (2/4)", done=0, total=0,
                 message="Descargando MediaPipe, OpenCV y NumPy (~470 MB)…")
    seen = {"n": 0}

    def on_pip(line):
        low = line.strip()
        if low.startswith("Collecting "):
            seen["n"] += 1
            ctx.progress(message="Descargando " + low.split()[1])
        elif low.startswith("Installing collected packages"):
            ctx.progress(message="Instalando paquetes (puede tardar un par de minutos)…")
        return False  # keep everything in the log as well

    cmd = [paths.python, "-m", "pip", "install", "--no-input", "--progress-bar", "off",
           "--only-binary=:all:", "-r", E.REQUIREMENTS_FILE]
    code = ctx.run(cmd, env=E.subprocess_env(), on_line=on_pip)
    if code != 0:
        raise TaskError("pip no pudo instalar las dependencias del motor. Revisa la conexión, el "
                        "antivirus o el espacio en disco.\n" + ctx.log_tail(), "PIP_FAILED")

    ctx.progress(stage="Descargando modelo (3/4)", done=0, total=0, message="")
    download_model(ctx, paths, variant, online)
    ctx.progress(stage="Verificando (4/4)", done=0, total=0, message="")
    return verify_engine(ctx, paths, variant, base_python)


def verify_engine(ctx, paths, variant, base_python=""):
    if not os.path.isfile(paths.python):
        raise TaskError("El motor no está instalado.", "NOT_INSTALLED")
    if not paths.model_ok(variant):
        raise TaskError("Falta el modelo «%s». Descárgalo en las preferencias del addon."
                        % E.MODELS[variant]["label"], "MODEL_MISSING")
    ctx.progress(stage="Verificando el motor", done=0, total=0,
                 message="Cargando MediaPipe y el modelo…")
    events = []
    code = ctx.run(E.engine_command(paths, "selftest", "--model", paths.model(variant)),
                   env=E.subprocess_env(with_engine=True), on_line=_json_events(events.append))
    last = events[-1] if events else {}
    if last.get("type") != "done":
        msg = last.get("message") or ctx.log_tail()
        if sys.platform.startswith("linux") and ("libEGL" in msg or "libGLES" in msg):
            msg += ("\nMediaPipe necesita las librerías gráficas del sistema. Instálalas con: "
                    "sudo apt install libegl1 libgles2")
        raise TaskError("La autoprueba del motor ha fallado: " + msg, last.get("code", "SELFTEST"))
    versions = {k: last.get(k) for k in ("python", "numpy", "opencv", "mediapipe")}
    status = {
        "verified": True,
        "verified_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "requirements": E.requirements_hash(),
        "engine_version": last.get("engine_version"),
        "contract_version": last.get("contract_version"),
        "versions": versions,
        "base_python": base_python or E.read_status(paths).get("base_python", ""),
        "platform": sys.platform,
    }
    E.write_status(paths, status)
    return status


# --- Video ------------------------------------------------------------------

def probe_video(ctx, paths, video):
    ctx.progress(stage="Analizando vídeo", done=0, total=0, message=os.path.basename(video))
    events = []
    ctx.run(E.engine_command(paths, "probe", "--video", video),
            env=E.subprocess_env(with_engine=True), on_line=_json_events(events.append))
    last = events[-1] if events else {}
    if last.get("type") == "error":
        raise TaskError(last.get("message", "Error al leer el vídeo."), last.get("code", ""))
    if last.get("type") != "done":
        raise TaskError("No se pudo analizar el vídeo.\n" + ctx.log_tail(), "PROBE_FAILED")
    return last["video"]


def capture(ctx, paths, job, variant, online):
    """Run the engine on a video. ``job['out_dir']`` must be a fresh work folder."""
    if not paths.model_ok(variant):
        download_model(ctx, paths, variant, online)
    job = dict(job, model_path=paths.model(variant))
    os.makedirs(job["out_dir"], exist_ok=True)
    job_path = os.path.join(job["out_dir"], "job.json")
    with open(job_path, "w", encoding="utf-8") as fh:
        json.dump(job, fh, indent=1, ensure_ascii=False)

    ctx.progress(stage="Iniciando el motor de IA", done=0, total=0, message="Cargando el modelo…")
    state = {"done": None, "error": None, "total": 0}

    def on_event(ev):
        kind = ev.get("type")
        if kind == "info":
            state["total"] = int(ev.get("expected_frames") or 0)
            ctx.progress(stage=STAGE_LABELS["pose"], done=0, total=state["total"], message="")
        elif kind == "progress":
            done, total = int(ev.get("done", 0)), int(ev.get("total", 0))
            stage = STAGE_LABELS.get(ev.get("stage"), ev.get("stage", ""))
            msg = f"Fotograma {done} de {total}" if ev.get("stage") == "pose" else ""
            ctx.progress(stage=stage, done=done, total=total, message=msg)
        elif kind == "done":
            state["done"] = ev
        elif kind == "error":
            state["error"] = ev

    code = ctx.run(E.engine_command(paths, "run", "--job", job_path),
                   env=E.subprocess_env(with_engine=True), on_line=_json_events(on_event))
    if state["error"]:
        err = state["error"]
        if err.get("traceback"):
            ctx.log(err["traceback"])
        raise TaskError(err.get("message", "Error del motor."), err.get("code", "ENGINE"))
    if state["done"] is None:
        raise TaskError(f"El motor terminó sin resultado (código {code}).\n" + ctx.log_tail(),
                        "ENGINE_EXIT")
    return {"out_dir": job["out_dir"], "timing_s": state["done"].get("timing_s", {}),
            "frames": state["done"].get("frames")}
