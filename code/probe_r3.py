"""R3 级接口探针：模型在图上指像素 + 选 primitive，harness 负责深度反投影和运动。

  --policy gpt     GPT-6 Astra（经 codex exec，走 ChatGPT 订阅）
  --policy oracle  用物体真值位置投影出的像素走同一条 像素->反投影->primitive 通路；
                   它失败 = 执行器有问题，它成功而 gpt 失败 = 模型指点/决策有问题。

输出：$PROBE_OUT/runs/<run>/ep<k>/ 下每次调用一个目录（发给模型的图、prompt、原始事件流、解析结果、
反投影 3D 点、离它最近的真值物体），以及 episode.json、rollout.mp4；run 目录下 summary.json。
"""
import argparse, json, os, subprocess, tempfile, time
import imageio
import numpy as np
from PIL import Image

from geom import Camera, upright
from libero_utils import make_env, reset_to, object_positions

OPEN, CLOSE = -1.0, 1.0

SYSTEM = """You are controlling a Franka Panda arm with a parallel-jaw gripper in a tabletop simulation.
You do NOT output motor commands. Each turn you choose ONE primitive and point at a pixel; a fixed
controller executes it and you then get fresh images.

Images: image 1 is a fixed third-person camera facing the robot across the table ({res}x{res} px).
Image 2 is the wrist camera (context only). Pixel coordinates are (u, v) = (column, row) in IMAGE 1,
origin at the top-left corner, u to the right, v downward.

Primitives:
- grasp_at: the gripper opens, moves above the 3D surface point seen at pixel_uv, descends vertically
  until the fingertips are grasp_depth_cm BELOW that surface point, closes, and lifts.
  The gripper always points straight down. Max finger opening is about 8 cm, and the two fingers close
  toward each other along the LEFT-RIGHT direction of image 1. Objects wider than 8 cm (e.g. bowls) cannot be
  grasped around their body: point at a graspable part such as a rim or handle, chosen so that the
  part ends up between the two fingers.
- place_at: moves the held object above the 3D surface point seen at pixel_uv, descends until the
  fingertips are release_height_cm ABOVE that surface point, opens the gripper, and lifts.
  Note that pixel_uv is where the FINGERTIPS go. If you are holding an object by its rim or edge, the
  object's center is offset from the fingertips, so offset the placement pixel accordingly.
- done: you believe the task is complete.

Be precise with pixels: the point is back-projected with the depth map, so a pixel on the wrong
surface (table vs. object, near rim vs. far rim) gives a wrong 3D target.
Do not run any shell commands or read any files; answer from the images and text only."""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["scene", "rationale", "primitive", "pixel_uv", "grasp_depth_cm", "release_height_cm"],
    "properties": {
        "scene": {"type": "string", "description": "what you see and the current task state"},
        "rationale": {"type": "string", "description": "why this primitive and this pixel"},
        "primitive": {"type": "string", "enum": ["grasp_at", "place_at", "done"]},
        "pixel_uv": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
        "grasp_depth_cm": {"type": "number"},
        "release_height_cm": {"type": "number"},
    },
}


def call_codex(prompt, images, model, effort, call_dir):
    paths = []
    for i, im in enumerate(images):
        p = os.path.join(call_dir, "img%d.png" % i)
        Image.fromarray(im).save(p)
        paths.append(p)
    schema_p, out_p = os.path.join(call_dir, "schema.json"), os.path.join(call_dir, "out.json")
    with open(schema_p, "w") as f:
        json.dump(SCHEMA, f)
    with open(os.path.join(call_dir, "prompt.txt"), "w") as f:
        f.write(prompt)
    sandbox = tempfile.mkdtemp(dir=os.environ.get("PROBE_TMP"))   # 空目录当 cwd，模型无文件可读
    cmd = ["codex", "exec", "-m", model, "-s", "read-only", "--ephemeral", "--skip-git-repo-check",
           "-c", "model_reasoning_effort=" + effort, "--output-schema", schema_p, "-o", out_p, "--json"]
    for p in paths:
        cmd += ["-i", p]
    cmd += ["--", prompt]      # -i 是可变参数，不加 -- 会把 prompt 也吞成图片路径
    for attempt in range(3):
        t0 = time.time()
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=900, cwd=sandbox)
        latency = time.time() - t0
        with open(os.path.join(call_dir, "events.jsonl"), "w") as f:
            f.write(r.stdout)
        if r.returncode == 0 and os.path.exists(out_p):
            events = [json.loads(l) for l in r.stdout.splitlines() if l.startswith("{")]
            usage = next((e.get("usage") for e in events if e.get("type") == "turn.completed"), None)
            kinds = sorted(set(e.get("item", {}).get("type", e.get("type")) for e in events))
            return json.load(open(out_p)), {"latency_s": latency, "usage": usage, "event_kinds": kinds}
        with open(os.path.join(call_dir, "stderr_attempt%d.log" % attempt), "w") as f:
            f.write(r.stderr)
        time.sleep(20 * (attempt + 1))
    raise RuntimeError("codex exec failed 3 times, see " + call_dir)


