"""
OpenTelemetry Instrumentation and Observability Module for Village Pond Planning System
Captures the Three Pillars of Observability:
1. Distributed Traces: Full end-to-end request tracing with fine-grained custom spans
2. Metrics: Prometheus-compatible counters, histograms, and gauges
3. Correlated Logs: Python standard logging enriched with active trace_id and span_id
"""

import time
import logging
import json
import threading
from collections import deque
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from opentelemetry import trace, metrics
from opentelemetry.trace import Status, StatusCode
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider, ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter, SpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

# Service metadata resource
SERVICE_NAME = "village-pond-planning-service"
SERVICE_VERSION = "1.0.0"
DEPLOYMENT_ENV = "evaluation"

resource = Resource.create({
    "service.name": SERVICE_NAME,
    "service.version": SERVICE_VERSION,
    "deployment.environment": DEPLOYMENT_ENV,
})

# ============================================================================
# 1. IN-MEMORY SPAN STORE FOR DASHBOARD & VISUALIZATION
# ============================================================================

class InMemorySpanStore(SpanExporter):
    """
    Custom OpenTelemetry SpanExporter that stores the most recent spans in memory.
    Enables rich interactive waterfall trace visualization in the Web UI.
    """
    def __init__(self, max_spans: int = 500):
        self.max_spans = max_spans
        self.spans = deque(maxlen=max_spans)
        self._lock = threading.Lock()

    def export(self, spans: List[ReadableSpan]):
        with self._lock:
            for s in spans:
                ctx = s.get_span_context()
                parent_ctx = s.parent
                
                # Format attributes safely
                safe_attrs = {}
                if s.attributes:
                    for k, v in s.attributes.items():
                        if isinstance(v, (int, float, str, bool)):
                            safe_attrs[k] = v
                        else:
                            safe_attrs[k] = str(v)

                # Format events
                events = []
                for ev in s.events:
                    events.append({
                        "name": ev.name,
                        "timestamp": ev.timestamp / 1e9,
                        "attributes": dict(ev.attributes or {})
                    })

                span_dict = {
                    "name": s.name,
                    "trace_id": format(ctx.trace_id, "032x"),
                    "span_id": format(ctx.span_id, "016x"),
                    "parent_span_id": format(parent_ctx.span_id, "016x") if parent_ctx and parent_ctx.is_valid else None,
                    "start_time_unix_nano": s.start_time,
                    "end_time_unix_nano": s.end_time,
                    "start_time_iso": datetime.fromtimestamp(s.start_time / 1e9, tz=timezone.utc).isoformat(),
                    "duration_ms": round((s.end_time - s.start_time) / 1e6, 3),
                    "status": s.status.status_code.name if s.status else "UNSET",
                    "status_description": s.status.description if s.status else "",
                    "attributes": safe_attrs,
                    "events": events,
                    "kind": str(s.kind).split(".")[-1],
                }
                self.spans.append(span_dict)
        return True

    def shutdown(self):
        pass

    def get_recent_spans(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.spans)

    def get_traces(self) -> List[Dict[str, Any]]:
        """Groups recorded spans into hierarchical traces with root and child spans."""
        with self._lock:
            all_spans = list(self.spans)

        trace_map: Dict[str, List[Dict[str, Any]]] = {}
        for s in all_spans:
            t_id = s["trace_id"]
            if t_id not in trace_map:
                trace_map[t_id] = []
            trace_map[t_id].append(s)

        traces = []
        for t_id, spans_in_trace in trace_map.items():
            spans_sorted = sorted(spans_in_trace, key=lambda x: x["start_time_unix_nano"])
            root = spans_sorted[0]
            for s in spans_sorted:
                if s["parent_span_id"] is None:
                    root = s
                    break

            min_start = min(s["start_time_unix_nano"] for s in spans_sorted)
            max_end = max(s["end_time_unix_nano"] for s in spans_sorted)
            total_duration_ms = round((max_end - min_start) / 1e6, 3)

            traces.append({
                "trace_id": t_id,
                "root_span_name": root["name"],
                "start_time_iso": root["start_time_iso"],
                "total_duration_ms": total_duration_ms,
                "span_count": len(spans_sorted),
                "has_error": any(s["status"] == "ERROR" for s in spans_sorted),
                "spans": spans_sorted,
            })

        traces.sort(key=lambda t: t["spans"][0]["start_time_unix_nano"], reverse=True)
        return traces

# Global in-memory span store
span_store = InMemorySpanStore(max_spans=500)

# ============================================================================
# 2. TRACER PROVIDER CONFIGURATION
# ============================================================================

