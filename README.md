# Agentic AI Benchmarking Mini SWE Agent

This repository packages a deployable benchmark for mini-swe-agent style coding
agents on PCIe GPU servers. It separates host LLM serving from agent execution
and records business metrics together with CPU, GPU, and DRAM bandwidth metrics.

## What Runs

- vLLM serves an OpenAI-compatible API on the host.
- Agent workers run through `mini_swe_agent_team_v2`.
- Workers can run as host processes or Docker containers.
- Optional repo-context mode scans a real repository before each agent call.
- The dashboard displays sweep results, CPU metrics, GPU metrics, DRAM bandwidth,
  agent rows, issue rows, and logs.

## Repository Layout

```text
aab_framework/
  cli.py                         command line entry point
  dashboard.py                   dashboard HTTP server and API
  metrics.py                     aligned sweep metrics summary
  team_v2/                       mini-swe-agent team runner
  dashboard_static/              browser UI

bin/
  start_dashboard.sh
  start_vllm_8x5090.sh
  run_mini_swe_agent_team_v2_sweep_with_metrics.sh

docs/
  deployment.md
  mini_swe_agent_team_v2.md
  methodology.md
```

## Quick Deploy

```bash
cp .env.example .env
docker compose up --build dashboard
```

The dashboard listens on `http://localhost:8080` by default. For host-level
metrics collection and Docker-based agent execution, run the benchmark scripts
directly on the host so they can access Docker and generic Linux `/proc` CPU/memory collectors.

Host dashboard:

```bash
AAB_UI_PORT=8080 bin/start_dashboard.sh
```

## Configuration with `.env`

The sweep runner automatically loads `.env` from the project directory. This avoids
retyping the Agent, repository, LiteLLM, and CPU/memory settings for every run:

```bash
cp .env.example .env
chmod 600 .env
# Edit .env and set OPENAI_API_KEY locally; never commit the real key.
bin/run_mini_swe_agent_team_v2_sweep_with_metrics.sh
```

To use another file, set `AAB_ENV_FILE=/path/to/run.env`. Explicitly exported shell
variables take precedence over the file, so one-off overrides remain possible:

```bash
AAB_ENV_FILE=/path/to/run.env AGENT_SWEEP="1 2 4" PARALLELISM=4 \
  bin/run_mini_swe_agent_team_v2_sweep_with_metrics.sh
```

## Generic CPU and memory metrics

This generic copy intentionally does not require Intel PCM, DCGM, or a local GPU.
It samples CPU utilization/load and host memory from Linux `/proc` files. DRAM
bandwidth is optional and is not treated as available when no platform backend exists.

## Start vLLM

```bash
MODEL=/home/user/models/Qwen2.5-Coder-32B-Instruct \
TP=8 \
MAX_MODEL_LEN=4096 \
MAX_NUM_SEQS=128 \
MAX_NUM_BATCHED_TOKENS=16384 \
bin/start_vllm_8x5090.sh
```

The LiteLLM OpenAI-compatible API defaults to `http://127.0.0.1:4000/v1` with served model name
`DeepSeek-V4-Flash`.

## LiteLLM connection

This Intel server version keeps the historical `VLLM_BASE_URL` variable name for
compatibility, but it should point to the LiteLLM proxy, not directly to vLLM:

```bash
export VLLM_BASE_URL=http://127.0.0.1:4000/v1
export OPENAI_API_KEY="<your-LiteLLM-key>"
export MODEL=DeepSeek-V4-Flash
```

The key is read only from the process environment. Docker Agent workers inherit it
via `-e OPENAI_API_KEY` without writing it to the repository.

The adapter adds the `openai/` provider prefix internally when a model is supplied without one, so `MODEL=DeepSeek-V4-Flash` works with the LiteLLM OpenAI-compatible endpoint.

## Run a Mock Sweep

```bash
python3 -m aab_framework.cli sweep \
  --workload mini_swe_agent_team_v2 \
  --agent-counts 1,2,4,8 \
  --context-lengths 1024,2048,4096 \
  --parallelism 4 \
  --adapter-mode mock \
  --runtime-type process
```

## Run a Real Repo-Context Sweep

Use a full Django clone as the repo source:

```bash
git clone https://github.com/django/django.git /home/user/repos/django
```

Run mini-swe-agent through Docker with per-agent workspaces and metrics:

```bash
AGENT_SWEEP="1 2 4 8 16 32 64 128" \
CONTEXT_LENGTH=4096 \
PARALLELISM=8 \
ADAPTER_MODE=cli \
RUNTIME_TYPE=docker \
MINI_COMMAND=mini \
MODEL=DeepSeek-V4-Flash \
VLLM_BASE_URL=http://127.0.0.1:4000/v1 \
TASK_SOURCE=local \
TASK="Inspect the Django repository and identify a focused code-quality fix." \
VERIFY_COMMAND="python -m pytest --collect-only -q" \
AAB_REPO_CONTEXT_ENABLED=1 \
AAB_REPO_SOURCE=/home/user/repos/django \
AAB_REPO_WORKSPACE_MODE=worktree \
AAB_REPO_CONTEXT_INCLUDE_GIT_HISTORY=1 \
AAB_REPO_CONTEXT_PYTEST_COLLECT=1 \
bin/run_mini_swe_agent_team_v2_sweep_with_metrics.sh
```

Each child run writes `result.json`; the sweep wrapper combines child results
into a group `result.json`, `sweep.json`, and `team_sweep_summary.csv`.


The Agent worker image sets `MSWEA_CONFIGURED=1` so unattended Docker workers do not open the mini-SWE-agent first-run setup wizard. API credentials are still supplied only at runtime via `OPENAI_API_KEY`.

## Build the Agent Image

```bash
docker build -f docker/mini-swe-agent.Dockerfile -t aab-mini-swe-agent:latest .
```

If you use a custom image, set `RUNTIME_TYPE=docker` and override
`TeamRunConfig.runtime_image` from Python, or keep the default image tag above.

## Verification

```bash
python3 -m unittest discover -s tests
```

The repository also includes a packaging test that ensures the current codebase
contains no legacy VM runtime references and has direct deployment entrypoints.

## Generic host monitor

Use `scripts/generic_host_monitor.py` to wrap Agent or SWE-bench commands. It uses
Linux `/proc` and has no generic Linux CPU/memory collectors, DCGM, or local GPU dependency:

```bash
python3 scripts/generic_host_monitor.py \
  --output-dir runs/standalone-smoke/metrics \
  --interval 1 \
  --docker-stats \
  -- \
  mini-extra swebench --subset lite --split dev --slice 0:1 --workers 1
```

It writes `cpu.csv`, `memory.csv`, optional `docker_stats.tsv`, command logs, and
`monitor.json`. The sweep wrapper uses the same CPU/memory sampling contract.
