"""Run the whole closed-loop test: ground truth -> engine -> retarget -> metrics.

    <engine-python> tests/e2e/run_closed_loop.py --blender <blender.exe> --fbx <character.fbx>
        --models dev/models --out dev/closed_loop [--variants full,heavy] [--skip-gt] [--render]

Must be launched with the engine's Python (it runs the engine in-process
via subprocess with the same interpreter).
"""

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def run(cmd, env=None):
    print(">", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    if proc.returncode != 0:
        print(proc.stdout[-4000:], proc.stderr[-4000:])
        raise SystemExit(f"command failed ({proc.returncode})")
    return proc.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blender", required=True)
    ap.add_argument("--fbx", required=True)
    ap.add_argument("--models", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--variants", default="full")
    ap.add_argument("--skip-gt", action="store_true")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--smoothing", type=float, default=0.5)
    args = ap.parse_args()
    out = os.path.realpath(args.out)
    os.makedirs(out, exist_ok=True)

    if not args.skip_gt:
        run([args.blender, "-b", "--factory-startup", "--python",
             os.path.join(HERE, "make_ground_truth.py"), "--", args.fbx, out])
    with open(os.path.join(out, "gt_camera.txt")) as fh:
        hfov = float(fh.read().split("=")[1])

    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "engine"))
    summary = {}
    for variant in args.variants.split(","):
        eng_dir = os.path.join(out, f"engine_{variant}")
        job = {"video": os.path.join(out, "gt.mp4"), "out_dir": eng_dir,
               "model_path": os.path.realpath(os.path.join(args.models, f"pose_landmarker_{variant}.task")),
               "target_fps": 30, "hfov_deg": hfov, "smoothing": args.smoothing}
        job_path = os.path.join(out, f"job_{variant}.json")
        with open(job_path, "w") as fh:
            json.dump(job, fh)
        run([sys.executable, "-m", "ai_mocap_engine.cli", "run", "--job", job_path], env=env)
        eval_dir = os.path.join(out, f"eval_{variant}")
        cmd = [args.blender, "-b", "--factory-startup", "--python", os.path.join(HERE, "evaluate.py"),
               "--", os.path.join(out, "gt.blend"), eng_dir, eval_dir]
        if args.render:
            cmd.append("--render")
        run(cmd)
        with open(os.path.join(eval_dir, "metrics.json")) as fh:
            m = json.load(fh)
        with open(os.path.join(eng_dir, "result.json")) as fh:
            r = json.load(fh)
        summary[variant] = {
            "detected": r["quality"]["detected_ratio"],
            "inverted": r["quality"]["inverted_detections"],
            "recovered": r["quality"]["inverted_recovered"],
            "engine_s": r["timing_s"]["total"],
            "overall_dir_deg": m["overall_direction_error_deg"],
            "rest_baseline_deg": m["overall_rest_baseline_deg"],
            "root_m": m["root_error_m"],
            "per_bone_median_dir": {k: v["median"] for k, v in m["direction_error_deg"].items()},
            "per_bone_median_rot": {k: v["median"] for k, v in m["rotation_error_deg"].items()},
        }
    with open(os.path.join(out, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
