"""汇总若干 run：python analyze.py <run 名前缀>   例：$PY analyze.py abl1_t8
每个 run 一行：成功率、平均调用次数/步数、首次抓取是否抓住、首次放置点到目标物体原点的水平误差、
最终 被移动物体-目标物体 水平距离、每次调用的延迟与 token。"""
import glob, json, os, sys
import numpy as np

prefix = sys.argv[1]
PAIRS = {8: ("akita_black_bowl_1", "plate_1"), 1: ("akita_black_bowl_1", "flat_stove_1_cook_region"),
         4: ("akita_black_bowl_1", "wooden_cabinet_1_top_side"), 6: ("cream_cheese_1", "akita_black_bowl_1")}   # libero_goal
root = os.path.join(os.environ["PROBE_OUT"], "runs")
print("%-28s %7s %6s %6s %9s %12s %12s %8s %9s %8s" % (
    "run", "succ", "calls", "steps", "grasp1_ok", "place1_err", "final_dist", "lat_s", "in_tok", "rsn_tok"))
for run in sorted(glob.glob(os.path.join(root, prefix + "*"))):
    eps = [json.load(open(f)) for f in sorted(glob.glob(run + "/ep*/episode.json"))]
    if not eps:
        continue
    sf = os.path.join(run, "summary.json")      # 任务号优先从 summary 读，没跑完的 run 退回到从名字里解析
    if os.path.exists(sf):
        tid = json.load(open(sf))["args"]["task_id"]
    else:
        parts = os.path.basename(run).split("_t")
        tid = int(parts[1].split("_")[0]) if len(parts) > 1 and parts[1].split("_")[0].isdigit() else 8
    moved, target = PAIRS.get(tid, PAIRS[8])
    if target not in eps[0]["final_objects_world"]:      # 旧 run 没记录区域位置
        continue
    succ = [e["success"] for e in eps]
    g1, p1, fd, lat, tin, trs = [], [], [], [], [], []
    for e in eps:
        o = e["final_objects_world"]
        fd.append(100 * np.linalg.norm(np.array(o[moved][:2]) - np.array(o[target][:2])))
        grasps = [c for c in e["calls"] if c["out"].get("primitive") == "grasp_at" and "exec" in c]   # 直出动作(r1)没有 primitive，这两列为空
        places = [c for c in e["calls"] if c["out"].get("primitive") == "place_at" and "exec" in c]
        if grasps:
            g1.append(grasps[0]["exec"]["gripper_width_after_lift_cm"] > 0.15)
        if places:   # 夹爪目标点 vs 目标物体原点（夹沿时理想值≈碗半径 6cm，所以这只是参考）
            tgt = places[0]["objects_world"].get(target, e["final_objects_world"][target])     # 区域是固定的，用最终记录的位置即可
            p1.append(100 * np.linalg.norm(np.array(places[0]["point_world"][:2]) - np.array(tgt[:2])))
        for c in e["calls"]:
            m = c.get("meta") or {}
            if m.get("usage"):
                lat.append(m["latency_s"]); tin.append(m["usage"]["input_tokens"]); trs.append(m["usage"]["reasoning_output_tokens"])
    f = lambda a, fmt="%.1f": (fmt % np.mean(a)) if len(a) else "-"
    print("%-28s %3d/%-3d %6s %6s %9s %12s %12s %8s %9s %8s" % (
        os.path.basename(run)[-28:], sum(succ), len(succ), f([e["n_calls"] for e in eps]), f([e["steps"] for e in eps], "%.0f"),
        "%d/%d" % (sum(g1), len(g1)), f(p1) + " cm", "%s cm" % f(fd), f(lat), f(tin, "%.0f"), f(trs, "%.0f")))
