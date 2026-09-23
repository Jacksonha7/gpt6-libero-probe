#!/bin/bash
# 直出动作（r1）：每个任务两个条件（给物体坐标 / 只看图）各 N 个回合，跑完自动传 wandb
# 用法：srun --overlap --jobid=<jobid> bash run_r1.sh "8 1 4 6" 10 r1a
cd "$(dirname "$0")" && source env.sh
TASKS=${1:-"8"}; N=${2:-10}; TAG=${3:-r1_$(date +%m%d_%H%M)}; CONDS=${4:-"state vision"}; MORE=${5:-""}   # MORE 例：--extra-cams sideview 或 --effort high
mkdir -p $PROBE_OUT/logs
for T in $TASKS; do
  for C in $CONDS; do
    [ $C = state ] && EXTRA="--oracle-state" || EXTRA=""
    $PY probe.py --task-id $T --interface r1 $EXTRA --episodes $N --max-calls 40 --max-steps 450 --chunk 10 --effort low $MORE \
        --run-name ${TAG}_t${T}_r1_$C > $PROBE_OUT/logs/${TAG}_t${T}_r1_$C.log 2>&1 &
  done
done
wait
grep -H "success rate" $PROBE_OUT/logs/${TAG}_*.log | sed 's#.*/##'
$WANDB_PY upload_wandb.py ${TAG}_ 2>&1 | grep -E "^uploaded|^skip"
