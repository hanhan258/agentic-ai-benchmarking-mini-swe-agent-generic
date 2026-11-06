#!/usr/bin/env bash
set -euo pipefail

# Load a dotenv-style configuration file when present. Explicit environment
# variables always win over values from the file. Use AAB_ENV_FILE to choose a
# different file; the default is .env in the current project directory.
AAB_ENV_FILE="${AAB_ENV_FILE:-${ENV_FILE:-.env}}"
if [[ "${AAB_ENV_FILE}" != /* ]]; then
  AAB_ENV_FILE="${PWD}/${AAB_ENV_FILE}"
fi
load_dotenv_defaults() {
  local file="$1" raw key value
  [[ -f "$file" ]] || return 0
  while IFS= read -r raw || [[ -n "$raw" ]]; do
    raw="${raw#${raw%%[![:space:]]*}}"
    raw="${raw%${raw##*[![:space:]]}}"
    [[ -z "$raw" || "${raw:0:1}" == "#" ]] && continue
    [[ "$raw" == export\ * ]] && raw="${raw#export }"
    [[ "$raw" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
    key="${BASH_REMATCH[1]}"
    [[ -v "$key" ]] && continue
    value="${BASH_REMATCH[2]}"
    if [[ ${#value} -ge 2 && "${value:0:1}" == '"' && "${value: -1}" == '"' ]]; then
      value="${value:1:${#value}-2}"
    elif [[ ${#value} -ge 2 && "${value:0:1}" == "'" && "${value: -1}" == "'" ]]; then
      value="${value:1:${#value}-2}"
    fi
    printf -v "$key" '%s' "$value"
    export "$key"
  done < "$file"
}
load_dotenv_defaults "$AAB_ENV_FILE"

AGENT_SWEEP="${AGENT_SWEEP:-1 2 4}"
SWEEP_ROOT="${SWEEP_ROOT:-runs/team-v2-sweep-metrics-$(date +%Y%m%d-%H%M%S)}"
PARALLELISM="${PARALLELISM:-4}"
CONTEXT_LENGTH="${CONTEXT_LENGTH:-1024}"
ADAPTER_MODE="${ADAPTER_MODE:-mock}"
RUNTIME_TYPE="${RUNTIME_TYPE:-process}"
METRICS_MIN_SECONDS="${METRICS_MIN_SECONDS:-2}"
AAB_REPO_CONTEXT_ENABLED="${AAB_REPO_CONTEXT_ENABLED:-0}"
AAB_REPO_SOURCE="${AAB_REPO_SOURCE:-}"
AAB_REPO_CONTEXT_MAX_FILES="${AAB_REPO_CONTEXT_MAX_FILES:-20000}"
AAB_REPO_CONTEXT_MAX_BYTES="${AAB_REPO_CONTEXT_MAX_BYTES:-1073741824}"
AAB_REPO_CONTEXT_BUNDLE_MAX_BYTES="${AAB_REPO_CONTEXT_BUNDLE_MAX_BYTES:-4194304}"
AAB_REPO_CONTEXT_PROMPT_MAX_CHARS="${AAB_REPO_CONTEXT_PROMPT_MAX_CHARS:-8192}"
AAB_REPO_CONTEXT_EXTENSIONS="${AAB_REPO_CONTEXT_EXTENSIONS:-.py,.js,.jsx,.ts,.tsx,.go,.rs,.c,.cc,.cpp,.h,.hpp,.java,.md,.toml,.yaml,.yml,.json}"
AAB_REPO_WORKSPACE_MODE="${AAB_REPO_WORKSPACE_MODE:-worktree}"
AAB_REPO_WORKSPACE_CLEANUP="${AAB_REPO_WORKSPACE_CLEANUP:-0}"
AAB_REPO_CONTEXT_INCLUDE_GIT_HISTORY="${AAB_REPO_CONTEXT_INCLUDE_GIT_HISTORY:-0}"
AAB_REPO_CONTEXT_GIT_HISTORY_MAX_BYTES="${AAB_REPO_CONTEXT_GIT_HISTORY_MAX_BYTES:-536870912}"
AAB_REPO_CONTEXT_GIT_LOG_LIMIT="${AAB_REPO_CONTEXT_GIT_LOG_LIMIT:-1000}"
AAB_REPO_CONTEXT_PYTEST_COLLECT="${AAB_REPO_CONTEXT_PYTEST_COLLECT:-0}"
AAB_REPO_CONTEXT_PYTEST_COMMAND="${AAB_REPO_CONTEXT_PYTEST_COMMAND:-python -m pytest --collect-only -q}"
AAB_REPO_CONTEXT_PYTEST_TIMEOUT_SEC="${AAB_REPO_CONTEXT_PYTEST_TIMEOUT_SEC:-120}"
TASK_SOURCE="${TASK_SOURCE:-synthetic}"
TASK="${TASK:-}"
VERIFY_COMMAND="${VERIFY_COMMAND:-}"
VERIFY_TIMEOUT_SEC="${VERIFY_TIMEOUT_SEC:-120}"
MINI_COMMAND="${MINI_COMMAND:-mini}"
MODEL="${MODEL:-DeepSeek-V4-Flash}"
VLLM_BASE_URL="${VLLM_BASE_URL:-http://127.0.0.1:4000/v1}"
MEMORY_SAMPLE_INTERVAL_SEC="${MEMORY_SAMPLE_INTERVAL_SEC:-1}"
GENERIC_MEMORY_BACKEND="${GENERIC_MEMORY_BACKEND:-procfs}"

mkdir -p "${SWEEP_ROOT}"

repo_context_args=()
task_args=(
  --task-source "${TASK_SOURCE}"
  --verify-timeout-sec "${VERIFY_TIMEOUT_SEC}"
)
if [[ -n "${TASK}" ]]; then
  task_args+=(--task "${TASK}")
fi
if [[ -n "${VERIFY_COMMAND}" ]]; then
  task_args+=(--verify-command "${VERIFY_COMMAND}")
fi
if [[ "${TASK_SOURCE}" == "local" ]]; then
  if [[ -z "${AAB_REPO_SOURCE}" ]]; then
    echo "AAB_REPO_SOURCE is required when TASK_SOURCE=local" >&2
    exit 2
  fi
  if [[ -z "${TASK}" ]]; then
    echo "TASK is required when TASK_SOURCE=local" >&2
    exit 2
  fi
  task_args+=(--repo-source "${AAB_REPO_SOURCE}")
fi

if [[ "${AAB_REPO_CONTEXT_ENABLED}" == "1" ]]; then
  if [[ -z "${AAB_REPO_SOURCE}" ]]; then
    echo "AAB_REPO_SOURCE is required when AAB_REPO_CONTEXT_ENABLED=1" >&2
    exit 2
  fi
  repo_context_args+=(
    --repo-context-enabled
    --repo-source "${AAB_REPO_SOURCE}"
    --repo-context-max-files "${AAB_REPO_CONTEXT_MAX_FILES}"
    --repo-context-max-bytes "${AAB_REPO_CONTEXT_MAX_BYTES}"
    --repo-context-bundle-max-bytes "${AAB_REPO_CONTEXT_BUNDLE_MAX_BYTES}"
    --repo-context-prompt-max-chars "${AAB_REPO_CONTEXT_PROMPT_MAX_CHARS}"
    --repo-context-extensions "${AAB_REPO_CONTEXT_EXTENSIONS}"
    --repo-workspace-mode "${AAB_REPO_WORKSPACE_MODE}"
    --repo-context-git-history-max-bytes "${AAB_REPO_CONTEXT_GIT_HISTORY_MAX_BYTES}"
    --repo-context-git-log-limit "${AAB_REPO_CONTEXT_GIT_LOG_LIMIT}"
    --repo-context-pytest-command "${AAB_REPO_CONTEXT_PYTEST_COMMAND}"
    --repo-context-pytest-timeout-sec "${AAB_REPO_CONTEXT_PYTEST_TIMEOUT_SEC}"
  )
  if [[ "${AAB_REPO_CONTEXT_INCLUDE_GIT_HISTORY}" == "1" ]]; then
    repo_context_args+=(--repo-context-include-git-history)
  fi
  if [[ "${AAB_REPO_CONTEXT_PYTEST_COLLECT}" == "1" ]]; then
    repo_context_args+=(--repo-context-pytest-collect)
  fi
  if [[ "${AAB_REPO_WORKSPACE_CLEANUP}" == "1" ]]; then
    repo_context_args+=(--repo-workspace-cleanup)
  fi
fi

start_cpu_metrics() {
  local run_dir="$1"
  mkdir -p "${run_dir}/metrics"
  (
    echo "timestamp,cpu_util_pct,user_pct,system_pct,iowait_pct,idle_pct,load1,load5,load15"
    prev_total=""
    prev_idle=""
    while true; do
      read -r _ user nice system idle iowait irq softirq steal guest guest_nice < /proc/stat
      total=$((user + nice + system + idle + iowait + irq + softirq + steal))
      idle_all=$((idle + iowait))
      if [[ -n "${prev_total}" ]]; then
        total_delta=$((total - prev_total))
        idle_delta=$((idle_all - prev_idle))
        user_delta=$((user - prev_user))
        system_delta=$((system - prev_system))
        iowait_delta=$((iowait - prev_iowait))
        if [[ "${total_delta}" -gt 0 ]]; then
          cpu_util="$(awk -v t="${total_delta}" -v i="${idle_delta}" 'BEGIN { printf "%.4f", 100*(1-i/t) }')"
          user_pct="$(awk -v t="${total_delta}" -v v="${user_delta}" 'BEGIN { printf "%.4f", 100*v/t }')"
          system_pct="$(awk -v t="${total_delta}" -v v="${system_delta}" 'BEGIN { printf "%.4f", 100*v/t }')"
          iowait_pct="$(awk -v t="${total_delta}" -v v="${iowait_delta}" 'BEGIN { printf "%.4f", 100*v/t }')"
          idle_pct="$(awk -v t="${total_delta}" -v v="${idle_delta}" 'BEGIN { printf "%.4f", 100*v/t }')"
          read -r load1 load5 load15 _ < /proc/loadavg
          echo "$(date +%s),${cpu_util},${user_pct},${system_pct},${iowait_pct},${idle_pct},${load1},${load5},${load15}"
        fi
      fi
      prev_total="${total}"
      prev_idle="${idle_all}"
      prev_user="${user}"
      prev_system="${system}"
      prev_iowait="${iowait}"
      sleep 1
    done
  ) > "${run_dir}/metrics/cpu.csv" &
  CPU_METRICS_PID="$!"
}

stop_cpu_metrics() {
  if [[ -n "${CPU_METRICS_PID:-}" ]]; then
    kill "${CPU_METRICS_PID}" >/dev/null 2>&1 || true
    wait "${CPU_METRICS_PID}" >/dev/null 2>&1 || true
  fi
}

start_memory_metrics() {
  local run_dir="$1"
  mkdir -p "${run_dir}/metrics"
  (
    echo "timestamp,mem_total_mib,mem_used_mib,mem_available_mib,buffers_mib,cached_mib,swap_total_mib,swap_used_mib,load1,load5,load15"
    while true; do
      read -r load1 load5 load15 _ < /proc/loadavg
      awk -v l1="$load1" -v l5="$load5" -v l15="$load15" '
        /^MemTotal:/ { total=$2 }
        /^MemFree:/ { free=$2 }
        /^MemAvailable:/ { available=$2 }
        /^Buffers:/ { buffers=$2 }
        /^Cached:/ { cached=$2 }
        /^SReclaimable:/ { reclaim=$2 }
        /^Shmem:/ { shmem=$2 }
        /^SwapTotal:/ { swap_total=$2 }
        /^SwapFree:/ { swap_free=$2 }
        END {
          used=total-available
          cached_total=cached+reclaim-shmem
          if (cached_total < 0) cached_total=0
          printf "%d,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%s,%s,%s\n",
            systime(), total/1024, used/1024, available/1024,
            buffers/1024, cached_total/1024, swap_total/1024,
            (swap_total-swap_free)/1024, l1, l5, l15
        }
      ' /proc/meminfo
      sleep "${MEMORY_SAMPLE_INTERVAL_SEC}"
    done
  ) > "${run_dir}/metrics/memory.csv" &
  MEMORY_METRICS_PID="$!"
}

stop_memory_metrics() {
  if [[ -n "${MEMORY_METRICS_PID:-}" ]]; then
    kill "${MEMORY_METRICS_PID}" >/dev/null 2>&1 || true
    wait "${MEMORY_METRICS_PID}" >/dev/null 2>&1 || true
  fi
}

refresh_run_metrics() {
  local run_dir="$1"
  python3 - "${run_dir}" <<'PY'
import sys
from pathlib import Path
from aab_framework.team_v2.metrics_wrapper import refresh_run_metrics

refresh_run_metrics(Path(sys.argv[1]))
PY
}

child_results=()
for agents in ${AGENT_SWEEP//,/ }; do
  point_tmp="${SWEEP_ROOT}/metrics_agents_${agents}"
  mkdir -p "${point_tmp}"
  echo "===== START mini_swe_agent_team_v2 agents=${agents} ====="
  start_cpu_metrics "${point_tmp}"
  start_memory_metrics "${point_tmp}"
  set +e
  run_output="$(
    python3 -m aab_framework.cli run \
      --workload mini_swe_agent_team_v2 \
      --num-agents "${agents}" \
      --parallelism "${PARALLELISM}" \
      --context-length "${CONTEXT_LENGTH}" \
      --adapter-mode "${ADAPTER_MODE}" \
      --runtime-type "${RUNTIME_TYPE}" \
      --mini-command "${MINI_COMMAND}" \
      --model "${MODEL}" \
      --vllm-base-url "${VLLM_BASE_URL}" \
      "${task_args[@]}" \
      "${repo_context_args[@]}" \
      --out-dir "${SWEEP_ROOT}" 2>&1
  )"
  rc="$?"
  set -e
  sleep "${METRICS_MIN_SECONDS}"
  stop_memory_metrics
  stop_cpu_metrics
  printf '%s\n' "${run_output}" | tee "${point_tmp}/run.log"
  if [[ "${rc}" -ne 0 ]]; then
    echo "run failed for agents=${agents} rc=${rc}" >&2
    exit "${rc}"
  fi
  run_dir="$(printf '%s\n' "${run_output}" | awk -F': ' '/^Run dir:/ {print $2}' | tail -1)"
  result_path="$(printf '%s\n' "${run_output}" | awk -F': ' '/^Result:/ {print $2}' | tail -1)"
  if [[ -z "${run_dir}" || -z "${result_path}" ]]; then
    echo "unable to parse run output for agents=${agents}" >&2
    exit 1
  fi
  rm -rf "${run_dir}/metrics"
  cp -a "${point_tmp}/metrics" "${run_dir}/metrics"
  refresh_run_metrics "${run_dir}"
  child_results+=("${result_path}")
  echo "===== END mini_swe_agent_team_v2 agents=${agents} result=${result_path} ====="
done

python3 - "${SWEEP_ROOT}" "${child_results[@]}" <<'PY'
import sys
from pathlib import Path
from aab_framework.team_v2.metrics_wrapper import build_sweep_from_child_runs

sweep_root = Path(sys.argv[1])
child_results = [Path(item) for item in sys.argv[2:]]
result = build_sweep_from_child_runs(sweep_root, child_results)
print(f"Sweep Group: {result['run_id']}")
print(f"Run dir: {result['run_dir'] if 'run_dir' in result else sweep_root}")
print(f"Result: {sweep_root / 'result.json'}")
for item in result["runs"]:
    print(f"Run: num_agents={item['num_agents']} run_id={item['run_id']} result={item['result_path']}")
PY
