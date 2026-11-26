"""coldmap: a framework for finding clusters of unsolved homicides in public data.

Extension points (all plugins, all discoverable through Python entry points):

    coldmap.sources    turn a file or API into a Dataset          SOURCES
    coldmap.fixes      correct known data problems                FIXES
    coldmap.detectors  find suspicious place/method/periods       DETECTORS
    coldmap.enrichers  add information to findings                ENRICHERS

Quick start:

    import coldmap
    data = coldmap.load("SHR76_25a.csv", clearance_path="UCR65_25.csv")
    findings = coldmap.run(data, coldmap.Query(state="California"))     # default ensemble
    findings = coldmap.run(data, coldmap.Query(state="Indiana"), detectors=["scan"],
                           params={"scan": {"levels": ("agency",)}})

A finding is a pattern worth review, never evidence that cases are linked.
See ETHICS.md before sharing anything.
"""

from .core import Dataset, Finding, Query, Registry, findings_frame
from .detectors import DETECTORS, Detector
from .enrichers import ENRICHERS, Enricher
from .ensemble import DEFAULT_DETECTORS, Ensemble, Matcher, run
from .fixes import FIXES, Fix
from .presets import PRESETS, Preset
from .sources import SOURCES, Source, load

__all__ = [
    "Dataset", "Finding", "Query", "Registry", "findings_frame",
    "DETECTORS", "Detector", "ENRICHERS", "Enricher", "FIXES", "Fix", "SOURCES", "Source",
    "Ensemble", "Matcher", "DEFAULT_DETECTORS", "PRESETS", "Preset", "load", "run", "explain",
]
__version__ = "0.3.0"

from .explain import explain  # noqa: E402
