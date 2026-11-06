from __future__ import annotations

from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def configure_phoenix_tracer(endpoint: str | None) -> Any | None:
    if not endpoint:
        return None
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as error:
        raise RuntimeError(
            "Phoenix tracing is configured but optional tracing packages are missing. "
            "Install requirements-tracing.txt."
        ) from error

    provider = TracerProvider()
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
    )
    trace.set_tracer_provider(provider)
    return trace.get_tracer("trialmatch")
