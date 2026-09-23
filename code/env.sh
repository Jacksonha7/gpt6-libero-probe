# 用法：cd code && source env.sh
# 需要：装好 LIBERO 的 Python 3.8 环境（EGL 渲染需 GPU），以及已登录的 codex CLI（经 ChatGPT 订阅调用 GPT-6，不需要 API key）
export MUJOCO_GL=egl
export LIBERO_ROOT=${LIBERO_ROOT:-/path/to/LIBERO}          # LIBERO 源码目录
export PYTHONPATH=$LIBERO_ROOT:$(pwd)
export PROBE_OUT=${PROBE_OUT:-$(pwd)/../outputs}            # 所有输出（回合记录、视频、日志）
export PROBE_TMP=$PROBE_OUT/tmp
export PY=${PY:-python}                                     # 装了 LIBERO 的解释器
export WANDB_PY=${WANDB_PY:-$PY}                            # 装了 wandb 的解释器（可选，只用于上传）
mkdir -p $PROBE_TMP $PROBE_OUT/logs
