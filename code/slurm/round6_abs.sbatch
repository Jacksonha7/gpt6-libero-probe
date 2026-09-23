#!/bin/bash
#SBATCH -J gpt6-abs
#SBATCH -p <your-partition>
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=48G
#SBATCH --time=08:00:00
#SBATCH -o logs/slurm_%j.out
# 第六轮：绝对目标位置接口（只看图、两路相机、每次新对话）。H1 不带历史图，H2 附前 3 次调用的主相机图
cd "$SLURM_SUBMIT_DIR" && source env.sh
echo "node=$(hostname) CVD=$CUDA_VISIBLE_DEVICES"
if ! $PY -c "from libero_utils import make_env; make_env('libero_goal', 8, 128)" > /tmp/egl_probe_$$.log 2>&1; then echo EGL_FAILED; cat /tmp/egl_probe_$$.log; exit 1; fi
B="--interface r1abs --wrist-hint --episodes 10 --max-calls 90 --max-steps 450 --effort low"
for T in 8 1 4 6; do
  $PY probe.py --task-id $T $B --run-name r1abs_t${T}_r1_vision >> $PROBE_OUT/logs/r1abs_t${T}_r1_vision.log 2>&1 &
  $PY probe.py --task-id $T $B --history-images 3 --run-name r1abshist_t${T}_r1_vision >> $PROBE_OUT/logs/r1abshist_t${T}_r1_vision.log 2>&1 &
done
wait
$WANDB_PY upload_wandb.py r1abs 2>&1 | grep -E "^uploaded"
echo ALL_DONE
