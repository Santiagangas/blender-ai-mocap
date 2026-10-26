"""Command line entry point used by the Blender add-on.

    python -m ai_mocap_engine.cli run   --job job.json
    python -m ai_mocap_engine.cli probe --video clip.mp4
    python -m ai_mocap_engine.cli selftest --model pose_landmarker_full.task

Every command prints JSON lines on stdout; the last line is either
{"type": "done", ...} or {"type": "error", "code": ..., "message": ...}.
Exit code is 0 on success, 2 on a handled error, 1 on a crash.
"""

import argparse
import json
import sys
import traceback

from .errors import EngineError
from .pipeline import Progress, run_job


def _print(event):
    sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def cmd_run(args):
    with open(args.job, "r", encoding="utf-8") as fh:
        job = json.load(fh)
    run_job(job, Progress(sys.stdout))


def cmd_probe(args):
    from . import video_io
    info = video_io.probe(args.video)
    _print({"type": "done", "video": info.to_dict()})


def cmd_selftest(args):
    import numpy as np
    from . import CONTRACT_VERSION, ENGINE_VERSION
    from .backends import create_backend
    import cv2
    import mediapipe
    with create_backend("mediapipe", model_path=args.model) as backend:
        frame = np.full((256, 256, 3), 128, dtype=np.uint8)
        backend.process(frame, 0)  # no person: must simply return None
    _print({"type": "done", "engine_version": ENGINE_VERSION, "contract_version": CONTRACT_VERSION,
            "python": sys.version.split()[0], "numpy": np.__version__, "opencv": cv2.__version__,
            "mediapipe": getattr(mediapipe, "__version__", "?")})


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ai_mocap_engine")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run"); p.add_argument("--job", required=True); p.set_defaults(fn=cmd_run)
    p = sub.add_parser("probe"); p.add_argument("--video", required=True); p.set_defaults(fn=cmd_probe)
    p = sub.add_parser("selftest"); p.add_argument("--model", required=True); p.set_defaults(fn=cmd_selftest)
    args = parser.parse_args(argv)
    # The protocol is UTF-8 JSON lines regardless of the Windows console code page.
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        args.fn(args)
    except EngineError as exc:
        _print({"type": "error", "code": exc.code, "message": exc.message})
        return 2
    except Exception as exc:  # report crashes in the same channel
        _print({"type": "error", "code": "CRASH", "message": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
