# mini_swe_agent_team_v2

`mini_swe_agent_team_v2` is the coding-agent workload used by this benchmark.
It runs synthetic smoke tasks, local repository tasks, or JSONL task lists, then
aggregates agent, issue, latency, throughput, and host metrics into `result.json`.

## Runtime Roles

- `TeamOrchestrator`: creates the run directory, workers, issue plans, metrics
  observer, and final result.
- `TaskPlanner`: creates synthetic tasks, local `cwd --task` style tasks, or
  tasks loaded from an instances file.
- `RepoWorkspaceManager`: gives each agent an independent source, copy, or git
  worktree workspace.
- `RepoContextBuilder`: scans real repo files, optional git history, and optional
  pytest collection output before the agent call.
- `MiniSweAgentAdapter`: runs mock mode for tests or invokes mini-swe-agent in
  process or Docker mode.
- `PatchReviewerAgent`, `TestVerifierAgent`, and `RepairLoopController`: review,
  verify, and decide whether another round is needed.
- `MetricsObserver`: reads existing collector outputs and emits structured
  `metrics_summary`, `metrics_timeline`, and attribution metadata.

## Data Flow

```text
CLI or dashboard
  -> TeamRunConfig
  -> TaskPlanner
  -> RepoWorkspaceManager
  -> RepoContextBuilder
  -> MiniSweAgentAdapter
  -> verifier and reviewer
  -> ResultAggregator
  -> result.json
  -> dashboard /api/run
```

## Local Repo Mode

Local mode is the closest shape to `cwd --task`: the repo path is used as the
task workspace, or copied/worktreed per agent when `repo_workspace_mode` is
`copy` or `worktree`.

```bash
python3 -m aab_framework.cli run \
  --workload mini_swe_agent_team_v2 \
  --num-agents 4 \
  --parallelism 4 \
  --context-length 4096 \
  --adapter-mode cli \
  --runtime-type docker \
  --task-source local \
  --repo-source /home/user/repos/django \
  --task "Inspect the Django repository and make a focused improvement." \
  --verify-command "python -m pytest --collect-only -q" \
  --repo-workspace-mode worktree
```

## Repo Context

Repo context mode performs real context-building work before each agent call:

```text
workspace -> file selection -> file reads -> symbol/import extraction
          -> context_bundle.txt -> prompt augmentation
```

Optional additions:

- `--repo-context-include-git-history` scans recent git objects and logs.
- `--repo-context-pytest-collect` runs the configured pytest collection command.
- `--repo-context-prompt-max-chars` controls how much context is appended to the
  mini-swe-agent task prompt.

## Sweep With Metrics

```bash
AGENT_SWEEP="1 2 4 8 16 32 64" \
CONTEXT_LENGTH=4096 \
PARALLELISM=8 \
ADAPTER_MODE=cli \
RUNTIME_TYPE=docker \
TASK_SOURCE=local \
TASK="Inspect the repository and make a focused improvement." \
VERIFY_COMMAND="python -m pytest --collect-only -q" \
AAB_REPO_CONTEXT_ENABLED=1 \
AAB_REPO_SOURCE=/home/user/repos/django \
AAB_REPO_WORKSPACE_MODE=worktree \
AAB_REPO_CONTEXT_INCLUDE_GIT_HISTORY=1 \
AAB_REPO_CONTEXT_PYTEST_COLLECT=1 \
bin/run_mini_swe_agent_team_v2_sweep_with_metrics.sh
```

The wrapper starts CPU, GPU, and AMD PCM collectors around each child run,
refreshes each child `result.json`, then builds a sweep group result from all
child runs.

## Result Shape

Each issue records:

- selected workspace and preparation time
- repo context scan counts and bundle paths
- per-round stdout, stderr, patch path, diff path, verification, review, and
  stage timings
- final verified status and error string if the issue failed

Each sweep point records:

- agent count and context length
- success rate, issue latency, and throughput
- CPU p50/p95/max
- GPU p95/max and GPU memory
- DRAM bandwidth avg/p95/max

## Notes

Synthetic tasks are useful for smoke tests. Real repo-context tasks are the
recommended path for measuring host CPU and DRAM behavior because they perform
real filesystem, git, parser-like, and test collection work rather than synthetic
memory pressure.
