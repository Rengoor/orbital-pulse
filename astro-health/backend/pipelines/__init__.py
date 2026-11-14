"""Auto-discovers pipeline subpackages exposing run(readings, context) -> Proposal. No central registry file, so adding a pipeline never edits a shared file.

Owner: person A
"""

import importlib
import logging
import os
import pkgutil
import types
from pathlib import Path

logger = logging.getLogger(__name__)


def discover_pipelines() -> list[types.ModuleType]:
    """
    Returns all pipeline modules exposing run(readings, context) -> Proposal.

    Searches backend/pipelines/ for subpackages that contain a pipeline.py
    with a callable 'run'. Skips d_llm when LLM_ENABLED != '1'. Logs a
    warning (not an error) on ImportError and continues.

    Result is deterministic for a given filesystem state and LLM_ENABLED value.
    """
    llm_enabled = os.environ.get("LLM_ENABLED", "0") == "1"
    package_path = [str(Path(__file__).parent)]
    discovered: list[types.ModuleType] = []

    for module_info in pkgutil.iter_modules(package_path):
        if not module_info.ispkg:
            continue

        name = module_info.name

        if name == "d_llm" and not llm_enabled:
            continue

        try:
            mod = importlib.import_module(f"backend.pipelines.{name}.pipeline")
        except ImportError as exc:
            logger.warning("Could not import backend.pipelines.%s.pipeline: %s", name, exc)
            continue

        if callable(getattr(mod, "run", None)):
            discovered.append(mod)

    return sorted(discovered, key=lambda m: m.__name__)
