import os
import numpy as np
from libero.libero import benchmark, get_libero_path
from libero.libero.envs import OffScreenRenderEnv

DUMMY = [0.0] * 6 + [-1.0]


def make_env(suite_name, task_id, res, seed=7, extra_cams=()):
    suite = benchmark.get_benchmark_dict()[suite_name]()
    task = suite.get_task(task_id)
    bddl = os.path.join(get_libero_path("bddl_files"), task.problem_folder, task.bddl_file)
    env = OffScreenRenderEnv(bddl_file_name=bddl, camera_heights=res, camera_widths=res, camera_depths=True,
                             camera_names=["agentview", "robot0_eye_in_hand"] + list(extra_cams))
    env.seed(seed)
    return env, task.language, suite.get_task_init_states(task_id)


def reset_to(env, init_state, settle=10):
    env.reset()
    obs = env.set_init_state(init_state)
    for _ in range(settle):
        obs, _, _, _ = env.step(DUMMY)
    return obs


def object_positions(obs):
    """obs 里所有物体的真值世界坐标（只用于日志/oracle，不给模型看，除非显式开 oracle）。"""
    return {k[:-4]: np.asarray(v, dtype=float) for k, v in obs.items()
            if k.endswith("_pos") and not k.startswith("robot0") and "_to_" not in k}


def region_positions(env):
    """固定物体上的目标区域（如 flat_stove_1_cook_region、wooden_cabinet_1_top_side）的世界坐标。
    成功判定用的是这些 site，不是固定物体的原点。"""
    e, out = env.env, {}
    for name in e.object_sites_dict:
        try:
            out[name] = np.asarray(e.sim.data.get_site_xpos(name), dtype=float).copy()
        except Exception:
            pass
    # 可动部件（抽屉体、炉子按钮）的刚体原点。注意：抽屉原点大致在抽屉中心，不是把手；把手位置仿真里没有单独的名字。
    sim = e.sim
    for k in range(sim.model.nbody):
        n = sim.model.body_id2name(k)
        if n and any(s in n for s in ("cabinet_top", "cabinet_middle", "cabinet_bottom", "_button")):
            out[n + "_body"] = np.asarray(sim.data.body_xpos[k], dtype=float).copy()
    return out
