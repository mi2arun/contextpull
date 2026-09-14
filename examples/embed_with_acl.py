"""Embedding ContextPull in your own product, with access control.

ContextPull's store knows nothing about users. Your product decides which
document paths a user may see and passes them as the `in=` filter on search
and grep; read and neighbours are checked against the same rule. The store
stays a single read-only file, and the core never has to learn your permission
model.

    export CONTEXTPULL_STORE=/data/store.sqlite
    python examples/embed_with_acl.py alice "refund window"
"""

from __future__ import annotations

import fnmatch
import os
import sys

from contextpull import Ops, Store
from contextpull.ops import OpsError

# Your permission model. Here: glob patterns per user; in a product this comes
# from your directory, groups, or a per-document ACL table you maintain.
ACL = {
    "alice": ["policies/*", "guides/*", "notes.txt"],
    "bob": ["guides/*"],
    "auditor": ["*"],
}


class AccessControlledOps:
    """Wraps Ops so every operation is scoped to what `user` may see."""

    def __init__(self, ops: Ops, allowed_paths: list[str]):
        self.ops = ops
        self.allowed = allowed_paths

    def _permitted(self, section_id: str) -> bool:
        doc = section_id.rsplit("#", 1)[0]
        return any(fnmatch.fnmatch(doc, pat) or doc.startswith(pat.rstrip("/*") + "/") for pat in self.allowed)

    def index(self, prefix: str | None = None) -> str:
        # Filter the table of contents to permitted documents so the model never
        # learns that other documents exist.
        lines = self.ops.index(prefix).splitlines()
        head = [l for l in lines[:3]]
        body = [l for l in lines[3:] if l.strip() and self._permitted(l.split()[0] + "#0")]
        return "\n".join(head + body)

    def search(self, query: str, limit: int = 10):
        return self.ops.search(query, in_=self.allowed, limit=limit)

    def grep(self, pattern: str, limit: int = 20):
        return self.ops.grep(pattern, in_=self.allowed, limit=limit)

    def read(self, section_id: str, context: int = 0):
        if not self._permitted(section_id):
            raise OpsError(f"no section '{section_id}'", "search for it first")  # indistinguishable from absent
        res = self.ops.read(section_id, context)
        res.context = [c for c in res.context if self._permitted(c.id)]
        return res

    def neighbours(self, section_id: str, before: int = 1, after: int = 1):
        if not self._permitted(section_id):
            raise OpsError(f"no section '{section_id}'", "search for it first")
        res = self.ops.neighbours(section_id, before, after)
        res.sections = [s for s in res.sections if self._permitted(s.id)]
        return res


def main(user: str, query: str) -> None:
    allowed = ACL.get(user)
    if allowed is None:
        sys.exit(f"unknown user {user}")
    with Store.open(os.environ.get("CONTEXTPULL_STORE", ".contextpull/store.sqlite")) as store:
        scoped = AccessControlledOps(Ops(store), allowed)
        print(f"--- index as seen by {user} ---")
        print(scoped.index())
        print(f"\n--- search '{query}' ---")
        for h in scoped.search(query, limit=5).hits:
            print(f"  {h.id:<36} {h.heading_path}")
        # Hand `scoped` to your model loop instead of `Ops`: same five operations, scoped.


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "bob", " ".join(sys.argv[2:]) or "refund window")
