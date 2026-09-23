#!/bin/bash
# 按条件名运行一个任务。条件、参数和报告中的结果见 conditions.tsv
# Usage: bash run_condition.sh <condition> <task_id> [episodes]
set -o pipefail
cd "$(dirname "$0")" && source env.sh
COND=$1; TASK=$2; N=${3:-10}
ARGS=$(awk -F'\t' -v c="$COND" 'NR>1 && $1==c {print $2}' conditions.tsv)
if [ -z "$ARGS" ] || [ -z "$TASK" ]; then
  echo "usage: bash run_condition.sh <condition> <task_id> [episodes]"; echo "conditions:"; awk -F'\t' 'NR>1 {print "  " $1 "\t" $3}' conditions.tsv; exit 1
fi
if [ "$COND" = oracle ]; then      # 真值基线：按任务指定被抓物体与目标；碗夹碗沿，奶油芝士夹中心
  case $TASK in
    8) ARGS="$ARGS --oracle-grasp akita_black_bowl_1 --oracle-place plate_1 --rim-offset 0.06 --rim-height 0.04 --oracle-release 3" ;;
    1) ARGS="$ARGS --oracle-grasp akita_black_bowl_1 --oracle-place flat_stove_1_cook_region --rim-offset 0.06 --rim-height 0.04 --oracle-release 3" ;;
    4) ARGS="$ARGS --oracle-grasp akita_black_bowl_1 --oracle-place wooden_cabinet_1_top_side --rim-offset 0.06 --rim-height 0.04 --oracle-release 3" ;;
    6) ARGS="$ARGS --oracle-grasp cream_cheese_1 --oracle-place akita_black_bowl_1 --oracle-release 3" ;;
    *) echo "oracle is defined for tasks 8, 1, 4, 6 only"; exit 1 ;;
  esac
fi
$PY probe.py --task-id $TASK --episodes $N --effort low $ARGS --run-name ${COND}_t${TASK} 2>&1 | tee $PROBE_OUT/logs/${COND}_t${TASK}.log
