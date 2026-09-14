"""ContextPull — pull, don't push.

Core library. Zero runtime dependencies. The store file is the contract
(docs/store-format.md); this package is the reference implementation.
"""

from __future__ import annotations

from .store import Store, StoreError, SCHEMA_VERSION
from .ops import Ops, Hit, Section, Match

__version__ = "0.2.0"
__all__ = ["Store", "StoreError", "SCHEMA_VERSION", "Ops", "Hit", "Section", "Match", "__version__"]
