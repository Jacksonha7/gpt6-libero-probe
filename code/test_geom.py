"""接 GPT 之前必须先过的单元测试：投影/反投影/图像翻转约定。
把每个物体的真值位置投到图上画圈，再从该像素反投影回 3D，报告与真值的距离。"""
import os, sys
import numpy as np
from PIL import Image, ImageDraw
from geom import Camera, upright
from libero_utils import make_env, reset_to, object_positions

suite, task_id, res = sys.argv[1], int(sys.argv[2]), 512
out = os.path.join(os.environ["PROBE_OUT"], "test"); os.makedirs(out, exist_ok=True)
env, lang, inits = make_env(suite, task_id, res)
obs = reset_to(env, inits[0])
cam = Camera(env.sim, "agentview", res, res)
depth = cam.depth_map(obs["agentview_depth"])
img = Image.fromarray(upright(obs["agentview_image"])); dr = ImageDraw.Draw(img)
print("task:", lang); print("depth range (m): %.3f - %.3f" % (depth.min(), depth.max()))
pts = object_positions(obs); pts["EEF"] = obs["robot0_eef_pos"]
for name, p in pts.items():
    (u, v), zc = cam.project(p)
    inside = 0 <= u < res and 0 <= v < res
    msg = "%-32s world=%s -> uv=(%6.1f,%6.1f)" % (name, np.round(p, 3), u, v)
    if inside:
        back = cam.backproject(u, v, depth)
        msg += "  backproj_err=%.3f m  (cam depth: true %.3f / rendered %.3f)" % (
            np.linalg.norm(back - p), zc, depth[int(round(v)), int(round(u))])
        dr.ellipse([u - 5, v - 5, u + 5, v + 5], outline=(255, 0, 0), width=2)
        dr.text((u + 7, v - 6), name[:18], fill=(255, 255, 0))
    print(msg)
img.save(os.path.join(out, "proj_%s_%d.png" % (suite, task_id)))
Image.fromarray(np.ascontiguousarray(obs["agentview_image"][::-1, ::-1])).save(os.path.join(out, "openpi_view_%s_%d.png" % (suite, task_id)))
print("saved ->", out)
