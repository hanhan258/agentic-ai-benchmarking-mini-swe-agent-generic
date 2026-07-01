from __future__ import annotations

import json
import multiprocessing
import queue
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aab_framework.dashboard import (
    DashboardState,
    SweepLaunchConfig,
    build_sweep_environment,
    dashboard_plugins_payload,
    ensure_aligned_metrics,
    list_runs,
    load_run_report,
    parse_agents_list,
    require_vllm_ready,
)


class _FakeProcess:
    pid = 12345

    def poll(self) -> None:
        return None


def _start_sweep_worker(project_root: str, result_queue: multiprocessing.Queue) -> None:
    with (
        patch("aab_framework.dashboard.require_vllm_ready"),
        patch("aab_framework.dashboard.subprocess.Popen", return_value=_FakeProcess()),
    ):
        state = DashboardState(Path(project_root))
        status = state.start_sweep(SweepLaunchConfig(agents=[1], run_name="Deadlock Test"))
        result_queue.put(status)


class DashboardTests(unittest.TestCase):
    def test_parse_agents_list_accepts_spaces_commas_and_deduplicates(self) -> None:
        self.assertEqual(parse_agents_list("2, 4 8\n16 16"), [2, 4, 8, 16])

    def test_parse_agents_list_rejects_unsafe_values(self) -> None:
        with self.assertRaises(ValueError):
            parse_agents_list("2 && rm -rf /")
        with self.assertRaises(ValueError):
            parse_agents_list("0 2")
        with self.assertRaises(ValueError):
            parse_agents_list("1025")

    def test_build_sweep_environment_sets_team_v2_runner_knobs(self) -> None:
        config = SweepLaunchConfig(
            agents=[2, 4],
            context_length=4096,
            parallelism=8,
            adapter_mode="cli",
            runtime_type="docker",
            model="agentic-model",
            vllm_base_url="http://127.0.0.1:8000/v1",
            mini_command="mini",
            task_source="local",
            task="Inspect the repository.",
            verify_command="python -m pytest",
            repo_context_enabled=True,
            repo_source="/tmp/repo",
            repo_workspace_mode="worktree",
            repo_context_include_git_history=True,
            repo_context_pytest_collect=True,
            sudo_password="secret",
            run_name="Nightly Smoke",
        )

        env = build_sweep_environment(config, timestamp="20260701-120000")

        self.assertEqual(env["AGENT_SWEEP"], "2 4")
        self.assertEqual(env["CONTEXT_LENGTH"], "4096")
        self.assertEqual(env["PARALLELISM"], "8")
        self.assertEqual(env["ADAPTER_MODE"], "cli")
        self.assertEqual(env["RUNTIME_TYPE"], "docker")
        self.assertEqual(env["TASK_SOURCE"], "local")
        self.assertEqual(env["TASK"], "Inspect the repository.")
        self.assertEqual(env["VERIFY_COMMAND"], "python -m pytest")
        self.assertEqual(env["AAB_REPO_CONTEXT_ENABLED"], "1")
        self.assertEqual(env["AAB_REPO_SOURCE"], "/tmp/repo")
        self.assertEqual(env["AAB_REPO_CONTEXT_INCLUDE_GIT_HISTORY"], "1")
        self.assertEqual(env["AAB_REPO_CONTEXT_PYTEST_COLLECT"], "1")
        self.assertEqual(env["SUDO_PASSWORD"], "secret")
        self.assertEqual(env["SWEEP_ROOT"], "runs/dashboard-nightly-smoke-20260701-120000")

    def test_start_sweep_uses_team_v2_wrapper_and_returns_status_without_deadlocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result_queue: multiprocessing.Queue = multiprocessing.Queue()
            process = multiprocessing.Process(target=_start_sweep_worker, args=(tmp, result_queue))
            process.start()
            process.join(timeout=2)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
                self.fail("start_sweep did not return; likely lock re-entry deadlock")
            self.assertEqual(process.exitcode, 0)
            try:
                status = result_queue.get_nowait()
            except queue.Empty as exc:
                raise AssertionError("start_sweep returned no status") from exc
            self.assertTrue(status["running"])
            self.assertIn("dashboard-deadlock-test-", status["sweep_root"])

    def test_start_sweep_requires_vllm_ready_before_launching_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = DashboardState(Path(tmp))

            with (
                patch(
                    "aab_framework.dashboard.subprocess.run",
                    return_value=SimpleNamespace(returncode=7, stderr="curl: connection refused"),
                ),
                patch("aab_framework.dashboard.subprocess.Popen") as popen,
            ):
                with self.assertRaisesRegex(RuntimeError, "vLLM is unavailable"):
                    state.start_sweep(SweepLaunchConfig(agents=[1]))

            popen.assert_not_called()

    def test_require_vllm_ready_includes_probe_error_details(self) -> None:
        with patch(
            "aab_framework.dashboard.subprocess.run",
            return_value=SimpleNamespace(returncode=7, stderr="curl: connection refused"),
        ):
            with self.assertRaisesRegex(RuntimeError, "curl: connection refused"):
                require_vllm_ready()

    def test_list_runs_uses_dashboard_run_name_for_display(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp) / "runs"
            run_dir = runs_dir / "dashboard-nightly-smoke-20260701-120000"
            run_dir.mkdir(parents=True)
            (run_dir / "dashboard-run.json").write_text(
                json.dumps(
                    {
                        "display_name": "Nightly Smoke",
                        "sweep_root": "runs/dashboard-nightly-smoke-20260701-120000",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            runs = list_runs(runs_dir)

            self.assertEqual(runs[0]["name"], "dashboard-nightly-smoke-20260701-120000")
            self.assertEqual(runs[0]["display_name"], "Nightly Smoke")

    def test_ensure_aligned_metrics_generates_missing_dashboard_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "runs" / "dashboard-manual"
            point = run / "agents_1"
            metrics = point / "metrics"
            results = point / "results"
            metrics.mkdir(parents=True)
            results.mkdir(parents=True)
            (run / "dashboard-run.json").write_text(
                json.dumps({"display_name": "manual", "run_seconds": 180, "workload_grace_seconds": 60}) + "\n",
                encoding="utf-8",
            )
            (run / "sweep_summary.csv").write_text(
                "agents,vm_results,completed_tasks,failed_tasks,vllm_ok\n1,1,1,0,1\n",
                encoding="utf-8",
            )
            (results / "summary.json").write_text(
                json.dumps({"vm_results": 1, "completed_tasks": 1, "failed_tasks": 0, "vllm_ok": 1}),
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
                "1,10,8,2,0,90,1,1,1\n",
                encoding="utf-8",
            )
            (metrics / "gpu.csv").write_text(
                "timestamp,index,utilization_gpu_pct,utilization_memory_pct,memory_used_mib,memory_total_mib,power_draw_w,temperature_c\n"
                "1,0,50,20,200,1000,100,35\n",
                encoding="utf-8",
            )

            generated = ensure_aligned_metrics(run)
            report = load_run_report(run)

            self.assertTrue(generated)
            self.assertTrue((run / "aligned_metrics.csv").exists())
            self.assertEqual(report["points"][0]["success_rate_pct"], 100)
            self.assertEqual(report["points"][0]["lat_ok_p95_ms"], 100)

    def test_dashboard_plugins_payload_lists_team_v2_runtimes(self) -> None:
        payload = dashboard_plugins_payload()

        workload_names = [item["name"] for item in payload["workloads"]]
        runtime_names = [item["name"] for item in payload["runtimes"]]
        self.assertIn("mini_swe_agent_team_v2", workload_names)
        self.assertEqual(runtime_names, ["process", "docker"])
        self.assertEqual(payload["challenge_reviews"]["workloads"]["mini_swe_agent_team_v2"]["verdict"], "PASS")

    def test_dashboard_static_assets_expose_cpu_gpu_and_repo_controls(self) -> None:
        script = Path("aab_framework/dashboard_static/app.js").read_text(encoding="utf-8")
        html = Path("aab_framework/dashboard_static/index.html").read_text(encoding="utf-8")

        self.assertIn("CPU Metrics", html)
        self.assertIn("GPU Metrics", html)
        self.assertIn("Runtime<select id=\"runtimeSelect\"", html)
        self.assertIn("Repo source", html)
        self.assertIn("repoContextEnabledInput", html)
        self.assertIn("context_length: Number($(\"contextLengthInput\").value)", script)
        self.assertIn("runtime_type: $(\"runtimeSelect\").value", script)
        self.assertIn("repo_context_enabled: $(\"repoContextEnabledInput\").checked", script)
        self.assertIn('drawChart("cpuChart"', script)
        self.assertIn('drawChart("gpuUtilChart"', script)
        self.assertIn('drawChart("gpuMemoryChart"', script)


if __name__ == "__main__":
    unittest.main()
