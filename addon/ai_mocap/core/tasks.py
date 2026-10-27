"""Background tasks that never block Blender's interface.

A task runs a worker function in a thread. The worker only sees plain
Python data (never ``bpy``) and talks to the main thread through a queue:
progress, log lines and the final result. A timer on the main thread drains
the queue, redraws the UI and, when the task ends, calls ``on_finish`` with
the task (that is where Blender data may be touched again).

Only one task runs at a time; external programs started by the worker are
killed on cancel.
"""

import os
import queue
import subprocess
import sys
import threading
import time
import traceback

RUNNING, DONE, ERROR, CANCELLED = "RUNNING", "DONE", "ERROR", "CANCELLED"
POLL_INTERVAL = 0.1


class TaskError(Exception):
    """Expected failure with a message for the user (Spanish)."""

    def __init__(self, message, code=""):
        super().__init__(message)
        self.message = message
        self.code = code


class Cancelled(Exception):
    pass


class TaskContext:
    """Worker-side API (runs in the background thread)."""

    def __init__(self, task):
        self._task = task

    @property
    def cancelled(self):
        return self._task._cancel.is_set()

    def check_cancel(self):
        if self.cancelled:
            raise Cancelled()

    def progress(self, stage=None, done=None, total=None, message=None):
        self._task._queue.put(("progress", stage, done, total, message))

    def log(self, text):
        self._task._write_log(text)

    def run(self, cmd, env=None, cwd=None, on_line=None):
        """Run an external program, feeding each stdout line to ``on_line``.

        stderr goes to the task log. Returns the exit code. Raises Cancelled
        if the task was cancelled while it ran.
        """
        self.check_cancel()
        self.log("> " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        with open(self._task.log_path, "a", encoding="utf-8", errors="replace") as err:
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err,
                                        stdin=subprocess.DEVNULL, env=env, cwd=cwd, text=True,
                                        encoding="utf-8", errors="replace", bufsize=1, **kwargs)
            except OSError as exc:
                raise TaskError(f"No se pudo ejecutar «{cmd[0]}»: {exc}. Si es el motor, "
                                "reinstálalo desde las preferencias del addon.", "EXEC_FAILED")
            self._task._proc = proc
            try:
                for line in proc.stdout:
                    line = line.rstrip("\r\n")
                    if not line:
                        continue
                    if on_line is None or not on_line(line):  # unhandled lines go to the log
                        err.write(line + "\n")
                        err.flush()
                    if self.cancelled:
                        break
            finally:
                if self.cancelled:
                    _kill(proc)
                code = proc.wait()
                self._task._proc = None
        self.check_cancel()
        return code

    def log_tail(self, lines=15):
        try:
            with open(self._task.log_path, "r", encoding="utf-8", errors="replace") as fh:
                return "".join(fh.readlines()[-lines:]).strip()
        except OSError:
            return ""


def _kill(proc):
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


