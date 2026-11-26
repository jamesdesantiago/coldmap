"""coldmap: find clusters of unsolved homicides in public U.S. homicide data.

A flag from this toolkit is a pattern worth asking about, never evidence that
cases are linked. See ETHICS.md before sharing any result.
"""

from .load import load_shr, load_clearance, WEAPON_GROUPS
from .issues import apply_fixes, ISSUES
from .detect import map_algorithm, sliding_window, Flag

__all__ = [
    "load_shr", "load_clearance", "WEAPON_GROUPS",
    "apply_fixes", "ISSUES",
    "map_algorithm", "sliding_window", "Flag",
]
__version__ = "0.1.0"
