# 代码

[English](README.md) | **中文**

GPT-6 经 `codex exec` 调用（走 ChatGPT 订阅，不需要 API key），在 LIBERO 仿真里逐回合决策。

## 文件

| 文件 | 作用 |
|---|---|
| `probe.py` | 主程序。`--interface r3\|r2\|r1\|r1abs` 选择接口，`--policy gpt\|oracle` 选择决策者 |
| `probe_r3.py` | 最初只支持指像素接口的版本，保留作记录 |
| `geom.py` | 相机几何：世界 ↔ 像素、深度线性化、反投影（不依赖 `robosuite.utils.camera_utils`，其反投影对 `[H,W,1]` 深度图有形状 bug） |
| `libero_utils.py` | 建环境（开深度）、reset、取物体与目标区域的真值位置 |
| `test_geom.py` | 几何自检：把物体真值位置投到图上、再反投影回 3D 报误差。改相机/分辨率/翻转后必须重跑 |
| `analyze.py` | 汇总若干 run 的成功率、调用次数、首次抓取、最终距离、延迟与 token |
| `make_comparisons.py` | 把若干回合拼成并排对照视频 |
| `upload_wandb.py` | 把 run 上传到 wandb（回放视频 + 逐次调用表），可选 |
| `run_ablation.sh` | 一个任务上并行跑条件 A–D |
| `run_r1.sh` | 批量跑直出动作条件（E/F/G/F-high） |
| `run_condition.sh` + `conditions.tsv` | 按条件名运行；列出参数和预期结果 |
| `slurm/*.sbatch` | Slurm 作业模板（分区需自行填写） |

## 环境

- 装好 [LIBERO](https://github.com/Lifelong-Robot-Learning/LIBERO) 的 Python 3.8 环境，另需 `numpy pillow imageio imageio-ffmpeg`；上传需 `wandb`
- GPU 节点（MuJoCo EGL 渲染），且能访问公网（codex 需要联网）
- 已登录的 [Codex CLI](https://github.com/openai/codex)

```bash
cd code
export LIBERO_ROOT=/path/to/LIBERO PY=/path/to/venv/bin/python
source env.sh
$PY test_geom.py libero_goal 8        # 看 $PROBE_OUT/test/proj_*.png，红圈应落在物体上
```

## 运行某个条件

报告中每个条件的名字、`probe.py` 参数和预期结果都在 [`conditions.tsv`](conditions.tsv)：

| 条件 | 报告中的名称 | 任务 8 / 1 / 4 / 6 的预期成功次数（各 10 回合） |
|---|---|---|
| `oracle` | 真值基线 | 10 / 10 / 10 / 10 |
| `prim_coords` | 原语 · 给坐标 [C] | 10 / 10 / 10 / 10 |
| `prim_pixel` | 原语 · 指像素 [A] | 9 / 10 / 10 / 1 |
| `prim_pixel_nohint` | 原语 · 指像素、无提示 [B] | 2 / 10 / 10 / 1 |
| `prim_xyz_vision` | 原语 · 从图估计 xyz [D] | 0 / 0 / 0 / 0 |
| `act_coords` | 直出动作 · 给坐标 [E] | 7 / 10 / 10 / 10 |
| `act_vision` | 直出动作 · 只看图 [F] | 0 / 0 / 1 / 1 |
| `act_vision_side` | 直出动作 · 看图 + 侧视图 [G] | 5 / 10 / 10 / 9 |
| `act_vision_high` | 直出动作 · 只看图、高推理档 [F-high] | 0/4 / 1/4 / 0/4 / 2/4 |

```bash
bash run_condition.sh act_vision_side 1 10     # 条件名、任务号、回合数
$PY analyze.py act_vision_side                 # 汇总该前缀的所有 run
```

最小冒烟测试（第一条不调用模型）：

```bash
bash run_condition.sh oracle 8 2               # 预期 2/2：检查渲染、几何和控制程序
bash run_condition.sh prim_coords 8 2          # 通常 2/2：检查 codex 连接
```

其余六个任务的结果（只有直出动作条件）见 [`../results/success_rates.csv`](../results/success_rates.csv)。每格只有 10 回合，重跑时每格有几个回合的波动是正常的，`prim_pixel_nohint` 尤其明显。`run_condition.sh` 里 `oracle` 的物体与偏移设置是根据实验记录重建的，可能与报告中的 run 略有差异。

libero_goal 任务号：0 开中间抽屉 · 1 碗→炉子 · 2 酒瓶→柜顶 · 3 开顶层抽屉放碗 · 4 碗→柜顶 · 5 推盘子 · 6 奶油芝士→碗 · 7 开炉子 · 8 碗→盘子 · 9 酒瓶→架子。

`run_ablation.sh` 和 `run_r1.sh` 是报告实验当时用的批量脚本，产生的是同样的 run，只是命名不同。

未写进报告的探索性接口：`--interface r1abs`（绝对目标位置）、`--wrist-hint`（鼓励用腕部相机检查对准）、`--history-images N`（附上前 N 次调用的主相机图）。

## 输出

```
$PROBE_OUT/runs/<run>/
  summary.json               参数、成功率
  ep000/
    episode.json             成功与否、步数、每次调用的完整记录、最终物体真值位置
    rollout.mp4              第三人称回放
    call00/
      img*.png               发给模型的图
      prompt.txt             完整提示词
      events.jsonl           codex 原始事件流（含 token 用量）
      out.json               模型的结构化输出
      record.json            + 反投影 3D 点、最近的真值物体及距离、执行结果
```

`probe.py` 支持断点续跑：已有 `episode.json` 的回合会跳过，同样的命令重跑即可。

## 注意事项

- robosuite 原始图像上下颠倒。`upright(img) = img[::-1]` 是发给模型的正向、不镜像的图；openpi 喂给 π₀ 的 `img[::-1, ::-1]` 是它的左右镜像，不要混用。
- 像素一律 `(u, v) = (列, 行)`，原点左上角。agentview 相机在桌子对面朝向机器人：世界 +x 指向画面下方，+y 指向画面右侧。
- `codex exec` 必须 `stdin=DEVNULL`，否则会挂起等待输入；`-i` 是可变参数，提示词前必须加 `--`。
- 每次调用约有 1.3 万 token 的 Codex 系统提示开销。
- 高推理档 + `model_reasoning_summary=detailed` 也只能拿到一两行推理小标题，拿不到原始思维链。
- 部分 GPU 节点 EGL 初始化会失败，sbatch 模板开头有 EGL 自检，失败会直接退出。
- 提交 sbatch 前先在 `code/` 下 `mkdir -p logs`。
