"""Pin protected files to the owner-authorized revision and retain prior evidence."""

import hashlib
import json
from pathlib import Path


def test_protected_hashes_match_only_authorized_eval_revision():
    root = Path(__file__).resolve().parents[1]
    proof = json.loads((root / "report/wo08-protected-files.json").read_text())
    current = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in proof["sha256"]
    }
    assert current == proof["sha256"]
    changed = {name for name, digest in current.items() if digest != proof["previous_sha256"][name]}
    assert changed == set(proof["authorized_changes"]) == {"factory/evals/runner.py"}
    for name in ("factory/evals/config.py", "factory/evals/decay.py", "factory/evals/deflated.py"):
        assert current[name] == proof["previous_sha256"][name]
    assert proof["revision"] == "2026-11-14-live-eval-publication-v1"
    assert proof["previous_revision"]["revision"] == "2026-11-14-wo12-events-v1"
    assert proof["previous_revision"]["sha256"] == proof["previous_sha256"]
