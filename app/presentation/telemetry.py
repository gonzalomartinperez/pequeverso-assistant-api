"""Optional independent private telemetry contract; the legacy summary is unchanged."""

from dataclasses import asdict
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from app.application.telemetry import TelemetrySnapshot


class _Out(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class ReadinessOut(_Out):
    status: Literal['ready', 'not_ready']
    checked_at: datetime
    measurement: Literal['point_in_time'] = 'point_in_time'


class ProviderObservationOut(_Out):
    status: Literal['unknown'] = 'unknown'
    reason: Literal['not_probed'] = 'not_probed'


class ResourcesOut(_Out):
    process_rss_bytes: int | None = Field(ge=0)
    process_peak_rss_bytes: int | None = Field(ge=0)
    cgroup_memory_current_bytes: int | None = Field(ge=0)
    cgroup_memory_limit_bytes: int | None = Field(ge=0)
    cgroup_cpu_limit_cores: float | None = Field(ge=0)
    cgroup_pids_current: int | None = Field(ge=0)
    cgroup_pids_limit: int | None = Field(ge=0)
    cgroup_scope: Literal['enclosing_cgroup_may_be_shared'] = 'enclosing_cgroup_may_be_shared'


class HttpTelemetryOut(_Out):
    requests: int = Field(ge=0)
    server_errors: int = Field(ge=0)
    inflight: int = Field(ge=0)
    window: Literal['since_process_start'] = 'since_process_start'
    error_scope: Literal['http_5xx_only_not_sse_run_outcomes'] = 'http_5xx_only_not_sse_run_outcomes'


class TracesOut(_Out):
    enabled: bool
    sampling_ratio: float = Field(ge=0, le=1)
    export_successes: int = Field(ge=0)
    export_failures: int = Field(ge=0)
    last_export_at: datetime | None
    last_export_success: bool | None
    durable: Literal[False] = False


class OpsTelemetryOut(_Out):
    schema_version: Literal['1'] = '1'
    generated_at: datetime
    process_started_at: datetime
    process_uptime_seconds: float = Field(
        ge=0, description='Current process lifetime, not availability percentage.'
    )
    synthetic: bool = Field(
        description='Fixture provider configuration; HTTP/resource measurements remain real.'
    )
    readiness: ReadinessOut
    provider_observation: ProviderObservationOut
    active_runs: int = Field(ge=0)
    max_concurrent_runs: int = Field(ge=1)
    resources: ResourcesOut
    http: HttpTelemetryOut
    traces: TracesOut

    @classmethod
    def of(cls, state: TelemetrySnapshot) -> Self:
        return cls.model_validate(
            {
                'generated_at': state.generated_at,
                'process_started_at': state.process_started_at,
                'process_uptime_seconds': state.process_uptime_seconds,
                'synthetic': state.synthetic,
                'readiness': {
                    'status': 'ready' if state.ready else 'not_ready',
                    'checked_at': state.generated_at,
                },
                'provider_observation': {},
                'active_runs': state.active_runs,
                'max_concurrent_runs': state.max_concurrent_runs,
                'resources': asdict(state.resources),
                'http': {
                    'requests': state.http_requests,
                    'server_errors': state.http_server_errors,
                    'inflight': state.http_inflight,
                },
                'traces': {
                    'enabled': state.traces_enabled,
                    'sampling_ratio': state.trace_sampling_ratio,
                    'export_successes': state.export_successes,
                    'export_failures': state.export_failures,
                    'last_export_at': state.last_export_at,
                    'last_export_success': state.last_export_success,
                },
            }
        )