class Executor:
    """像素 -> 3D -> 末端运动。只用 OSC_POSE 的平移分量，姿态保持初始的竖直向下。"""

    def __init__(self, env, obs, res, max_steps):
        self.env, self.obs, self.res, self.max_steps = env, obs, res, max_steps
        self.cam = Camera(env.sim, "agentview", res, res)
        self.safe_z = float(obs["robot0_eef_pos"][2])
        self.t, self.success, self.frames = 0, False, []

    def images(self):
        return [upright(self.obs["agentview_image"]), upright(self.obs["robot0_eye_in_hand_image"])]

    def _step(self, xyz_action, grip):
        if self.success or self.t >= self.max_steps:
            return
        self.obs, _, done, _ = self.env.step(list(xyz_action) + [0.0, 0.0, 0.0, grip])
        self.t += 1
        self.success = bool(done)
        if self.t % 3 == 0:
            self.frames.append(upright(self.obs["agentview_image"]))

    def goto(self, target, grip, tol=0.006, max_iter=200):
        best, stall = 1e9, 0
        for _ in range(max_iter):
            err = np.asarray(target) - self.obs["robot0_eef_pos"]
            dist = float(np.linalg.norm(err))
            if dist < tol or self.success or self.t >= self.max_steps:
                break
            stall = stall + 1 if dist > best - 5e-4 else 0
            best = min(best, dist)
            if stall > 25:          # 顶到桌面/物体走不动了
                break
            self._step(np.clip(err / 0.04, -1, 1), grip)
        return float(np.linalg.norm(np.asarray(target) - self.obs["robot0_eef_pos"]))

    def hold(self, grip, n=15):
        for _ in range(n):
            self._step([0, 0, 0], grip)

    def gripper_width_cm(self):
        q = self.obs["robot0_gripper_qpos"]
        return float(abs(q[0]) + abs(q[1])) * 100

    def backproject(self, u, v):
        return self.cam.backproject(u, v, self.cam.depth_map(self.obs["agentview_depth"]))

    def grasp_at(self, p, depth_cm):
        x, y, z = p
        self.hold(OPEN, 5)
        self.goto([x, y, self.safe_z], OPEN)
        resid = self.goto([x, y, z - depth_cm / 100.0], OPEN)
        self.hold(CLOSE)
        self.goto([x, y, self.safe_z], CLOSE)
        w = self.gripper_width_cm()
        return {"descend_residual_cm": resid * 100, "gripper_width_after_lift_cm": w}

    def place_at(self, p, height_cm):
        x, y, z = p
        self.goto([x, y, self.safe_z], CLOSE)
        resid = self.goto([x, y, z + height_cm / 100.0], CLOSE)
        self.hold(OPEN)
        self.goto([x, y, self.safe_z], OPEN)
        return {"descend_residual_cm": resid * 100}


def oracle_policy(ex, call_idx, args):
    """真值物体位置 -> 像素。抓取点取物体原点沿图像左右方向（世界 y）偏移 rim_offset，高度抬到 rim_height。"""
    objs = object_positions(ex.obs)
    if call_idx == 0:
        p = objs[args.oracle_grasp] + np.array([0.0, args.rim_offset, args.rim_height])
        (u, v), _ = ex.cam.project(p)
        return {"scene": "", "rationale": "oracle", "primitive": "grasp_at", "pixel_uv": [float(u), float(v)],
                "grasp_depth_cm": args.oracle_depth, "release_height_cm": 0.0}
    if call_idx == 1:
        # 夹的是碗沿，碗心相对夹爪有偏移（提起后碗还会倾斜），用真值量出实际偏移再反向补偿
        off = ex.obs["robot0_eef_pos"] - objs[args.oracle_grasp]
        (u, v), _ = ex.cam.project(objs[args.oracle_place] + np.array([off[0], off[1], 0.0]))
        return {"scene": "", "rationale": "oracle", "primitive": "place_at", "pixel_uv": [float(u), float(v)],
                "grasp_depth_cm": 0.0, "release_height_cm": args.oracle_release}
    return {"scene": "", "rationale": "oracle", "primitive": "done", "pixel_uv": [0.0, 0.0],
            "grasp_depth_cm": 0.0, "release_height_cm": 0.0}


