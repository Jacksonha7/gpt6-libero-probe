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

## Commands for each condition in the report

Task 8 shown; each command runs 10 episodes. libero_goal task ids: 0 open middle drawer · 1 bowl→stove · 2 wine bottle→cabinet top · 3 open top drawer and put bowl in · 4 bowl→cabinet top · 5 push plate · 6 cream cheese→bowl · 7 turn on stove · 8 bowl→plate · 9 wine bottle→rack.

| Condition | Arguments |
|---|---|
| A Pixel + hints | `--interface r3 --prompt-style full` |
| B Pixel, no hints | `--interface r3 --prompt-style nohint` |
| C Metric xyz + true coords | `--interface r2 --oracle-state` |
| D Metric xyz, images only | `--interface r2` |
| Ground-truth control | `--policy oracle --rim-offset 0.06 --rim-height 0.04 --oracle-release 3` (task 8; set `--oracle-grasp/--oracle-place` for other tasks) |
| E Direct actions + true coords | `--interface r1 --oracle-state --max-calls 40 --max-steps 450 --chunk 10` |
| F Direct actions, images only | `--interface r1 --max-calls 40 --max-steps 450 --chunk 10` |
| G F + side view | F's arguments + `--extra-cams sideview` |
| F-high | F's arguments + `--effort high --episodes 4` |

```bash
# Conditions A–D, four processes in parallel
bash run_ablation.sh 8 10 abl
# Conditions E/F; a 5th argument can add --extra-cams sideview (G) or --effort high (F-high)
bash run_r1.sh "8 1 4 6" 10 r1 "state vision"
# Summarize
$PY analyze.py abl_
```

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
