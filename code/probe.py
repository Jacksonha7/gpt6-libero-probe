"""R3 / R2 级接口探针（probe_r3.py 的超集，那个文件保留作最初版本的记录）。
R3：模型在图上指像素 + 选 primitive，harness 负责深度反投影和运动。

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
from libero_utils import make_env, reset_to, object_positions, region_positions

OPEN, CLOSE = -1.0, 1.0

HEAD = """You are controlling a Franka Panda arm with a parallel-jaw gripper in a tabletop simulation.
You do NOT output motor commands. Each turn you choose ONE primitive and give its target; a fixed
controller executes it and you then get fresh images.

Images: image 1 is a fixed third-person camera facing the robot across the table ({res}x{res} px).
Image 2 is the wrist camera (context only).
The gripper always points straight down. Max finger opening is about 8 cm, and the two fingers close
toward each other along the LEFT-RIGHT direction of image 1.
"""

R3_BODY = """Targets are pixels (u, v) = (column, row) in IMAGE 1, origin at the top-left corner, u to the right,
v downward. The pixel is back-projected to a 3D surface point with the depth map, so a pixel on the wrong
surface (table vs. object, near rim vs. far rim) gives a wrong 3D target.

Primitives:
- grasp_at: the gripper opens, moves above the 3D surface point seen at pixel_uv, descends vertically
  until the fingertips are grasp_depth_cm BELOW that surface point, closes, and lifts.
{hint_grasp}- place_at: moves the held object above the 3D surface point seen at pixel_uv, descends until the
  fingertips are release_height_cm ABOVE that surface point, opens the gripper, and lifts.
{hint_place}- done: you believe the task is complete.
"""

HINT_GRASP = """  Objects wider than 8 cm (e.g. bowls) cannot be grasped around their body: point at a graspable part
  such as a rim or handle, chosen so that the part ends up between the two fingers.
"""
HINT_PLACE = """  Note that pixel_uv is where the FINGERTIPS go. If you are holding an object by its rim or edge, the
  object's center is offset from the fingertips, so offset the placement pixel accordingly.
"""

R2_BODY = """Targets are metric 3D positions target_xyz = [x, y, z] in meters in the WORLD frame:
+x points from the robot toward the camera (downward in image 1), +y points to the RIGHT in image 1, +z is up.
The robot base is at {base}. The fingertips are currently at {eef}.
You must estimate object positions in this frame yourself{state_note}.

Primitives:
- grasp_at: the gripper opens, moves above target_xyz, descends vertically until the fingertips are AT
  target_xyz, closes, and lifts.
- place_at: moves the held object above target_xyz, descends until the fingertips are AT target_xyz,
  opens the gripper, and lifts.
- done: you believe the task is complete.
"""

R1_BODY = """You output LOW-LEVEL ACTIONS directly. There are no primitives and no helper controller: the numbers
you output are fed step by step to the robot's end-effector controller (20 Hz), exactly like a learned
visuomotor policy would.

Each action is 7 numbers [dx, dy, dz, droll, dpitch, dyaw, gripper], each in [-1, 1]:
- dx, dy, dz: end-effector velocity command in the WORLD frame. +x points from the robot toward the camera
  (downward in image 1), +y points to the RIGHT in image 1, +z is up. Measured response: at steady state one
  step moves the fingertips about 1.3 cm x value along that axis (value 1.0 for 10 steps = about 12 cm;
  value 0.2 for 10 steps = about 2.5 cm). There is about one step of lag, and after a full-speed move the
  arm coasts about 1 cm further.
- droll, dpitch, dyaw: rotation commands. The gripper starts pointing straight down; keep these 0 unless you
  need to rotate.
- gripper: -1 opens, +1 closes. It must be held every step (keep +1 while carrying). Closing fully takes
  about 10 steps.
