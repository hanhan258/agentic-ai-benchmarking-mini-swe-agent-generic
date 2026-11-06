# Agentic AI Benchmarking Mini SWE Agent（通用 Linux CPU/内存版）

这是一个面向 Agent 集群的基准测试框架，围绕 `mini-SWE-agent` 执行代码任务，并记录任务成功率、吞吐、延迟以及主机 CPU 和内存指标。

本仓库适合没有本地 GPU、模型服务部署在外部节点的 CPU Agent 服务器或 CPU 机柜。

## 主要能力

- 通过 LiteLLM 或其他 OpenAI 兼容接口调用外部大模型；
- 使用 `mini_swe_agent_team_v2` 运行多个 Agent；
- 支持宿主机进程和 Docker Worker；
- 支持真实 Git 仓库上下文扫描；
- 支持独立 Git worktree，避免多个 Agent 修改同一工作目录；
- 记录 CPU、主机内存、load、swap 和 Docker 容器指标；
- 支持标准 SWE-bench 命令的通用主机监控包装。

本版本**不依赖 Intel PCM、DCGM 或本地 GPU**。CPU 和主机内存指标通过 Linux `/proc` 采集；DRAM 带宽如果没有平台专用后端则标记为不可用，不伪造为 0。

## 目录结构

```text
aab_framework/                         Agent benchmark 主体
  cli.py                               CLI 入口
  dashboard.py                         Dashboard 服务
  team_v2/                             Agent Team v2 编排器
  dashboard_static/                    Dashboard 前端

bin/
  run_mini_swe_agent_team_v2_sweep_with_metrics.sh
  start_dashboard.sh

scripts/
  generic_host_monitor.py              通用 CPU/内存监控包装器

docs/
  deployment.md
  mini_swe_agent_team_v2.md
  methodology.md
```

## 配置文件方式

Runner 会自动读取项目目录下的 `.env`，显式导出的 Shell 环境变量优先级更高。

```bash
cd /home/test/agentic-ai-benchmarking-mini-swe-agent-generic
cp .env.example .env
chmod 600 .env
# 编辑 .env，设置 OPENAI_API_KEY 和目标仓库
```

然后直接运行：

```bash
bin/run_mini_swe_agent_team_v2_sweep_with_metrics.sh
```

也可以指定其他配置文件：

```bash
AAB_ENV_FILE=/home/test/configs/click.env \\
  bin/run_mini_swe_agent_team_v2_sweep_with_metrics.sh
```

不要把真实 API key 写入 Git、Dockerfile 或镜像。

## LiteLLM 配置

本项目保留历史变量名 `VLLM_BASE_URL`，但它可以指向外部 LiteLLM OpenAI 兼容入口：

```bash
VLLM_BASE_URL=http://127.0.0.1:4000/v1
OPENAI_API_KEY=你的LiteLLM密钥
MODEL=DeepSeek-V4-Flash
```

Agent 运行时会自动为没有 provider 前缀的模型名补充 `openai/`。

## 运行本地仓库 Agent sweep

```bash
export VLLM_BASE_URL=http://127.0.0.1:4000/v1
export OPENAI_API_KEY='新的LiteLLM key'
export MODEL=DeepSeek-V4-Flash

AGENT_SWEEP="1 2 4 8" \\
PARALLELISM=4 \\
CONTEXT_LENGTH=4096 \\
ADAPTER_MODE=cli \\
RUNTIME_TYPE=docker \\
TASK_SOURCE=local \\
AAB_REPO_SOURCE=/home/test/repos/click \\
AAB_REPO_WORKSPACE_MODE=worktree \\
TASK="检查Click仓库并完成一个小范围代码改进。" \\
VERIFY_COMMAND="PYTHONPATH=src python3 -m pytest -q tests/test_compat.py" \\
bin/run_mini_swe_agent_team_v2_sweep_with_metrics.sh
```

每个测试点会生成：

- `result.json`；
- Agent trajectory、stdout、stderr；
- patch、diff 和验证日志；
- `metrics/cpu.csv`；
- `metrics/memory.csv`；
- Docker 运行时日志（如适用）。

## 通用主机监控工具

可用独立脚本包住任意 Agent 或 SWE-bench 命令：

```bash
python3 scripts/generic_host_monitor.py \\
  --output-dir runs/standalone-smoke/metrics \\
  --interval 1 \\
  --docker-stats \\
  -- \\
  mini-extra swebench --subset lite --split dev --slice 0:1 --workers 1
```

输出包括：

```text
cpu.csv
memory.csv
docker_stats.tsv
command.stdout
command.stderr
monitor.json
```

## 标准 SWE-bench

标准 SWE-bench 使用官方 `mini-extra swebench`，本仓库提供的通用监控脚本只负责记录主机 CPU/内存和 Docker stats。

```bash
export OPENAI_API_KEY='新的LiteLLM key'
export SWE_API_BASE=http://127.0.0.1:4000/v1
export SWE_MODEL=openai/DeepSeek-V4-Flash

python3 scripts/generic_host_monitor.py \\
  --output-dir runs/swebench-lite-smoke/metrics \\
  --interval 1 \\
  --docker-stats \\
  -- \\
  mini-extra swebench \\
    --subset lite \\
    --split dev \\
    --slice 0:1 \\
    --workers 1 \\
    --environment-class docker \\
    --model "$SWE_MODEL" \\
    --output runs/swebench-lite-smoke/output \\
    -c swebench.yaml \\
    -c model.model_kwargs.api_base="$SWE_API_BASE" \\
    -c model.model_kwargs.drop_params=true \\
    -c model.cost_tracking=ignore_errors
```

自定义 Agent 的 `verified_success_rate` 和标准 SWE-bench 的 `resolved_rate` 是不同指标，不能混用。

## 验证

```bash
python3 -m unittest discover -s tests
python3 -m compileall -q aab_framework tests scripts
bash -n bin/run_mini_swe_agent_team_v2_sweep_with_metrics.sh
```

## 上游项目

本仓库基于：

```text
https://github.com/changzhi1990/agentic-ai-benchmarking-mini-swe-agent
```

当前仓库针对通用 Linux CPU/内存监控进行了适配。
