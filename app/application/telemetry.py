"""Content-free optional runtime telemetry port; no monitoring library dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RuntimeResources:
    process_rss_bytes: int | None
    process_peak_rss_bytes: int | None
    cgroup_memory_current_bytes: int | None
    cgroup_memory_limit_bytes: int | None
    cgroup_cpu_limit_cores: float | None
    cgroup_pids_current: int | None
    cgroup_pids_limit: int | None


@dataclass(frozen=True, slots=True)
class TelemetrySnapshot:
    generated_at: datetime
    process_started_at: datetime
    process_uptime_seconds: float
    synthetic: bool
    ready: bool
    active_runs: int
    max_concurrent_runs: int
    resources: RuntimeResources
    http_requests: int
    http_server_errors: int
    http_inflight: int
    traces_enabled: bool
    trace_sampling_ratio: float
    export_successes: int
    export_failures: int
    last_export_at: datetime | None
    last_export_success: bool | None


class TelemetryPort(Protocol):
    async def snapshot(self) -> TelemetrySnapshot: ...
    async def prometheus(self) -> bytes: ...
