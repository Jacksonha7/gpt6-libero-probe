#!/bin/bash
# 任务 8 上四个条件各 N 个 episode，4 个进程并行（并行度刻意压低，避免 codex 限流）
# 用法：srun --overlap --jobid=<jobid> bash run_ablation.sh [task_id] [episodes] [tag]
cd "$(dirname "$0")" && source env.sh
TASK=${1:-8}; N=${2:-10}; TAG=${3:-abl_$(date +%m%d_%H%M)}
mkdir -p $PROBE_OUT/logs
run() { name=$1; shift; $PY probe.py --task-id $TASK --policy gpt --episodes $N --effort low --run-name ${TAG}_t${TASK}_$name "$@" > $PROBE_OUT/logs/${TAG}_t${TASK}_$name.log 2>&1 & }
run r3_full    --interface r3 --prompt-style full
run r3_nohint  --interface r3 --prompt-style nohint
run r2_vision  --interface r2
run r2_state   --interface r2 --oracle-state
wait
grep -H "success rate" $PROBE_OUT/logs/${TAG}_t${TASK}_*.log
$WANDB_PY upload_wandb.py ${TAG}_t${TASK} 2>&1 | grep -E "^uploaded|^skip"   # 跑完自动传 wandb