tracer_provider = TracerProvider(resource=resource)
# Add console span exporter for terminal visibility
tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
# Add in-memory span store processor for web UI & viva demo
tracer_provider.add_span_processor(SimpleSpanProcessor(span_store))

trace.set_tracer_provider(tracer_provider)
tracer = trace.get_tracer(SERVICE_NAME, SERVICE_VERSION)

# ============================================================================
# 3. METRICS CONFIGURATION (PROMETHEUS & OPENTELEMETRY)
# ============================================================================

prometheus_reader = PrometheusMetricReader()
meter_provider = MeterProvider(resource=resource, metric_readers=[prometheus_reader])
metrics.set_meter_provider(meter_provider)
meter = metrics.get_meter(SERVICE_NAME, SERVICE_VERSION)

# Metric Instruments
http_requests_counter = meter.create_counter(
    name="http_requests_total",
    unit="1",
    description="Total count of incoming HTTP requests processed by endpoint and status code"
)

http_request_duration_histogram = meter.create_histogram(
    name="http_request_duration_seconds",
    unit="s",
    description="End-to-end HTTP request processing latency distribution"
)

dem_generation_histogram = meter.create_histogram(
    name="dem_generation_duration_seconds",
    unit="s",
    description="Execution time of continuous Digital Elevation Model TIN interpolation"
)

hydrology_execution_histogram = meter.create_histogram(
    name="hydrology_execution_duration_seconds",
    unit="s",
    description="Execution time of Priority-Flood depression filling and D8 flow accumulation routing"
)

catchment_delineation_histogram = meter.create_histogram(
    name="catchment_delineation_duration_seconds",
    unit="s",
    description="Execution time of reverse Breadth-First Search upstream catchment delineation"
)

catchment_area_histogram = meter.create_histogram(
    name="catchment_area_hectares",
    unit="ha",
    description="Calculated area of delineated contributing upstream hydrological catchments"
)

annual_runoff_histogram = meter.create_histogram(
    name="annual_runoff_m3",
    unit="m3",
    description="Estimated annual harvestable runoff water volume computed via Rational equation"
)

candidate_ponds_histogram = meter.create_histogram(
    name="candidate_ponds_count",
    unit="1",
    description="Number of viable pond candidate locations identified per terrain analysis"
)

active_cached_models_counter = meter.create_up_down_counter(
    name="active_cached_models",
    unit="1",
    description="Count of currently active pre-computed terrain models held in memory cache"
)

analysis_errors_counter = meter.create_counter(
    name="analysis_errors_total",
    unit="1",
    description="Count of terrain analysis failures, parsing errors, or validation exceptions"
)

# ============================================================================
# 4. LOGGING WITH TRACE CORRELATION
# ============================================================================

class TraceCorrelatingFormatter(logging.Formatter):
    """
    Custom log formatter that automatically injects the current active OpenTelemetry
    trace_id and span_id into every log record.
    """
    def format(self, record):
        span = trace.get_current_span()
        span_ctx = span.get_span_context() if span else None
        if span_ctx and span_ctx.is_valid:
            record.trace_id = format(span_ctx.trace_id, "032x")
            record.span_id = format(span_ctx.span_id, "016x")
        else:
            record.trace_id = "0" * 32
            record.span_id = "0" * 16
        return super().format(record)


class InMemoryLogHandler(logging.Handler):
    """
    Captures recent structured log records in memory for the interactive UI dashboard.
    """
    def __init__(self, max_logs: int = 400):
        super().__init__()
        self.logs = deque(maxlen=max_logs)
        self._lock = threading.Lock()

    def emit(self, record):
        try:
            span = trace.get_current_span()
            span_ctx = span.get_span_context() if span else None
            trace_id = format(span_ctx.trace_id, "032x") if span_ctx and span_ctx.is_valid else None
            span_id = format(span_ctx.span_id, "016x") if span_ctx and span_ctx.is_valid else None

            log_entry = {
                "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "trace_id": trace_id,
                "span_id": span_id,
            }
            with self._lock:
                self.logs.append(log_entry)
        except Exception:
            self.handleError(record)

    def get_recent_logs(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.logs)


# Initialize memory log handler
memory_log_handler = InMemoryLogHandler(max_logs=400)
memory_log_handler.setFormatter(
    TraceCorrelatingFormatter(
        fmt="%(asctime)s [%(levelname)s] [trace_id=%(trace_id)s span_id=%(span_id)s] [%(name)s]: %(message)s"
    )
)

