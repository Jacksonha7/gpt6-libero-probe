# Code

**English** | [中文](README_zh.md)

GPT-6 is called through `codex exec` (using a ChatGPT subscription, no API key needed) and makes decisions turn by turn in the LIBERO simulator.

## Files

| File | Purpose |
|---|---|
| `probe.py` | Main program. `--interface r3\|r2\|r1\|r1abs` selects the interface; `--policy gpt\|oracle` selects the decision maker |
| `probe_r3.py` | The first version, pixel-pointing interface only; kept for reference |
| `geom.py` | Camera geometry: world ↔ pixel, depth linearization, back-projection (does not use `robosuite.utils.camera_utils`, whose back-projection has a shape bug with `[H,W,1]` depth maps) |
| `libero_utils.py` | Environment creation (with depth), reset, ground-truth object and target-region positions |
| `test_geom.py` | Geometry self-check: projects true object positions into the image, back-projects them and reports the error. Rerun after changing camera, resolution or image flips |
| `analyze.py` | Summarizes runs: success rate, calls, first grasp, final distance, latency and tokens |
| `make_comparisons.py` | Stitches episodes into side-by-side comparison videos |
| `upload_wandb.py` | Uploads runs to wandb (rollout videos + per-call tables); optional |
| `run_ablation.sh` | Runs conditions A–D in parallel on one task |
| `run_r1.sh` | Batch runs of the direct-action conditions (E/F/G/F-high) |
| `run_condition.sh` + `conditions.tsv` | Run any condition by name; lists arguments and expected results |
| `slurm/*.sbatch` | Slurm job templates (fill in your partition) |

Code comments are in Chinese.

## Setup

- Python 3.8 environment with [LIBERO](https://github.com/Lifelong-Robot-Learning/LIBERO), plus `numpy pillow imageio imageio-ffmpeg`; `wandb` for uploading
- A GPU node (MuJoCo EGL rendering) with internet access (codex needs it)
- A logged-in [Codex CLI](https://github.com/openai/codex)

```bash
cd code
export LIBERO_ROOT=/path/to/LIBERO PY=/path/to/venv/bin/python
source env.sh
$PY test_geom.py libero_goal 8        # check $PROBE_OUT/test/proj_*.png: red circles should sit on the objects
```

## Running a condition

Every condition in the report has a name, its `probe.py` arguments and its expected result in [`conditions.tsv`](conditions.tsv):

| Condition | Report label | Expected successes on tasks 8 / 1 / 4 / 6 (10 episodes each) |
|---|---|---|
| `oracle` | Ground-truth baseline | 10 / 10 / 10 / 10 |
| `prim_coords` | Primitives · coordinates [C] | 10 / 10 / 10 / 10 |
| `prim_pixel` | Primitives · pixel [A] | 9 / 10 / 10 / 1 |
| `prim_pixel_nohint` | Primitives · pixel, no hints [B] | 2 / 10 / 10 / 1 |
| `prim_xyz_vision` | Primitives · xyz from images [D] | 0 / 0 / 0 / 0 |
| `act_coords` | Raw actions · coordinates [E] | 7 / 10 / 10 / 10 |
| `act_vision` | Raw actions · images only [F] | 0 / 0 / 1 / 1 |
| `act_vision_side` | Raw actions · images + side view [G] | 5 / 10 / 10 / 9 |
| `act_vision_high` | Raw actions · images only, high effort [F-high] | 0/4 / 1/4 / 0/4 / 2/4 |

```bash
bash run_condition.sh act_vision_side 1 10     # condition, task id, episodes
$PY analyze.py act_vision_side                 # summarize all runs with this prefix
```

Minimal smoke test (the first command makes no model calls):

```bash
bash run_condition.sh oracle 8 2               # expect 2/2: checks rendering, geometry and controller
bash run_condition.sh prim_coords 8 2          # usually 2/2: checks the codex connection
```

Results for the other six tasks (raw-action conditions only) are in [`../results/success_rates.csv`](../results/success_rates.csv). With 10 episodes per cell, expect a few episodes of variation per cell, especially for `prim_pixel_nohint`. The `oracle` object/offset settings in `run_condition.sh` are reconstructed from the experiment notes and may differ slightly from the runs in the report.

libero_goal task ids: 0 open middle drawer · 1 bowl→stove · 2 wine bottle→cabinet top · 3 open top drawer and put bowl in · 4 bowl→cabinet top · 5 push plate · 6 cream cheese→bowl · 7 turn on stove · 8 bowl→plate · 9 wine bottle→rack.

`run_ablation.sh` and `run_r1.sh` are the batch scripts originally used for the report; they produce the same runs under different names.

Exploratory interfaces not covered in the report: `--interface r1abs` (absolute target positions), `--wrist-hint` (encourages using the wrist camera to check alignment), `--history-images N` (attaches main-camera images from the previous N calls).

## Output

```
$PROBE_OUT/runs/<run>/
  summary.json               arguments, success rate
  ep000/
    episode.json             success, steps, full record of every call, final true object positions
    rollout.mp4              third-person rollout
    call00/
      img*.png               images sent to the model
      prompt.txt             full prompt
      events.jsonl           raw codex event stream (with token usage)
      out.json               the model's structured output
      record.json            + back-projected 3D point, nearest true object and distance, execution result
```

`probe.py` resumes from where it stopped: episodes that already have `episode.json` are skipped, so just rerun the same command.

## Notes

- robosuite's raw images are upside down. `upright(img) = img[::-1]` is the upright, unmirrored image sent to the model; openpi's `img[::-1, ::-1]` fed to π₀ is its left-right mirror. Don't mix them.
- Pixels are always `(u, v) = (column, row)` with the origin at the top-left. The agentview camera faces the robot across the table: world +x points down in the image, +y points right.
- `codex exec` needs `stdin=DEVNULL` or it hangs waiting for input; `-i` takes a variable number of arguments, so the prompt must be preceded by `--`.
- Each call carries roughly 13k tokens of Codex system prompt.
- Even with high effort and `model_reasoning_summary=detailed`, only one or two reasoning headings are returned, not the raw chain of thought.
- EGL initialization fails on some GPU nodes; the sbatch templates start with an EGL self-check and exit early if it fails.
- Run `mkdir -p logs` inside `code/` before submitting an sbatch job.
