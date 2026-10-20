# -*- coding: utf-8 -*-
"""Mutation check: break one rule at a time and confirm the test suite goes RED.

    python skills/am-markup-intake/tests/mutate.py

Row "none" is the negative control and must stay GREEN. Exit 0 only when the
control is GREEN, every mutation is RED, and each run executed assertions.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_markup_intake as T  # noqa: E402

C, P = T.C, T.P


def _no_dedupe(records):
    return [{"members": [r]} for r in records]


def _normalized_text(orig):
    def run(records):
        items, orphans = orig(records)
        for it in items:
            it["text"] = C.norm_text(it["text"])
        return items, orphans
    return run


def _replies_as_items(orig):
    def run(records):
        return orig([dict(r, inReplyTo="") for r in records])
    return run


MUTATIONS = [
    ("none", None),
    ("dedupe-off", lambda: setattr(C, "dedupe", _no_dedupe)),
    ("conflict-off", lambda: setattr(C, "conflict_reason", lambda a, b: "")),
    ("region-overlap-off", lambda: setattr(C, "overlap", lambda a, b: 0.0)),
    ("text-normalized-not-verbatim", lambda: setattr(C, "build_items", _normalized_text(C.build_items))),
    ("replies-become-items", lambda: setattr(C, "build_items", _replies_as_items(C.build_items))),
    ("popup-not-skipped", lambda: setattr(P, "SKIP_SUBTYPES", ("Widget", "Link"))),
    ("check-in-model-off", lambda: setattr(C, "model_refs", lambda item: [])),
]


def main():
    ok = True
    print("%-30s %-6s %s" % ("mutation", "result", "detail"))
    for name, apply in MUTATIONS:
        saved_c, saved_p = dict(vars(C)), dict(vars(P))
        try:
            if apply:
                apply()
            n, failed, checks = T.run_all(verbose=False)
        finally:
            vars(C).update(saved_c)
            vars(P).update(saved_p)
        red = bool(failed)
        expect_red = apply is not None
        good = (red == expect_red) and checks > 0
        ok = ok and good
        print("%-30s %-6s %d/%d tests failed, %d assertion(s)%s" % (
            name, "RED" if red else "GREEN", len(failed), n, checks,
            "" if good else "   <-- UNEXPECTED"))
    print("MUTATION CHECK: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