# Setup application logger
app_logger = logging.getLogger("village_pond.observability")
app_logger.setLevel(logging.INFO)
app_logger.addHandler(memory_log_handler)

# Add to root logger so all subsystem logs get trace-correlated
console_handler = logging.StreamHandler()
console_handler.setFormatter(
    TraceCorrelatingFormatter(
        fmt="%(asctime)s [%(levelname)s] [trace_id=%(trace_id)s span_id=%(span_id)s] [%(name)s]: %(message)s"
    )
)
logging.getLogger().addHandler(console_handler)
logging.getLogger().addHandler(memory_log_handler)
logging.getLogger().setLevel(logging.INFO)

# ============================================================================
# 5. METRIC AGGREGATION & SUMMARY HELPER
# ============================================================================

_METRIC_STATS: Dict[str, Any] = {
    "total_requests": 0,
    "total_contour_analyses": 0,
    "total_land_area_analyses": 0,
    "total_errors": 0,
    "latencies": [],
    "dem_durations": [],
    "hydro_durations": [],
    "catchment_areas_ha": [],
    "annual_runoff_m3": [],
}
_stats_lock = threading.Lock()

def record_request_metric(endpoint: str, status_code: int, duration_sec: float):
    http_requests_counter.add(1, {"endpoint": endpoint, "status_code": str(status_code), "method": "HTTP"})
    http_request_duration_histogram.record(duration_sec, {"endpoint": endpoint})
    with _stats_lock:
        _METRIC_STATS["total_requests"] += 1
        _METRIC_STATS["latencies"].append(duration_sec)
        if len(_METRIC_STATS["latencies"]) > 200:
            _METRIC_STATS["latencies"].pop(0)

def record_dem_metric(duration_sec: float, grid_cells: int):
    dem_generation_histogram.record(duration_sec, {"grid_cells": str(grid_cells)})
    with _stats_lock:
        _METRIC_STATS["dem_durations"].append(duration_sec)

def record_hydro_metric(duration_sec: float):
    hydrology_execution_histogram.record(duration_sec)
    with _stats_lock:
        _METRIC_STATS["hydro_durations"].append(duration_sec)

def record_analysis_results(catchment_ha: float, runoff_m3: float, num_candidates: int, is_contour: bool = True):
    catchment_area_histogram.record(catchment_ha)
    annual_runoff_histogram.record(runoff_m3)
    candidate_ponds_histogram.record(num_candidates)
    with _stats_lock:
        if is_contour:
            _METRIC_STATS["total_contour_analyses"] += 1
        else:
            _METRIC_STATS["total_land_area_analyses"] += 1
        _METRIC_STATS["catchment_areas_ha"].append(catchment_ha)
        _METRIC_STATS["annual_runoff_m3"].append(runoff_m3)

def record_error_metric(error_type: str):
    analysis_errors_counter.add(1, {"error_type": error_type})
    with _stats_lock:
        _METRIC_STATS["total_errors"] += 1

def get_telemetry_summary() -> Dict[str, Any]:
    with _stats_lock:
        avg_lat = round(sum(_METRIC_STATS["latencies"]) / max(1, len(_METRIC_STATS["latencies"])), 4)
        avg_dem = round(sum(_METRIC_STATS["dem_durations"]) / max(1, len(_METRIC_STATS["dem_durations"])), 4)
        avg_hydro = round(sum(_METRIC_STATS["hydro_durations"]) / max(1, len(_METRIC_STATS["hydro_durations"])), 4)
        total_catchment = round(sum(_METRIC_STATS["catchment_areas_ha"]), 2)
        total_runoff = round(sum(_METRIC_STATS["annual_runoff_m3"]), 1)

        return {
            "service_name": SERVICE_NAME,
            "service_version": SERVICE_VERSION,
            "environment": DEPLOYMENT_ENV,
            "total_requests": _METRIC_STATS["total_requests"],
            "total_contour_analyses": _METRIC_STATS["total_contour_analyses"],
            "total_land_area_analyses": _METRIC_STATS["total_land_area_analyses"],
            "total_errors": _METRIC_STATS["total_errors"],
            "avg_latency_seconds": avg_lat,
            "avg_dem_duration_seconds": avg_dem,
            "avg_hydrology_duration_seconds": avg_hydro,
            "cumulative_catchment_hectares": total_catchment,
            "cumulative_runoff_harvested_m3": total_runoff,
            "total_recorded_spans": len(span_store.spans),
            "total_recorded_traces": len(span_store.get_traces()),
            "total_recorded_logs": len(memory_log_handler.logs),
        }