def run_episode(env, init_state, instruction, args, ep_dir):
    obs = reset_to(env, init_state)
    ex = Executor(env, obs, args.res, args.max_steps)
    history, calls = [], []
    for ci in range(args.max_calls):
        call_dir = os.path.join(ep_dir, "call%02d" % ci)
        os.makedirs(call_dir)
        objs_before = object_positions(ex.obs)
        if args.policy == "gpt":
            prompt = SYSTEM.format(res=args.res) + "\n\nTask: %s\nTurn %d of at most %d.\nGripper opening now: %.1f cm.\nPrevious turns:\n%s" % (
                instruction, ci + 1, args.max_calls, ex.gripper_width_cm(),
                "\n".join(history) if history else "(none)")
            out, meta = call_codex(prompt, ex.images(), args.model, args.effort, call_dir)
        else:
            out, meta = oracle_policy(ex, ci, args), {}
            for i, im in enumerate(ex.images()):
                Image.fromarray(im).save(os.path.join(call_dir, "img%d.png" % i))
        rec = {"call": ci, "t_before": ex.t, "out": out, "meta": meta}
        if out["primitive"] == "done":
            calls.append(rec)
            break
        u, v = [float(np.clip(c, 0, args.res - 1)) for c in out["pixel_uv"]]
        p = ex.backproject(u, v)
        near = min(objs_before.items(), key=lambda kv: np.linalg.norm(kv[1] - p))
        rec.update({"point_world": p.tolist(), "nearest_object": near[0],
                    "nearest_object_dist_cm": float(np.linalg.norm(near[1] - p)) * 100,
                    "objects_world": {k: v_.tolist() for k, v_ in objs_before.items()}})
        if out["primitive"] == "grasp_at":
            res = ex.grasp_at(p, float(np.clip(out["grasp_depth_cm"], 0, 8)))
            fb = "gripper opening after lifting = %.1f cm (about 0 means nothing is held)" % res["gripper_width_after_lift_cm"]
        else:
            res = ex.place_at(p, float(np.clip(out["release_height_cm"], 0, 15)))
            fb = "released"
        rec.update({"exec": res, "t_after": ex.t, "success_after": ex.success})
        calls.append(rec)
        history.append("%d. %s at pixel (%.0f, %.0f) -> %s" % (ci + 1, out["primitive"], u, v, fb))
        with open(os.path.join(call_dir, "record.json"), "w") as f:
            json.dump(rec, f, indent=1)
        if ex.success or ex.t >= args.max_steps:
            break
    ex.hold(OPEN, 10)      # 放手后物体落稳，成功判定可能在这几步才触发
    final = object_positions(ex.obs)
    summary = {"final_objects_world": {k: v_.tolist() for k, v_ in final.items()}, "success": ex.success, "steps": ex.t, "n_calls": len(calls), "instruction": instruction, "calls": calls}
    with open(os.path.join(ep_dir, "episode.json"), "w") as f:
        json.dump(summary, f, indent=1)
    if ex.frames:
        imageio.mimwrite(os.path.join(ep_dir, "rollout.mp4"), ex.frames, fps=10)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default="libero_goal")
    ap.add_argument("--task-id", type=int, required=True)
    ap.add_argument("--episodes", type=int, default=2)
    ap.add_argument("--policy", choices=["gpt", "oracle"], default="gpt")
    ap.add_argument("--model", default="gpt-6-astra")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--res", type=int, default=512)
    ap.add_argument("--max-calls", type=int, default=6)
    ap.add_argument("--max-steps", type=int, default=900)
    ap.add_argument("--run-name", default=None)
    ap.add_argument("--oracle-grasp", default="akita_black_bowl_1")
    ap.add_argument("--oracle-place", default="plate_1")
    ap.add_argument("--rim-offset", type=float, default=0.0)
    ap.add_argument("--rim-height", type=float, default=0.0)
    ap.add_argument("--oracle-depth", type=float, default=2.0)
    ap.add_argument("--oracle-release", type=float, default=6.0)
    args = ap.parse_args()

    run = args.run_name or "%s_%s_t%d_%s" % (time.strftime("%m%d_%H%M%S"), args.suite, args.task_id, args.policy)
    run_dir = os.path.join(os.environ["PROBE_OUT"], "runs", run)
    os.makedirs(run_dir)
    env, instruction, inits = make_env(args.suite, args.task_id, args.res)
    print("task:", instruction, "| run dir:", run_dir, flush=True)
    results = []
    for ep in range(args.episodes):
        ep_dir = os.path.join(run_dir, "ep%03d" % ep)
        os.makedirs(ep_dir)
        s = run_episode(env, inits[ep], instruction, args, ep_dir)
        results.append(s["success"])
        print("ep %d: success=%s steps=%d calls=%d" % (ep, s["success"], s["steps"], s["n_calls"]), flush=True)
        for c in s["calls"]:
            if "point_world" in c:
                print("   %-9s uv=(%.0f,%.0f) -> nearest %s (%.1f cm) %s" % (
                    c["out"]["primitive"], c["out"]["pixel_uv"][0], c["out"]["pixel_uv"][1],
                    c["nearest_object"], c["nearest_object_dist_cm"], json.dumps(c["exec"])), flush=True)
    with open(os.path.join(run_dir, "summary.json"), "w") as f:
        json.dump({"args": vars(args), "instruction": instruction, "success": results,
                   "success_rate": float(np.mean(results))}, f, indent=1)
    print("success rate: %d/%d" % (sum(results), len(results)))


if __name__ == "__main__":
    main()