The fingertips are currently at {eef} (meters, world frame); the robot base is at {base}.
{state_note}
Each turn, output between 1 and {chunk} actions; they are executed open-loop, then you get fresh images and
the measured fingertip displacement. Set done=true (with an empty or short action list) only when the task
is complete. You have at most {max_calls} turns and {max_steps} steps in total, so do not waste steps.
"""

SIDE_NOTE = """Image 3 is a SIDE camera whose viewing direction is perpendicular to image 1: it looks along the world -y axis.
In image 3 the robot is on the right; world +x (toward the image-1 camera) points to the LEFT, +z is up, and +y
points toward the image-3 viewer. Use it to judge distances along x, which image 1 cannot resolve well.
"""

R1ABS_BODY = """You control the arm by giving ABSOLUTE fingertip targets. Each turn you output one target position
target_xyz = [x, y, z] in meters in the WORLD frame, a gripper command, and how many control steps (1-5, 20 Hz)
to spend moving toward it. A simple bounded controller moves the fingertips toward the target for that many
steps (it may not arrive), then you get fresh images, the MEASURED fingertip position and the remaining error.
World frame: +x points from the robot toward the camera (downward in image 1), +y points to the RIGHT in
image 1, +z is up. The robot base is at {base}. The fingertips are currently at {eef} (measured).
The target must be within 5 cm of the current measured fingertip position, otherwise it is rejected and
nothing moves. The gripper always points straight down. gripper_closed=true closes (takes about 10 steps to
close fully; keep it true while carrying), false opens.
{state_note}
Set done=true only when the task is complete. You have at most {max_calls} turns and {max_steps} steps.
"""

TAIL = "Do not run any shell commands or read any files; answer from the images and text only."


def build_system(args, ex):
    text = _build_system(args, ex)
    if args.wrist_hint:       # GPT-Policy 复现里观察到：模型靠腕部相机确认对准。原 prompt 把它标成 context only，这里改成鼓励使用
        text = text.replace("Image 2 is the wrist camera (context only).",
                            "Image 2 is the wrist camera, mounted on the gripper and looking down past the fingertips. "
                            "Use it actively: before descending or closing, check in image 2 that the target part is centered between the two fingers, and correct the position if it is not.")
    if args.history_images:
        text = text.replace("\nThe gripper always points", "\nAny images after these are image-1 views from your previous turns (oldest first, half resolution), so you can see how the scene changed after your earlier commands.\nThe gripper always points", 1)
    if "sideview" in args.extra_cams:
        text = text.replace("\nThe gripper always points", "\n" + SIDE_NOTE.strip() + "\nThe gripper always points", 1)
    return text


def _build_system(args, ex):
    head = HEAD.format(res=args.res)
    if args.interface == "r1abs":
        base = np.round(ex.env.sim.data.body_xpos[ex.env.sim.model.body_name2id("robot0_base")], 3).tolist()
        note = "You must judge where things are from the images."
        if args.oracle_state:
            objs = {k: np.round(v, 3).tolist() for k, v in object_positions(ex.obs).items()}
            regs = {k: np.round(v, 3).tolist() for k, v in region_positions(ex.env).items()}
            note = "Ground-truth object origins right now (meters, world frame): " + json.dumps(objs) + ". Named regions: " + json.dumps(regs)
        body = R1ABS_BODY.format(eef=np.round(ex.obs["robot0_eef_pos"], 3).tolist(), base=base, state_note=note,
                                 max_calls=args.max_calls, max_steps=args.max_steps)
        head = HEAD.format(res=args.res).replace("Each turn you choose ONE primitive and give its target; a fixed\ncontroller executes it and you then get fresh images.", "").replace("You do NOT output motor commands. ", "")
        return head + "\n" + body + "\n" + TAIL
    if args.interface == "r1":
        base = np.round(ex.env.sim.data.body_xpos[ex.env.sim.model.body_name2id("robot0_base")], 3).tolist()
        note = "You must judge where things are from the images."
        if args.oracle_state:
            objs = {k: np.round(v, 3).tolist() for k, v in object_positions(ex.obs).items()}
            regs = {k: np.round(v, 3).tolist() for k, v in region_positions(ex.env).items()}
            note = ("Ground-truth object origins right now (meters, world frame; an origin is roughly the center of the "
                    "object's base): " + json.dumps(objs) + ". Centers of named regions on fixtures: " + json.dumps(regs))
        body = R1_BODY.format(eef=np.round(ex.obs["robot0_eef_pos"], 3).tolist(), base=base, state_note=note,
                              chunk=args.chunk, max_calls=args.max_calls, max_steps=args.max_steps)
        return HEAD.format(res=args.res).replace("Each turn you choose ONE primitive and give its target; a fixed\ncontroller executes it and you then get fresh images.", "").replace("You do NOT output motor commands. ", "") + "\n" + body + "\n" + TAIL
    if args.interface == "r3":
        hint = args.prompt_style == "full"
        body = R3_BODY.format(hint_grasp=HINT_GRASP if hint else "", hint_place=HINT_PLACE if hint else "")
    else:
        base = np.round(ex.env.sim.data.body_xpos[ex.env.sim.model.body_name2id("robot0_base")], 3).tolist()
        eef = np.round(ex.obs["robot0_eef_pos"], 3).tolist()
        note = ""
        if args.oracle_state:
            objs = {k: np.round(v, 3).tolist() for k, v in object_positions(ex.obs).items()}
            regs = {k: np.round(v, 3).tolist() for k, v in region_positions(ex.env).items()}
            note = (". Ground-truth object origins (meters, world frame; an origin is roughly the center of the object's base): "
                    + json.dumps(objs) + ". Centers of named regions on fixtures: " + json.dumps(regs))
        body = R2_BODY.format(base=base, eef=eef, state_note=note)
    return head + "\n" + body + "\n" + TAIL


def build_schema(interface, chunk=10):
    if interface == "r1abs":
        props = {"scene": {"type": "string"}, "rationale": {"type": "string"},
                 "target_xyz": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                 "gripper_closed": {"type": "boolean"}, "steps": {"type": "integer", "minimum": 1, "maximum": 5},
                 "done": {"type": "boolean"}}
        return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}
    if interface == "r1":
        props = {"scene": {"type": "string", "description": "what you see and the current task state"},
                 "rationale": {"type": "string", "description": "what this chunk of actions is meant to achieve"},
                 "actions": {"type": "array", "minItems": 0, "maxItems": chunk,
                             "items": {"type": "array", "minItems": 7, "maxItems": 7, "items": {"type": "number"}}},
                 "done": {"type": "boolean"}}
        return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}
    props = {
        "scene": {"type": "string", "description": "what you see and the current task state"},
        "rationale": {"type": "string", "description": "why this primitive and this target"},
        "primitive": {"type": "string", "enum": ["grasp_at", "place_at", "done"]},
    }
    if interface == "r3":
        props.update({"pixel_uv": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                      "grasp_depth_cm": {"type": "number"}, "release_height_cm": {"type": "number"}})
    else:
        props["target_xyz"] = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


def call_codex(prompt, images, model, effort, call_dir, schema):
    paths = []
    for i, im in enumerate(images):
        p = os.path.join(call_dir, "img%d.png" % i)
        Image.fromarray(im).save(p)
        paths.append(p)
    schema_p, out_p = os.path.join(call_dir, "schema.json"), os.path.join(call_dir, "out.json")
    with open(schema_p, "w") as f:
        json.dump(schema, f)
    with open(os.path.join(call_dir, "prompt.txt"), "w") as f:
        f.write(prompt)
    sandbox = tempfile.mkdtemp(dir=os.environ.get("PROBE_TMP"))   # 空目录当 cwd，模型无文件可读
    cmd = ["codex", "exec", "-m", model, "-s", "read-only", "--ephemeral", "--skip-git-repo-check",
           "-c", "model_reasoning_effort=" + effort, "-c", "model_reasoning_summary=detailed",
           "--output-schema", schema_p, "-o", out_p, "--json"]
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
            reasoning = [e["item"].get("text", "") for e in events if e.get("item", {}).get("type") == "reasoning"]
            return json.load(open(out_p)), {"latency_s": latency, "usage": usage, "event_kinds": kinds,
                                            "reasoning_summary": reasoning}   # 只有小标题，原始思维链拿不到
        with open(os.path.join(call_dir, "stderr_attempt%d.log" % attempt), "w") as f:
            f.write(r.stderr)
        time.sleep(20 * (attempt + 1))
    raise RuntimeError("codex exec failed 3 times, see " + call_dir)


class Executor:
    """像素 -> 3D -> 末端运动。只用 OSC_POSE 的平移分量，姿态保持初始的竖直向下。"""

    def __init__(self, env, obs, res, max_steps, extra_cams=()):
        self.env, self.obs, self.res, self.max_steps, self.extra_cams = env, obs, res, max_steps, list(extra_cams)
        self.cam = Camera(env.sim, "agentview", res, res)
        self.safe_z = float(obs["robot0_eef_pos"][2]) + 0.10   # 夹着的碗会垂到指尖下方约 6 cm，要能越过 1.13 m 高的柜顶
        self.t, self.success, self.frames = 0, False, []
        self.past_views = []          # 每次调用时的主相机图，供 --history-images 使用

    def images(self, n_history=0):
        cur = [upright(self.obs["agentview_image"]), upright(self.obs["robot0_eye_in_hand_image"])] + \
              [upright(self.obs[c + "_image"]) for c in self.extra_cams]
        hist = self.past_views[-n_history:] if n_history else []
        self.past_views.append(cur[0])
        return cur + [v[::2, ::2] for v in hist]        # 历史图降到一半分辨率

    def _step(self, xyz_action, grip):
        if self.success or self.t >= self.max_steps:
            return
        self.obs, _, done, _ = self.env.step(list(xyz_action) + [0.0, 0.0, 0.0, grip])
        self.t += 1
        self.success = bool(done)
        if self.t % 3 == 0:
            self.frames.append(upright(self.obs["agentview_image"]))

    def raw(self, actions):
        """直出动作：逐步原样送进 env.step（只做 [-1,1] 裁剪），不经过任何 P 控制。"""
        p0 = self.obs["robot0_eef_pos"].copy()
        n = 0
        for a in actions:
            if self.success or self.t >= self.max_steps:
                break
            a = np.clip(np.asarray(a, dtype=float), -1, 1)
            self.obs, _, done, _ = self.env.step(a.tolist())
            self.t += 1; n += 1
            self.success = bool(done)
            if self.t % 3 == 0:
                self.frames.append(upright(self.obs["agentview_image"]))
        return {"steps_executed": n, "eef_moved_cm": np.round(100 * (self.obs["robot0_eef_pos"] - p0), 1).tolist(),
                "eef_now": np.round(self.obs["robot0_eef_pos"], 3).tolist(), "gripper_width_cm": round(self.gripper_width_cm(), 1)}

    def toward(self, target, closed, steps):
        """绝对目标接口：目标离实测位置 >5 cm 则拒绝；否则用有界 P 控制朝目标走 steps 步（不保证到达）。"""
        target = np.asarray(target, dtype=float); p0 = self.obs["robot0_eef_pos"].copy()
        far = float(np.linalg.norm(target - p0))
        if far > 0.05 + 1e-6:
            return {"rejected": "target is %.1f cm from the measured fingertip position; the limit is 5 cm" % (far * 100),
                    "steps_executed": 0, "eef_now": np.round(p0, 3).tolist(), "gripper_width_cm": round(self.gripper_width_cm(), 1)}
        n = 0
        for _ in range(int(steps)):
            if self.success or self.t >= self.max_steps:
                break
            err = target - self.obs["robot0_eef_pos"]
            self.obs, _, done, _ = self.env.step(np.clip(err / 0.02, -1, 1).tolist() + [0.0, 0.0, 0.0, CLOSE if closed else OPEN])
            self.t += 1; n += 1; self.success = bool(done)
            if self.t % 3 == 0:
                self.frames.append(upright(self.obs["agentview_image"]))
        now = self.obs["robot0_eef_pos"]
        return {"steps_executed": n, "eef_moved_cm": np.round(100 * (now - p0), 1).tolist(), "eef_now": np.round(now, 3).tolist(),
                "remaining_error_cm": np.round(100 * (target - now), 1).tolist(), "gripper_width_cm": round(self.gripper_width_cm(), 1)}

    def goto(self, target, grip, tol=0.006, max_iter=400):
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
            lim = 0.4 if grip == CLOSE else 1.0          # 夹着物体时限速，碗沿这种薄边抓取快了会滑脱
            self._step(np.clip(err / 0.04, -lim, lim), grip)
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


def pixel_for_xy(ex, target, radius=40, stride=2, dims=2):
    (u0, v0), _ = ex.cam.project(target)
    depth = ex.cam.depth_map(ex.obs["agentview_depth"])
    best, best_d = (float(u0), float(v0)), 1e9
    for v in np.arange(v0 - radius, v0 + radius + 1, stride):
        for u in np.arange(u0 - radius, u0 + radius + 1, stride):
            if 0 <= u < ex.res and 0 <= v < ex.res:
                d = np.linalg.norm(ex.cam.backproject(u, v, depth)[:dims] - np.asarray(target)[:dims])
                if d < best_d:
                    best, best_d = (float(u), float(v)), d
    return best


def oracle_policy(ex, call_idx, args):
    """真值物体位置 -> 像素。抓取点取物体原点沿图像左右方向（世界 y）偏移 rim_offset，高度抬到 rim_height。"""
    objs = dict(object_positions(ex.obs), **region_positions(ex.env))
    if call_idx == 0:
        p = objs[args.oracle_grasp] + np.array([0.0, args.rim_offset, args.rim_height])
        u, v = pixel_for_xy(ex, p, dims=3)      # 直接投影的像素常反投影到碗沿后面的桌面上，所以按 3D 距离搜
        return {"scene": "", "rationale": "oracle", "primitive": "grasp_at", "pixel_uv": [float(u), float(v)],
                "grasp_depth_cm": args.oracle_depth, "release_height_cm": 0.0}
    if call_idx == 1:
        # 夹的是碗沿，碗心相对夹爪有偏移（提起后碗还会倾斜），用真值量出实际偏移再反向补偿
        off = ex.obs["robot0_eef_pos"] - objs[args.oracle_grasp]
        u, v = pixel_for_xy(ex, objs[args.oracle_place] + np.array([off[0], off[1], 0.0]))
        return {"scene": "", "rationale": "oracle", "primitive": "place_at", "pixel_uv": [float(u), float(v)],
                "grasp_depth_cm": 0.0, "release_height_cm": args.oracle_release}
    return {"scene": "", "rationale": "oracle", "primitive": "done", "pixel_uv": [0.0, 0.0],
            "grasp_depth_cm": 0.0, "release_height_cm": 0.0}


def run_episode(env, init_state, instruction, args, ep_dir):
    obs = reset_to(env, init_state)
    ex = Executor(env, obs, args.res, args.max_steps, args.extra_cams)
    history, calls = [], []
    for ci in range(args.max_calls):
        call_dir = os.path.join(ep_dir, "call%02d" % ci)
        os.makedirs(call_dir)
        objs_before = object_positions(ex.obs)
        if args.policy == "gpt":
            prompt = build_system(args, ex) + "\n\nTask: %s\nTurn %d of at most %d.\nGripper opening now: %.1f cm.\nPrevious turns:\n%s" % (
                instruction, ci + 1, args.max_calls, ex.gripper_width_cm(),
                "\n".join(history) if history else "(none)")
            out, meta = call_codex(prompt, ex.images(args.history_images), args.model, args.effort, call_dir, build_schema(args.interface, args.chunk))
        else:
            out, meta = oracle_policy(ex, ci, args), {}
            for i, im in enumerate(ex.images()):
                Image.fromarray(im).save(os.path.join(call_dir, "img%d.png" % i))
        rec = {"call": ci, "t_before": ex.t, "out": out, "meta": meta}
        if args.interface == "r1abs":
            res = ex.toward(out["target_xyz"], out["gripper_closed"], out["steps"])
            rec.update({"exec": res, "t_after": ex.t, "success_after": ex.success,
                        "objects_world": {k: v_.tolist() for k, v_ in objs_before.items()}})
            calls.append(rec)
            if "rejected" in res:
                history.append("%d. REJECTED: %s" % (ci + 1, res["rejected"]))
            else:
                history.append("%d. %s | target %s, gripper_closed=%s, %d steps -> measured fingertips now %s, remaining error %s cm, gripper opening %.1f cm" % (
                    ci + 1, out["rationale"][:80], np.round(out["target_xyz"], 3).tolist(), out["gripper_closed"], res["steps_executed"],
                    res["eef_now"], res["remaining_error_cm"], res["gripper_width_cm"]))
            history[:] = history[-8:]
            with open(os.path.join(call_dir, "record.json"), "w") as f:
                json.dump(rec, f, indent=1)
            if ex.success or ex.t >= args.max_steps or out["done"]:
                break
            continue
        if args.interface == "r1":
            res = ex.raw(out["actions"])
            rec.update({"exec": res, "t_after": ex.t, "success_after": ex.success,
                        "objects_world": {k: v_.tolist() for k, v_ in objs_before.items()}})
            calls.append(rec)
            history.append("%d. %s | executed %d steps, fingertips moved %s cm -> now at %s, gripper opening %.1f cm" % (
                ci + 1, out["rationale"][:90], res["steps_executed"], res["eef_moved_cm"], res["eef_now"], res["gripper_width_cm"]))
            history[:] = history[-8:]
            with open(os.path.join(call_dir, "record.json"), "w") as f:
                json.dump(rec, f, indent=1)
            if ex.success or ex.t >= args.max_steps or out["done"]:
                break
            continue
        if out["primitive"] == "done":
            calls.append(rec)
            break
        if args.interface == "r3":
            u, v = [float(np.clip(c, 0, args.res - 1)) for c in out["pixel_uv"]]
            p = ex.backproject(u, v)
            depth_cm, height_cm = float(np.clip(out["grasp_depth_cm"], 0, 8)), float(np.clip(out["release_height_cm"], 0, 15))
            where = "pixel (%.0f, %.0f)" % (u, v)
        else:
            p = np.clip(np.asarray(out["target_xyz"], dtype=float), [-0.6, -0.6, 0.85], [0.4, 0.6, 1.4])   # 工作空间限幅
            depth_cm, height_cm = 0.0, 0.0
            where = "xyz %s" % np.round(p, 3).tolist()
        near = min(objs_before.items(), key=lambda kv: np.linalg.norm(kv[1] - p))
        rec.update({"point_world": p.tolist(), "nearest_object": near[0],
                    "nearest_object_dist_cm": float(np.linalg.norm(near[1] - p)) * 100,
                    "objects_world": {k: v_.tolist() for k, v_ in objs_before.items()}})
        if out["primitive"] == "grasp_at":
            res = ex.grasp_at(p, depth_cm)
            fb = "gripper opening after lifting = %.1f cm (about 0 means nothing is held)" % res["gripper_width_after_lift_cm"]
        else:
            res = ex.place_at(p, height_cm)
            fb = "released"
        rec.update({"exec": res, "t_after": ex.t, "success_after": ex.success})
        calls.append(rec)
        history.append("%d. %s at %s -> %s" % (ci + 1, out["primitive"], where, fb))
        with open(os.path.join(call_dir, "record.json"), "w") as f:
            json.dump(rec, f, indent=1)
        if ex.success or ex.t >= args.max_steps:
            break
    if args.interface not in ("r1", "r1abs"):
        ex.hold(OPEN, 10)      # 放手后物体落稳，成功判定可能在这几步才触发
    final = dict(object_positions(ex.obs), **region_positions(env))
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
    ap.add_argument("--chunk", type=int, default=10, help="r1：每次调用最多输出几步动作")
    ap.add_argument("--interface", choices=["r3", "r2", "r1", "r1abs"], default="r3", help="r1=直出 7 维动作，不经过任何控制程序；r3=指像素+深度反投影；r2=直接报世界系米制坐标")
    ap.add_argument("--prompt-style", choices=["full", "nohint"], default="full", help="r3 专用：nohint 去掉 夹碗沿/放置补偿 两条提示")
    ap.add_argument("--oracle-state", action="store_true", help="r2/r1：把物体真值坐标写进 prompt")
    ap.add_argument("--ep-start", type=int, default=0)
    ap.add_argument("--history-images", type=int, default=0, help="额外附上前 N 次调用时的主相机图（模拟持久对话里能看到历史图像）")
    ap.add_argument("--wrist-hint", action="store_true", help="把腕部相机的说明从 context only 改成鼓励用它检查对准")
    ap.add_argument("--extra-cams", nargs="*", default=[], help="额外发给模型的相机，目前支持 sideview")
    ap.add_argument("--res", type=int, default=512)
    ap.add_argument("--max-calls", type=int, default=6)
    ap.add_argument("--max-steps", type=int, default=900)
    ap.add_argument("--run-name", default=None)
    ap.add_argument("--oracle-grasp", default="akita_black_bowl_1")
    ap.add_argument("--oracle-place", default="plate_1")
    ap.add_argument("--rim-offset", type=float, default=0.0)
    ap.add_argument("--rim-height", type=float, default=0.0)
    ap.add_argument("--oracle-depth", type=float, default=1.5)
    ap.add_argument("--oracle-release", type=float, default=6.0)
    args = ap.parse_args()

    run = args.run_name or "%s_%s_t%d_%s" % (time.strftime("%m%d_%H%M%S"), args.suite, args.task_id, args.policy)
    run_dir = os.path.join(os.environ["PROBE_OUT"], "runs", run)
    os.makedirs(run_dir, exist_ok=True)       # 支持断点续跑：已有 episode.json 的回合跳过，半截的回合目录删掉重跑
    env, instruction, inits = make_env(args.suite, args.task_id, args.res, extra_cams=args.extra_cams)
    print("task:", instruction, "| run dir:", run_dir, flush=True)
    results = []
    for ep in range(args.ep_start, args.ep_start + args.episodes):
        ep_dir = os.path.join(run_dir, "ep%03d" % ep)
        if os.path.exists(os.path.join(ep_dir, "episode.json")):
            s = json.load(open(os.path.join(ep_dir, "episode.json")))
            results.append(s["success"])
            print("ep %d: (已完成，跳过) success=%s" % (ep, s["success"]), flush=True)
            continue
        if os.path.exists(ep_dir):
            import shutil
            shutil.rmtree(ep_dir)
        os.makedirs(ep_dir)
        s = run_episode(env, inits[ep], instruction, args, ep_dir)
        results.append(s["success"])
        print("ep %d: success=%s steps=%d calls=%d" % (ep, s["success"], s["steps"], s["n_calls"]), flush=True)
        for c in s["calls"]:
            if "steps" in c["out"]:
                pass
            elif "actions" in c["out"]:
                print("   r1 call %d: %s | %s" % (c["call"], json.dumps(c["exec"]), c["out"]["rationale"][:80]), flush=True)
            elif "point_world" in c:
                print("   %-9s %s -> nearest %s (%.1f cm) %s" % (
                    c["out"]["primitive"], c["out"].get("pixel_uv", c["out"].get("target_xyz")),
                    c["nearest_object"], c["nearest_object_dist_cm"], json.dumps(c["exec"])), flush=True)
    with open(os.path.join(run_dir, "summary.json"), "w") as f:
        json.dump({"args": vars(args), "instruction": instruction, "success": results,
                   "success_rate": float(np.mean(results))}, f, indent=1)
    print("success rate: %d/%d" % (sum(results), len(results)))


if __name__ == "__main__":
    main()
