"""Compile the contract into validators, documentation and agent data context."""

import argparse
import hashlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).with_name("contract.yaml")


def read_contract():
    return yaml.safe_load(SOURCE.read_text())


def fingerprint(spec):
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()


def artifacts(spec):
    from factory.data_contract.runtime import OPERATIONS

    for kind in spec["datasets"].values():
        for rule in kind["invariants"]:
            if rule["op"] not in OPERATIONS:
                raise ValueError(f"Unknown validation operation: {rule['op']}")
    digest = fingerprint(spec)
    lines = [
        f"# {spec['title']}",
        "",
        "<!-- GENERATED from factory/data_contract/contract.yaml; do not edit. -->",
        f"Schema version: {spec['schema_version']}. Source SHA-256: `{digest}`.",
        "",
        "## Meaning and use",
        "",
    ]
    lines += ["- " + line for line in spec["semantics"]]
    lines += [
        "",
        "## Calendar and activity settings",
        "",
        "```json",
        json.dumps({"calendar": spec["calendar"], "activity": spec["activity"]}, indent=2),
        "```",
    ]
    for name, entity in spec["ontology"].items():
        lines += [
            "",
            f"## {name}",
            "",
            entity["description"],
            "",
            "| Field | dtype | Units | Constraints | Meaning |",
            "|---|---|---|---|---|",
        ]
        for group in ("fields", "derived_fields"):
            for field, definition in entity.get(group, {}).items():
                constraints = {
                    k: v
                    for k, v in definition.items()
                    if k not in ("dtype", "units", "description")
                }
                lines.append(
                    f"| `{field}` | `{definition['dtype']}` | {definition['units']} | "
                    f"{json.dumps(constraints)} | {definition['description']} |"
                )
    for name, kind in spec["datasets"].items():
        lines += [
            "",
            f"## Dataset kind: {name}",
            "",
            f"Extra columns allowed: {kind['extra_columns']}.",
        ]
        if "fields" in kind:
            for field, definition in kind["fields"].items():
                lines += [
                    f"- `{field}`: `{definition['dtype']}`, {definition['units']}. "
                    f"{definition['description']}"
                ]
            lines += [f"Extension dtypes: {', '.join(kind['extension_dtypes'])}."]
        lines += ["", "Invariants:", ""]
        lines += [f"- `{name}.{r['id']}`: {r['description']}" for r in kind["invariants"]]
    lines += ["", "## Record and strategy invariants", ""]
    lines += [f"- `{r['id']}`: {r['description']}" for r in spec["record_invariants"]]
    doc = "\n".join(lines) + "\n"
    code = (
        "# GENERATED from contract.yaml; do not edit.\n"
        "import json\nfrom factory.data_contract.runtime import validate\n\n"
        f"SOURCE_SHA256 = {digest!r}\nSPEC = json.loads({json.dumps(spec, sort_keys=True)!r})\n\n"
    )
    for kind in spec["datasets"]:
        code += (
            f"def validate_{kind}(frame, *, dataset, **context):\n"
            f"    return validate(SPEC, {kind!r}, frame, dataset=dataset, **context)\n\n"
        )
    return {
        "docs/DATA.md": doc,
        "factory/data_contract/agent_data.md": doc,
        "factory/data_contract/generated.py": code.rstrip() + "\n",
    }


def generate(root=ROOT, spec=None):
    for name, content in artifacts(read_contract() if spec is None else spec).items():
        path = Path(root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def check(root=ROOT, spec=None):
    for name, content in artifacts(read_contract() if spec is None else spec).items():
        path = Path(root) / name
        if not path.exists() or path.read_text() != content:
            raise ValueError(
                f"Generated artifact is stale: {name}; run python -m factory.data_contract.generate"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    check() if args.check else generate()
