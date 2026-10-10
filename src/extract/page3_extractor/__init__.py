"""page3_extractor — production extractor for Tunisian dam-bulletin Page 3.

Layer A of the three-layer delivery: reusable code only. It never reads the
producer's run outputs, never hard-codes the producer's corpus or output
directory, and never imports anything from a notebook.

Public surface::

    from page3_extractor import Page3RunConfig, run_page3_pipeline
    result = run_page3_pipeline(Page3RunConfig(input_dir=..., output_root=...))
"""

from .version import (
    EXTRACTOR_VERSION,
    ROUTING_VERSION,
    SEMANTICS_VERSION,
    SCHEMA_CONTRACT_VERSION,
)
from .config import Page3RunConfig, load_config, resolve_config
from .api import (
    run_page3_pipeline,
    validate_run,
    review_run,
    generate_findings,
    RunResult,
)

__version__ = EXTRACTOR_VERSION

__all__ = [
    "EXTRACTOR_VERSION",
    "ROUTING_VERSION",
    "SEMANTICS_VERSION",
    "SCHEMA_CONTRACT_VERSION",
    "Page3RunConfig",
    "load_config",
    "resolve_config",
    "run_page3_pipeline",
    "validate_run",
    "review_run",
    "generate_findings",
    "RunResult",
    "__version__",
]
