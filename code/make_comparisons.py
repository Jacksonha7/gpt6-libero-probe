"""把若干回合的回放拼成左右并排的对照视频（同一任务、尽量同一初始状态）。输出到 $PROBE_OUT/report/cmp_*.mp4。
视频里的标签用英文（集群上没有中文字体），中文说明写在报告网页里。"""
import json, os
import imageio, numpy as np
from PIL import Image, ImageDraw, ImageFont
R, O = os.environ["PROBE_OUT"] + "/runs", os.environ["PROBE_OUT"] + "/report"
NAMES = {"r1side": "G  raw actions (image only + SIDE camera)", "r1high": "F-high  raw actions (image only, high effort)", "r3_full": "A  point at pixel (with hints)", "r3_nohint": "B  point at pixel (no hints)",
         "r2_state": "C  output xyz (true coords given)", "r2_vision": "D  output xyz (image only)", "orc": "Control (ground-truth positions)",
         "r1_state": "E  raw 7-D actions (true coords given)", "r1_vision": "F  raw 7-D actions (image only)"}
W, H, BAR = 336, 300, 40
try: FONT = ImageFont.truetype("DejaVuSans-Bold.ttf", 13)
except Exception: FONT = ImageFont.load_default()

def panel(run, ep):
    e = json.load(open("%s/%s/ep%03d/episode.json" % (R, run, ep)))
    fr = imageio.mimread("%s/%s/ep%03d/rollout.mp4" % (R, run, ep), memtest=False)
    key = next(k for k in NAMES if k in run)
    ok = e["success"]
    frames = []
    for i, f in enumerate(fr):
        im = Image.new("RGB", (W, H + BAR), (18, 26, 32))
        im.paste(Image.fromarray(f).crop((56, 90, 456, 447)).resize((W, H)), (0, BAR))
        d = ImageDraw.Draw(im)
        d.text((8, 5), NAMES[key], fill=(235, 240, 243), font=FONT)
        done = i == len(fr) - 1
        d.text((8, 22), "%s   GPT calls: %d" % (("SUCCESS" if ok else "FAIL") if done else "running...", e["n_calls"]) if key != "orc"
               else ("SUCCESS" if done and ok else "running..." if not done else "FAIL"),
               fill=((90, 200, 130) if ok else (240, 120, 100)) if done else (150, 165, 175), font=FONT)
        frames.append(np.asarray(im))
    return frames

def compare(name, specs, hold=25):
    ps = [panel(r, ep) for r, ep in specs]
    n = max(len(p) for p in ps) + hold
    out = [np.concatenate([p[min(i, len(p) - 1)] for p in ps], 1) for i in range(n)]
    path = "%s/cmp_%s.mp4" % (O, name)
    imageio.mimwrite(path, out, fps=20, quality=5, macro_block_size=4)
    print(name, len(out), "frames", os.path.getsize(path) // 1024, "KB")

import sys
SEL = sys.argv[1:]
_compare = compare
def compare(name, specs, hold=25):
    if not SEL or any(name.startswith(x) for x in SEL): _compare(name, specs, hold)

compare("1_pixel_vs_xyz_t8", [("abl2_t8_r3_full", 0), ("abl2_t8_r2_state", 0), ("abl2_t8_r2_vision", 0)])
compare("2_pixel_vs_xyz_t4", [("abl2_t4_r3_full", 0), ("abl2_t4_r2_vision", 0)])
compare("3_hint_vs_nohint_t8", [("abl2_t8_r3_full", 0), ("abl2_t8_r3_nohint", 0)])
compare("4_bowl_center_t6", [("abl2_t6_r3_full", 1), ("abl2_t6_r2_state", 1), ("orc4_t6", 1)])
compare("5_retry_t6", [("abl2_t6_r2_state", 0), ("abl2_t6_r3_full", 0)])
compare("6_raw_state_vs_vision_t8", [("r1a_t8_r1_state", 0), ("r1a_t8_r1_vision", 0)])
compare("7_raw_state_vs_vision_t6", [("r1a_t6_r1_state", 0), ("r1a_t6_r1_vision", 0)])
compare("8_program_vs_raw_t1", [("abl2_t1_r3_full", 0), ("r1a_t1_r1_state", 0)])
compare("9_side_camera_t1", [("r1a_t1_r1_vision", 0), ("r1side_t1_r1_vision", 0)])
compare("10_side_camera_t6", [("r1a_t6_r1_vision", 0), ("r1side_t6_r1_vision", 0)])
compare("11_side_camera_t8_fail", [("r1side_t8_r1_vision", 0), ("r1side_t8_r1_vision", 1)])
compare("12_stove_t7", [("r1all_t7_r1_state", 0), ("r1allside_t7_r1_vision", 1), ("r1allside_t7_r1_vision", 0)])
compare("13_drawer_t0_fail", [("r1all_t0_r1_state", 0), ("r1allside_t0_r1_vision", 0)])
compare("14_wine_bottle_t2", [("r1all_t2_r1_state", 0), ("r1allside_t2_r1_vision", 0)])
compare("15_push_plate_t5", [("r1all_t5_r1_state", 2), ("r1all_t5_r1_state", 0)])
