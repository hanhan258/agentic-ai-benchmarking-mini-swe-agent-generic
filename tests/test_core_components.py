from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aab_framework.agent_team import (
    AgentRoleSpec,
    AgentTeamSpec,
    ChallengeAgent,
    PluginRegistry,
    WorkloadSpec,
)
from aab_framework.dcgm import DCGM_CSV_FIELDS, format_dcgm_csv_rows, parse_dcgm_dmon_lines
from aab_framework.launch import expand_cpu_list, plan_vm_placement
from aab_framework.metrics import summarize_agent_sweep
from aab_framework.nvtop import GPU_CSV_FIELDS, format_gpu_csv_rows, parse_nvtop_snapshot
from aab_framework.sweep import plan_role_separated_sweep
from aab_framework.vllm import (
    VllmDockerConfig,
    build_vllm_container_command,
    build_vllm_serve_command,
)
from aab_framework.workloads.coding import (
    build_coding_chat_payload_template,
    build_coding_prompt_template,
    build_coding_result_schema,
    build_coding_trace_schema,
    build_coding_workload_spec,
)
from aab_framework.workloads.mini_swe_agent_team_v2 import build_mini_swe_agent_team_v2_workload_spec


class CoreComponentTests(unittest.TestCase):
    def test_build_vllm_docker_command_for_8x5090(self) -> None:
        command = build_vllm_container_command(
            VllmDockerConfig(
                model="/home/user/models/Qwen2.5-Coder-32B-Instruct",
                image="vllm/vllm-openai:latest",
                served_model_name="agentic-model",
                api_key="token-abc123",
                tensor_parallel_size=8,
                port=8000,
            )
        )

        self.assertIn("docker run -itd", command)
        self.assertIn("--gpus all", command)
        self.assertIn("--runtime=nvidia", command)
        self.assertIn("--network host", command)
        self.assertIn("--ipc=host", command)
        self.assertIn("--shm-size 128G", command)
        self.assertIn("-e NCCL_P2P_LEVEL=SYS", command)
        self.assertIn("-v /home/user/models:/workspace/models", command)

    def test_build_vllm_serve_command_exposes_gpu_memory_tuning_knobs(self) -> None:
        command = build_vllm_serve_command(
            VllmDockerConfig(
                model="/home/user/models/Qwen2.5-Coder-32B-Instruct",
                gpu_memory_utilization=0.95,
                max_model_len=32768,
                max_num_seqs=64,
                max_num_batched_tokens=131072,
                enable_auto_tool_choice=True,
                tool_call_parser="hermes",
            )
        )

        self.assertIn("--gpu-memory-utilization 0.95", command)
        self.assertIn("--max-model-len 32768", command)
        self.assertIn("--max-num-seqs 64", command)
        self.assertIn("--max-num-batched-tokens 131072", command)
        self.assertIn("--enable-auto-tool-choice", command)
        self.assertIn("--tool-call-parser hermes", command)

    def test_start_vllm_script_defaults_nccl_p2p_level_to_sys(self) -> None:
        script = Path("bin/start_vllm_8x5090.sh").read_text(encoding="utf-8")

        self.assertIn('NCCL_P2P_LEVEL="${NCCL_P2P_LEVEL:-SYS}"', script)
        self.assertIn('GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.9}"', script)
        self.assertIn('MAX_MODEL_LEN="${MAX_MODEL_LEN:-}"', script)
        self.assertIn('MAX_NUM_BATCHED_TOKENS="${MAX_NUM_BATCHED_TOKENS:-}"', script)
        self.assertIn('ENABLE_AUTO_TOOL_CHOICE="${ENABLE_AUTO_TOOL_CHOICE:-0}"', script)

    def test_coding_workload_declares_agent_team_without_runtime_details(self) -> None:
        workload = build_coding_workload_spec()

        self.assertEqual(workload.name, "coding")
        self.assertEqual(workload.default_team.name, "coding-bugfix-team")
        self.assertIn("planner", workload.default_team.role_names)
        self.assertEqual(workload.default_team.challenge_role, "challenge")
        self.assertEqual(workload.executor_specific_fields, ())
        self.assertIn("success_rate_pct", workload.base_metrics)
        self.assertIn("patch_plan", workload.business_metrics)

    def test_plugin_registry_keeps_workloads_separate(self) -> None:
        registry = PluginRegistry()
        registry.register_workload(build_coding_workload_spec())
        registry.register_workload(build_mini_swe_agent_team_v2_workload_spec())

        self.assertEqual(registry.workload("coding").name, "coding")
        self.assertEqual(registry.workload("mini_swe_agent_team_v2").name, "mini_swe_agent_team_v2")
        self.assertEqual(registry.workload_names(), ["coding", "mini_swe_agent_team_v2"])
        self.assertEqual(registry.executor_names(), [])

    def test_challenge_agent_blocks_workload_with_runtime_coupling(self) -> None:
        workload = WorkloadSpec(
            name="bad-workload",
            description="Invalid workload with runtime leakage.",
            default_team=AgentTeamSpec(
                name="bad-team",
                roles=(AgentRoleSpec(name="solver", responsibility="Solve the task."),),
                challenge_role=None,
            ),
            base_metrics=("success_rate_pct",),
            business_metrics=("task_quality",),
            executor_specific_fields=("host_device",),
        )

        review = ChallengeAgent().review_workload(workload)

        self.assertTrue(review.blocked)
        self.assertEqual(review.verdict, "BLOCKED")

    def test_cli_workload_contract_templates_are_stable(self) -> None:
        prompt = build_coding_prompt_template()
        payload = build_coding_chat_payload_template()
        trace_schema = build_coding_trace_schema()
        result_schema = build_coding_result_schema()

        self.assertIn("retry_state is not persisted after timeout", prompt)
        self.assertIn("${task_id}", prompt)
        self.assertIn("${prompt}", payload)
        self.assertIn("${llm_max_tokens}", payload)
        self.assertIn("task_id", trace_schema.required_fields)
        self.assertIn("event_type", trace_schema.required_fields)
        self.assertIn("vllm_health", result_schema.required_fields)
        self.assertIn("completed_tasks", result_schema.required_fields)

    def test_expand_cpu_list_parses_ranges_and_singletons(self) -> None:
        self.assertEqual(expand_cpu_list("0-3,8,10-11"), [0, 1, 2, 3, 8, 10, 11])

    def test_plan_vm_placement_binds_agents_across_numa_nodes(self) -> None:
        numa_cpu_lists = {
            0: list(range(0, 16)),
            1: list(range(64, 80)),
        }

        placements = [
            plan_vm_placement(
                vm_index=index,
                vcpu_count=4,
                host_cpu_count=128,
                cpu_pinning=True,
                numa_policy="bind-by-agent",
                numa_cpu_lists=numa_cpu_lists,
            )
            for index in range(4)
        ]

        self.assertEqual([item.numa_node for item in placements], [0, 1, 0, 1])
        self.assertEqual([item.cpu_set for item in placements], ["0-3", "64-67", "4-7", "68-71"])

    def test_role_separated_sweep_scales_one_task_per_agent(self) -> None:
        rows = plan_role_separated_sweep([2, 4, 8])

        self.assertEqual([row.agents for row in rows], [2, 4, 8])
        self.assertEqual([row.vm_count for row in rows], [2, 4, 8])
        self.assertEqual([row.total_tasks for row in rows], [2, 4, 8])

    def test_nvtop_snapshot_parser_outputs_compatible_gpu_csv_rows(self) -> None:
        snapshot = json.dumps(
            [
                {
                    "device_name": "NVIDIA GeForce RTX 5090",
                    "gpu_util": "87%",
                    "mem_util": "95%",
                    "mem_used": str(31 * 1024 * 1024 * 1024),
                    "mem_total": str(32 * 1024 * 1024 * 1024),
                    "power_draw": "251W",
                    "temp": "42C",
                }
            ]
        )

        rows = parse_nvtop_snapshot(snapshot, timestamp=123)
        csv_line = format_gpu_csv_rows(rows)

        self.assertEqual(GPU_CSV_FIELDS[0], "timestamp")
        self.assertEqual(rows[0]["utilization_gpu_pct"], "87")
        self.assertEqual(rows[0]["memory_used_mib"], "31744.0")
        self.assertEqual(rows[0]["gpu_metrics_backend"], "nvtop")
        self.assertEqual(len(csv_line.split(",")), len(GPU_CSV_FIELDS))

    def test_dcgm_dmon_parser_outputs_normalized_compute_metric_rows(self) -> None:
        lines = [
            "# gpu gputl mcutl fbused fbtotal power temp sm_active sm_occupancy tensor_active dram_active fp32_active fp16_active",
            "GPU 0 0.42 0.24 29305 32607 125.5 42 0.31 0.18 0.21 0.11 0.07 0.09",
            "GPU 1 42 24 29305 32607 125.5 42 31 18 21 11 7 9",
        ]

        rows = parse_dcgm_dmon_lines(
            lines,
            field_ids="203,204,252,250,155,150,1002,1003,1004,1005,1007,1008",
            timestamp=123,
        )
        csv_line = format_dcgm_csv_rows(rows)

        self.assertEqual(DCGM_CSV_FIELDS[0], "timestamp")
        self.assertEqual(rows[0]["utilization_gpu_pct"], "42.0")
        self.assertEqual(rows[0]["sm_active_pct"], "31.0")
        self.assertEqual(rows[1]["fp16_active_pct"], "9.0")
        self.assertEqual(len(csv_line.splitlines()[0].split(",")), len(DCGM_CSV_FIELDS))

    def test_summarize_agent_sweep_writes_aligned_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            point = root / "agents_2"
            metrics = point / "metrics"
            results = point / "results"
            metrics.mkdir(parents=True)
            results.mkdir(parents=True)
            (results / "summary.json").write_text(
                json.dumps({"vm_results": 2, "completed_tasks": 2, "failed_tasks": 0, "vllm_ok": 2}),
                encoding="utf-8",
            )
            (results / "agent-000.trace.jsonl").write_text(
                json.dumps({"task_id": "agent-000-task-0", "status": "ok", "latency_ms": 100}) + "\n",
                encoding="utf-8",
            )
            (results / "agent-000.result.json").write_text(
                json.dumps({"memory_workers": 8, "memory_mode": "read"}),
                encoding="utf-8",
            )
            (metrics / "cpu.csv").write_text(
                "timestamp,cpu_util_pct,user_pct,system_pct,iowait_pct,idle_pct,load1,load5,load15\n"
                "1,10,8,2,0,90,1,1,1\n"
                "2,20,16,4,0,80,2,2,2\n",
                encoding="utf-8",
            )
            (metrics / "gpu.csv").write_text(
                "timestamp,index,utilization_gpu_pct,utilization_memory_pct,memory_used_mib,memory_total_mib,power_draw_w,temperature_c\n"
                "1,0,0,0,100,1000,50,30\n"
                "2,0,50,20,200,1000,100,35\n",
                encoding="utf-8",
            )
            (metrics / "memory.csv").write_text(

                "timestamp,mem_total_mib,mem_used_mib,mem_available_mib,buffers_mib,cached_mib,swap_total_mib,swap_used_mib,load1,load5,load15\n"

                "1,1024,500,524,20,200,0,0,1,1,1\n"

                "2,1024,600,424,20,200,0,0,2,2,2\n",

                encoding="utf-8",

            )

            rows = summarize_agent_sweep(root, run_seconds=60, workload_seconds=30)
            aligned_exists = (root / "aligned_metrics.csv").exists()

            self.assertEqual(rows[0]["agents"], 2)
            self.assertEqual(rows[0]["completed"], 2)
            self.assertEqual(rows[0]["dram_bw_p95_gbps"], "")
            self.assertEqual(rows[0]["gpu_util_p95_pct"], "")
            self.assertTrue(aligned_exists)


if __name__ == "__main__":
    unittest.main()
