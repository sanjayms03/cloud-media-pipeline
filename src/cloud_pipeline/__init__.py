"""cloud_pipeline — media job ingestion pipeline.

Deliberately flawed benchmark package. See ../../benchmark/expected-findings.yaml.
"""

__version__ = "0.3.0"

# CMP-CODE-001: a mutable module-level registry used as ad-hoc global state.
# Because Lambda reuses execution environments, this dictionary persists across
# invocations and silently leaks data between unrelated requests. It is also
# unbounded, so a long-lived container grows until it is recycled.
PROCESSED_JOBS: dict = {}

