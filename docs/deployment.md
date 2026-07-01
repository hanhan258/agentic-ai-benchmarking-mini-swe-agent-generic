# Deployment

This project can be deployed in two modes:

- Docker Compose dashboard for viewing runs and checking the UI quickly.
- Host deployment for real sweeps with vLLM, Docker agent workers, and metrics
  collectors.

## Dashboard With Docker Compose

```bash
cp .env.example .env
docker compose up --build dashboard
```

Open `http://localhost:8080`.

The compose service mounts `./runs` into the container, so run results written on
the host are visible in the dashboard.

## Host Dashboard

Use host mode when the dashboard should launch sweeps or when scripts need
access to local `docker`, `dcgmi`, and AMD PCM tooling:

```bash
python3 -m pip install -e .
AAB_UI_PORT=8080 bin/start_dashboard.sh
```

## Build the Agent Worker Image

```bash
docker build -f docker/mini-swe-agent.Dockerfile -t aab-mini-swe-agent:latest .
```

The team runner defaults to that image when `RUNTIME_TYPE=docker`.

## Start vLLM

```bash
MODEL=/home/user/models/Qwen2.5-Coder-32B-Instruct \
TP=8 \
MAX_MODEL_LEN=4096 \
MAX_NUM_SEQS=128 \
MAX_NUM_BATCHED_TOKENS=16384 \
bin/start_vllm_8x5090.sh
```

Verify:

```bash
curl -fsS http://127.0.0.1:8000/v1/models -H "Authorization: Bearer token-abc123"
```

## Run a Django Sweep

```bash
git clone https://github.com/django/django.git /home/user/repos/django
```

```bash
AGENT_SWEEP="1 2 4 8 16 32 64 128" \
CONTEXT_LENGTH=4096 \
PARALLELISM=8 \
ADAPTER_MODE=cli \
RUNTIME_TYPE=docker \
MODEL=agentic-model \
VLLM_BASE_URL=http://127.0.0.1:8000/v1 \
TASK_SOURCE=local \
TASK="Inspect the Django repository and make a focused improvement." \
VERIFY_COMMAND="python -m pytest --collect-only -q" \
AAB_REPO_CONTEXT_ENABLED=1 \
AAB_REPO_SOURCE=/home/user/repos/django \
AAB_REPO_WORKSPACE_MODE=worktree \
AAB_REPO_CONTEXT_INCLUDE_GIT_HISTORY=1 \
AAB_REPO_CONTEXT_PYTEST_COLLECT=1 \
bin/run_mini_swe_agent_team_v2_sweep_with_metrics.sh
```

Results are written under `runs/`. The dashboard automatically lists runs that
contain `result.json`, `sweep.json`, `dashboard-run.json`, `aligned_metrics.csv`,
or `sweep_summary.csv`.

## Validation

```bash
python3 -m unittest discover -s tests
docker compose config
```
