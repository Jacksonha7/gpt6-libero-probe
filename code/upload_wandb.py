"""把探针 run 上传到 wandb：每个 run 目录 = 一个 wandb run。
内容：config（命令行参数）、汇总指标、每个 episode 的回放视频、逐次调用表（发给模型的图、模型输出、
rationale、reasoning summary、反投影点与真值的误差、延迟、token）。
用法（用 openpi 的 venv，它有 wandb）：
  source env.sh && $WANDB_PY upload_wandb.py <run 名前缀> [--project gpt6-libero-probe] [--force]
已上传的 run 会在目录里留 .wandb_uploaded，默认跳过。"""
import argparse, glob, json, os
import numpy as np
import wandb

ap = argparse.ArgumentParser()
ap.add_argument("prefix")
ap.add_argument("--project", default="gpt6-libero-probe")
ap.add_argument("--force", action="store_true")
a = ap.parse_args()
root = os.path.join(os.environ["PROBE_OUT"], "runs")

for run_dir in sorted(glob.glob(os.path.join(root, a.prefix + "*"))):
    name, marker = os.path.basename(run_dir), os.path.join(run_dir, ".wandb_uploaded")
    sfile = os.path.join(run_dir, "summary.json")
    if not os.path.exists(sfile):
        print("skip (未跑完):", name); continue
    if os.path.exists(marker) and not a.force:
        print("skip (已上传):", name); continue
    summ = json.load(open(sfile))
    cfg = dict(summ["args"], instruction=summ["instruction"])
    run = wandb.init(project=a.project, name=name, config=cfg, dir=os.environ["PROBE_OUT"], reinit=True,
                     tags=[cfg["policy"], cfg.get("interface", "r3"), "%s_t%d" % (cfg["suite"], cfg["task_id"])],
                     group="%s_t%d" % (cfg["suite"], cfg["task_id"]))
    cols = ["episode", "call", "primitive", "target", "image", "scene", "rationale", "reasoning_summary",
            "nearest_object", "nearest_dist_cm", "exec", "success_after", "latency_s", "input_tokens", "reasoning_tokens"]
    table, lat, rsn, calls, steps = wandb.Table(columns=cols), [], [], [], []
    for ep_dir in sorted(glob.glob(run_dir + "/ep*")):
        e = json.load(open(os.path.join(ep_dir, "episode.json")))
        ep = int(os.path.basename(ep_dir)[2:])
        calls.append(e["n_calls"]); steps.append(e["steps"])
        log = {"episode": ep, "ep/success": int(e["success"]), "ep/steps": e["steps"], "ep/n_calls": e["n_calls"]}
        mp4 = os.path.join(ep_dir, "rollout.mp4")
        if os.path.exists(mp4):
            log["rollout"] = wandb.Video(mp4, caption="ep%d %s" % (ep, "SUCCESS" if e["success"] else "FAIL"), format="mp4")
        wandb.log(log)
        for c in e["calls"]:
            o, m = c["out"], c.get("meta") or {}
            u = m.get("usage") or {}
            if m.get("latency_s"):
                lat.append(m["latency_s"]); rsn.append(u.get("reasoning_output_tokens", 0))
            img = os.path.join(ep_dir, "call%02d" % c["call"], "img0.png")
            table.add_data(ep, c["call"], o.get("primitive", "abs_target" if "steps" in o else "raw_actions"), json.dumps(o.get("pixel_uv", o.get("target_xyz", o.get("actions")))),
                           wandb.Image(img) if os.path.exists(img) else None, o.get("scene", ""), o.get("rationale", ""),
                           " | ".join(m.get("reasoning_summary") or []), c.get("nearest_object"),
                           c.get("nearest_object_dist_cm"), json.dumps(c.get("exec")), c.get("success_after"),
                           m.get("latency_s"), u.get("input_tokens"), u.get("reasoning_output_tokens"))
    wandb.log({"calls": table})
    run.summary.update({"success_rate": summ["success_rate"], "n_episodes": len(summ["success"]),
                        "n_success": int(sum(summ["success"])), "mean_calls": float(np.mean(calls)),
                        "mean_steps": float(np.mean(steps)), "mean_latency_s": float(np.mean(lat)) if lat else None,
                        "mean_reasoning_tokens": float(np.mean(rsn)) if rsn else None})
    url = run.get_url(); run.finish()
    open(marker, "w").write(url + "\n"); print("uploaded:", name, url)
