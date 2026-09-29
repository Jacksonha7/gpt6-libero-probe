#!/bin/bash
#SBATCH -J gpt6-nodone
#SBATCH -p long
#SBATCH --exclude=gpu-05,gpu-12,gpu-15,gpu-24,gpu-37,gpu-54,gpu-62
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=48G
#SBATCH --time=08:00:00
#SBATCH -o /l/users/jianxiang.he/icl-vla-scratch/gpt6_probe/logs/slurm_%j.out
# 第七轮：H3 = H2 + 忽略模型的 done（回合只由仿真器结束）
cd ~/Project/gpt6-probe && source env.sh
echo "node=$(hostname) CVD=$CUDA_VISIBLE_DEVICES"
if ! $PY -c "from libero_utils import make_env; make_env('libero_goal', 8, 128)" > /tmp/egl_probe_$$.log 2>&1; then echo EGL_FAILED; cat /tmp/egl_probe_$$.log; exit 1; fi
B="--interface r1abs --wrist-hint --history-images 3 --ignore-done --episodes 10 --max-calls 90 --max-steps 450 --effort low"
for T in 8 1 4 6; do
  $PY probe.py --task-id $T $B --run-name r1absnodone_t${T}_r1_vision >> $PROBE_OUT/logs/r1absnodone_t${T}_r1_vision.log 2>&1 &
done
wait
$WANDB_PY upload_wandb.py r1absnodone 2>&1 | grep -E "^uploaded"
echo ALL_DONE
