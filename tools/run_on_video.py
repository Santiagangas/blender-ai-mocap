"""Phase 2 prototype: video + character -> .blend with a new Action.

    <engine-python> tools/run_on_video.py --video clip.mp4 --fbx "X Bot.fbx" --out out_dir
        [--blender <blender.exe>] [--model dev/models/pose_landmarker_full.task]
        [--fps 30] [--start 0] [--end 5] [--mirror] [--smoothing 0.5]

Runs the engine on the video, then Blender in background to retarget onto the
character, and writes <out_dir>/mocap.blend. Open it and press Play.
"""

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--fbx", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--blender", default=DEFAULT_BLENDER)
    ap.add_argument("--model", default=os.path.join(ROOT, "dev", "models", "pose_landmarker_full.task"))
    ap.add_argument("--fps", type=float, default=30)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--mirror", action="store_true")
    ap.add_argument("--smoothing", type=float, default=0.5)
    args = ap.parse_args()

    out = os.path.realpath(args.out)
    engine_dir = os.path.join(out, "engine")
    os.makedirs(out, exist_ok=True)
    job = {"video": os.path.realpath(args.video), "out_dir": engine_dir,
           "model_path": os.path.realpath(args.model), "target_fps": args.fps,
           "start_s": args.start, "end_s": args.end, "mirror": args.mirror,
           "smoothing": args.smoothing}
    job_path = os.path.join(out, "job.json")
    with open(job_path, "w", encoding="utf-8") as fh:
        json.dump(job, fh, indent=1)

    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "engine"))
    proc = subprocess.Popen([sys.executable, "-m", "ai_mocap_engine.cli", "run", "--job", job_path],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, encoding="utf-8")
    last = None
    for line in proc.stdout:
        event = json.loads(line)
        last = event
        if event["type"] == "progress":
            print(f"\r[{event['stage']}] {event['done']}/{event['total']}", end="", flush=True)
    proc.wait()
    print()
    if not last or last["type"] != "done":
        raise SystemExit(f"Engine failed: {last}")
    print("engine:", last["timing_s"])

    blend = os.path.join(out, "mocap.blend")
    res = subprocess.run([args.blender, "-b", "--factory-startup", "--python",
                          os.path.join(HERE, "apply_to_fbx.py"), "--",
                          os.path.realpath(args.fbx), engine_dir, blend, "--fps", str(int(args.fps))],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    applied = [l for l in res.stdout.splitlines() if l.startswith("APPLIED")]
    if res.returncode != 0 or not applied:
        raise SystemExit("Blender step failed:\n" + res.stdout[-3000:] + res.stderr[-3000:])
    print(applied[0])
    print("Saved:", blend)


if __name__ == "__main__":
    main()