class Task:
    def __init__(self, title, worker, on_finish=None, kind="task", log_dir=None):
        self.title = title
        self.kind = kind
        self.worker = worker
        self.on_finish = on_finish
        self.state = RUNNING
        self.stage = ""
        self.message = ""
        self.done = 0
        self.total = 0
        self.result = None
        self.error = ""
        self.error_code = ""
        self.started = time.monotonic()
        self.ended = None
        self.finish_note = ""          # set by on_finish (e.g. what was created)
        self._queue = queue.Queue()
        self._cancel = threading.Event()
        self._proc = None
        self._thread = None
        log_dir = log_dir or os.path.join(os.path.expanduser("~"), ".ai_mocap_logs")
        os.makedirs(log_dir, exist_ok=True)
        _prune_logs(log_dir)
        self.log_path = os.path.join(log_dir, f"{kind}_{time.strftime('%Y%m%d_%H%M%S')}.log")
        self._log_lock = threading.Lock()

    # --- worker thread ----------------------------------------------------
    def start(self):
        self._thread = threading.Thread(target=self._run, name=f"ai_mocap_{self.kind}", daemon=True)
        self._thread.start()

    def _run(self):
        ctx = TaskContext(self)
        try:
            result = self.worker(ctx)
            self._queue.put(("end", DONE, result, "", ""))
        except Cancelled:
            self._queue.put(("end", CANCELLED, None, "Cancelado por el usuario.", ""))
        except TaskError as exc:
            self._write_log("ERROR: " + exc.message)
            self._queue.put(("end", ERROR, None, exc.message, exc.code))
        except Exception as exc:  # unexpected: keep the traceback in the log
            self._write_log(traceback.format_exc())
            self._queue.put(("end", ERROR, None, f"Error inesperado: {type(exc).__name__}: {exc}",
                             "CRASH"))

    def _write_log(self, text):
        with self._log_lock:
            try:
                with open(self.log_path, "a", encoding="utf-8", errors="replace") as fh:
                    fh.write(text.rstrip("\n") + "\n")
            except OSError:
                pass

    # --- main thread ------------------------------------------------------
    def cancel(self):
        self._cancel.set()
        proc = self._proc
        if proc is not None:
            _kill(proc)

    @property
    def finished(self):
        return self.state != RUNNING

    @property
    def factor(self):
        return min(1.0, self.done / self.total) if self.total else 0.0

    @property
    def elapsed(self):
        return (self.ended or time.monotonic()) - self.started

    def poll(self):
        """Apply queued events. Returns True once the task has ended."""
        while True:
            try:
                ev = self._queue.get_nowait()
            except queue.Empty:
                break
            if ev[0] == "progress":
                _, stage, done, total, message = ev
                if stage is not None:
                    self.stage = stage
                if done is not None:
                    self.done = done
                if total is not None:
                    self.total = total
                if message is not None:
                    self.message = message
            elif ev[0] == "end":
                _, self.state, self.result, self.error, self.error_code = ev
                self.ended = time.monotonic()
        return self.finished

    def wait(self, timeout=None):
        """Block until the worker thread ends (tests and shutdown only)."""
        if self._thread is not None:
            self._thread.join(timeout)
        return self.poll()


def _prune_logs(log_dir, keep=20):
    try:
        logs = sorted((os.path.join(log_dir, f) for f in os.listdir(log_dir) if f.endswith(".log")),
                      key=os.path.getmtime)
        for path in logs[:-keep]:
            os.remove(path)
    except OSError:
        pass


# --- Manager (main thread) ----------------------------------------------------

_current = None
_last = None
_redraw_cb = None


def current():
    return _current


def last():
    """Most recent finished task (to show its result or error in the UI)."""
    return _last


def busy():
    return _current is not None


def clear_last():
    global _last
    _last = None


def set_redraw_callback(fn):
    global _redraw_cb
    _redraw_cb = fn


def start(task):
    global _current
    if _current is not None:
        raise TaskError("Ya hay una tarea en curso: " + _current.title)
    _current = task
    task.start()
    try:
        import bpy
        if not bpy.app.timers.is_registered(_timer):
            bpy.app.timers.register(_timer, first_interval=POLL_INTERVAL, persistent=True)
    except Exception:  # pragma: no cover - outside Blender: caller drives tick()
        pass
    return task


def cancel():
    if _current is not None:
        _current.cancel()


def tick():
    """Advance the current task; returns True while a task is running."""
    global _current, _last
    task = _current
    if task is None:
        return False
    ended = task.poll()
    if ended:
        _current = None
        _last = task
        if task.on_finish is not None:
            try:
                task.on_finish(task)
            except TaskError as exc:
                task.state, task.error, task.error_code = ERROR, exc.message, exc.code
            except Exception as exc:
                task._write_log(traceback.format_exc())
                task.state = ERROR
                task.error = f"Error al aplicar el resultado: {type(exc).__name__}: {exc}"
    if _redraw_cb is not None:
        try:
            _redraw_cb()
        except Exception:
            pass
    return not ended


def _timer():
    return POLL_INTERVAL if tick() else None


def shutdown():
    """Cancel and wait for the running task (add-on unregister, file load)."""
    global _current
    task = _current
    if task is None:
        return
    task.cancel()
    task.wait(timeout=5)
    _current = None
    try:
        import bpy
        if bpy.app.timers.is_registered(_timer):
            bpy.app.timers.unregister(_timer)
    except Exception:
        pass
