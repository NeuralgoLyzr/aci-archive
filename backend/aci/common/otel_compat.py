"""Compatibility shims for the OpenTelemetry env the K8s OTel operator injects.

Import and run these before importing ``logfire`` so the side effect lands first.
"""

import os


def neutralize_incompatible_otel_sampler_env() -> None:
    """Stop logfire from crashing on the operator-injected ``OTEL_TRACES_SAMPLER_ARG``.

    The AWS EKS OpenTelemetry operator's auto-instrumentation injects
    ``OTEL_TRACES_SAMPLER_ARG`` (e.g. ``endpoint=http://cloudwatch-agent.amazon-cloudwatch:2000``
    for the X-Ray sampler). logfire reads ``OTEL_TRACES_SAMPLER_ARG`` as its float
    ``trace_sample_rate`` and raises ``ValueError`` at import when the value isn't a
    number, taking down the whole process before its ``import logfire`` guard can help.

    logfire consults ``LOGFIRE_TRACE_SAMPLE_RATE`` before ``OTEL_TRACES_SAMPLER_ARG``,
    so set it to logfire's default sample rate when the injected value isn't a usable
    float. This keeps logfire importable and functional without disturbing
    ``OTEL_TRACES_SAMPLER_ARG`` for genuine OpenTelemetry consumers.
    """
    sampler_arg = os.environ.get("OTEL_TRACES_SAMPLER_ARG")
    if not sampler_arg or "LOGFIRE_TRACE_SAMPLE_RATE" in os.environ:
        return
    try:
        float(sampler_arg)
    except ValueError:
        # logfire's own default trace_sample_rate; makes the fallback explicit.
        os.environ["LOGFIRE_TRACE_SAMPLE_RATE"] = "1.0"
