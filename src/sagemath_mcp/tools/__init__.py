"""Tool modules, imported for their registration side effects.

Importing this package is what puts the 37 tools and 3 resources on the shared
FastMCP object. ``server`` imports it for exactly that reason, so the names must
stay listed here -- a module missing from this list registers nothing and its
tools simply vanish from the catalogue.
"""

from . import (  # noqa: F401
    algebra,
    calculus,
    core,
    discrete,
    plotting,
    session,
    stats,
)
