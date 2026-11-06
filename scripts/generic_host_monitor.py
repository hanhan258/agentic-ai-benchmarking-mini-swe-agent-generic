#!/usr/bin/env python3
"""Dependency-free Linux CPU and host-memory monitor.

Usage:
  python3 scripts/generic_host_monitor.py --output-dir run/metrics -- \
      mini-extra swebench --subset lite --slice 0:1 --workers 1

The command is optional. Without it, use --duration to collect a fixed window.
No GPU/DCGM/PCM dependency is required.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

STOP = False


def stop(_sig, _frame):
    global STOP
    STOP = True


def read_cpu():
    fields = Path('/proc/stat').read_text().splitlines()[0].split()
    values = [int(x) for x in fields[1:9]]
    total = sum(values)
    idle = values[3] + values[4]
    return total, idle, values[0], values[2], values[4]


def read_memory():
    values = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, _, value = line.partition(':')
        if value:
            try:
                values[key] = float(value.strip().split()[0]) / 1024.0
            except (IndexError, ValueError):
                pass
    total = values.get('MemTotal', 0)
    available = values.get('MemAvailable', values.get('MemFree', 0))
    swap_total = values.get('SwapTotal', 0)
    swap_free = values.get('SwapFree', 0)
    return total, total - available, available, swap_total, swap_total - swap_free


def main():
    global STOP
    parser = argparse.ArgumentParser(description='Generic Linux CPU/memory monitor')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('--duration', type=float, default=0.0)
    parser.add_argument('--docker-stats', action='store_true')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error('--interval must be positive')
    if args.duration < 0:
        parser.error('--duration must be non-negative')
    target = args.command[1:] if args.command[:1] == ['--'] else args.command
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    cpu_path = out / 'cpu.csv'
    mem_path = out / 'memory.csv'
    docker_path = out / 'docker_stats.tsv'
    start = time.time()
    proc = None
    if target:
        proc = subprocess.Popen(target, stdout=(out / 'command.stdout').open('w'), stderr=(out / 'command.stderr').open('w'))
    cpu_file = cpu_path.open('w', newline='')
    mem_file = mem_path.open('w', newline='')
    cpu_writer = csv.writer(cpu_file)
    mem_writer = csv.writer(mem_file)
    cpu_writer.writerow(['timestamp','cpu_util_pct','user_pct','system_pct','iowait_pct','idle_pct','load1','load5','load15'])
    mem_writer.writerow(['timestamp','mem_total_mib','mem_used_mib','mem_available_mib','swap_total_mib','swap_used_mib','load1','load5','load15'])
    if args.docker_stats:
        docker_path.write_text('timestamp\tname\tcpu_pct\tmemory_usage\tmemory_pct\tnet_io\tblock_io\tpids\n')
    previous = read_cpu()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        while not STOP:
            now = time.time()
            if args.duration and now - start >= args.duration:
                break
            if proc is not None and proc.poll() is not None:
                break
            time.sleep(args.interval)
            current = read_cpu()
            total_delta = current[0] - previous[0]
            idle_delta = current[1] - previous[1]
            if total_delta > 0:
                util = 100 * (1 - idle_delta / total_delta)
                user = 100 * (current[2] - previous[2]) / total_delta
                system = 100 * (current[3] - previous[3]) / total_delta
                iowait = 100 * (current[4] - previous[4]) / total_delta
                load = Path('/proc/loadavg').read_text().split()[:3]
                ts = int(time.time())
                cpu_writer.writerow([ts, round(util,4), round(user,4), round(system,4), round(iowait,4), round(100-util,4), *load])
                total, used, available, swap_total, swap_used = read_memory()
                mem_writer.writerow([ts, round(total,3), round(used,3), round(available,3), round(swap_total,3), round(swap_used,3), *load])
                cpu_file.flush(); mem_file.flush()
                if args.docker_stats:
                    try:
                        result = subprocess.run(['docker','stats','--no-stream','--format','{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}\t{{.PIDs}}'], text=True, capture_output=True, check=False)
                        with docker_path.open('a') as handle:
                            for line in result.stdout.splitlines():
                                handle.write(f'{ts}\t{line}\n')
                    except OSError:
                        pass
            previous = current
    finally:
        STOP = True
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait()
        cpu_file.close(); mem_file.close()
        metadata = {'started_at_unix': start, 'ended_at_unix': time.time(), 'command': target, 'returncode': None if proc is None else proc.returncode, 'interval_sec': args.interval}
        (out / 'monitor.json').write_text(json.dumps(metadata, indent=2) + '\n')
    return 0 if proc is None or proc.returncode == 0 else proc.returncode


if __name__ == '__main__':
    raise SystemExit(main())
