#!/bin/bash
#SBATCH -J gpt6-probe
#SBATCH -p <your-partition>
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=48G
#SBATCH --time=05:00:00
#SBATCH -o logs/slurm_%j.out
# 第四轮未完成回合的续跑（probe.py 会跳过已有 episode.json 的回合）+ 腕部相机变体
cd "$SLURM_SUBMIT_DIR" && source env.sh
# 单卡作业里 EGL 设备号可能和 CUDA_VISIBLE_DEVICES 对不上：逐个试，找到能初始化渲染的设置再跑
echo "node=$(hostname) CVD=$CUDA_VISIBLE_DEVICES"
EGL_OK=""
for v in unset 0 1 2 3; do
  if [ $v = unset ]; then unset MUJOCO_EGL_DEVICE_ID; else export MUJOCO_EGL_DEVICE_ID=$v; fi
  if $PY -c "from libero_utils import make_env; make_env('libero_goal', 8, 128)" > /tmp/egl_probe_$$.log 2>&1; then EGL_OK=$v; break; fi
  grep -E "Cannot initialize|must be|ValueError|RuntimeError" /tmp/egl_probe_$$.log | head -2
done
echo "EGL setting that works: [$EGL_OK]"
if [ -z "$EGL_OK" ]; then echo "EGL_FAILED_ALL"; cat /tmp/egl_probe_$$.log; exit 1; fi
R1="--interface r1 --episodes 10 --max-calls 40 --max-steps 450 --chunk 10 --effort low"
for T in 0 3; do $PY probe.py --task-id $T $R1 --oracle-state --run-name r1all_t${T}_r1_state >> $PROBE_OUT/logs/r1all_t${T}_r1_state.resume3.log 2>&1 & done
for T in 0 3 5; do $PY probe.py --task-id $T $R1 --extra-cams sideview --run-name r1allside_t${T}_r1_vision >> $PROBE_OUT/logs/r1allside_t${T}_r1_vision.resume3.log 2>&1 & done
for T in 8 1 4 6; do $PY probe.py --task-id $T $R1 --wrist-hint --run-name r1wrist_t${T}_r1_vision >> $PROBE_OUT/logs/r1wrist_t${T}_r1_vision.log 2>&1 & done
wait
$WANDB_PY upload_wandb.py r1all 2>&1 | grep -E "^uploaded"
$WANDB_PY upload_wandb.py r1wrist 2>&1 | grep -E "^uploaded"
echo ALL_DONE
