#!/usr/bin/env python3
"""Save-then-read census of this repo's test suites (C-49.contract.sdk-suites, U49.A2; G11, G12, G47).

Derives the save vocabulary from the product code (never hand-listed), scans every test for the units that save
(directly, by fixture or by helper) and whether a read follows, and checks that every unit carries exactly one
authored disposition. A deferral names where and its owner step and carries the prepared explicit wait
(``tests/public_wait.py``). The ENGINE and COMMON regions are byte-identical in smart-memory-client and
smart-memory-mcp, which share no package.

    python scripts/save_then_read_census.py            # check, exit 1 on a problem or a stale fixture
    python scripts/save_then_read_census.py --write    # regenerate tests/data/save_then_read_census.json
    python scripts/save_then_read_census.py --table    # one line per unit

Stdlib only; it imports none of the code it scans.
"""

import ast
import hashlib
import json
import re
import sys
from pathlib import Path


# --- ENGINE BEGIN ---

SKIP_DIRS = {
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    "dist",
    "build",
    "artifacts",
}
MEMORY_RECEIVER = re.compile(
    r"(?i)(backend|^be$|mem|^sm$|smart|lite|storage|core|client|secure|wrapper|^st$|svc|service)"
)
READ_NAME = re.compile(
    r"^(get|search|recall|list|query|explain|find|read|traverse|stats)(_\w+)?$"
)
WAIT_NAME = re.compile(r"\b(sleep|poll|wait_for|await_\w+|wait)\s*\(")


def _name(node):
    """Dotted name of a Name/Attribute chain, or the unparsed text for anything else (a call, a subscript)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_name(node.value)}.{node.attr}"
    return ast.unparse(node)[:40]


def _fixture_kind(fn):
    """None for a plain function, "fixture" for ``@pytest.fixture``, "autouse" for ``@pytest.fixture(autouse=True)``."""
    for d in fn.decorator_list:
        target = d.func if isinstance(d, ast.Call) else d
        if _name(target).split(".")[-1] == "fixture":
            if isinstance(d, ast.Call):
                for kw in d.keywords:
                    if (
                        kw.arg == "autouse"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value is True
                    ):
                        return "autouse"
            return "fixture"
    return None


def _walk_functions(tree):
    """Yield (qualified_name, node): ``Class.method`` for methods, the bare name otherwise."""

    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                yield from visit(child, f"{prefix}{child.name}.")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield f"{prefix}{child.name}", child
                yield from visit(child, f"{prefix}{child.name}.<locals>.")
            else:
                yield from visit(child, prefix)

    yield from visit(tree, "")


def _own_nodes(fn):
    """Nodes of ``fn`` excluding nested function bodies (those are their own units)."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _memory_like(receiver):
    return bool(MEMORY_RECEIVER.search(receiver.split(".")[-1]))


def call_sites(fn, vocab):
    """Every save and read call in ``fn``: sorted (line, kind, name, receiver, memory_like)."""
    out = set()
    for node in _own_nodes(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr, recv = node.func.attr, _name(node.func.value)
            if attr in vocab["save_methods"]:
                out.add((node.lineno, "save", attr, recv, _memory_like(recv)))
            elif READ_NAME.match(attr):
                out.add((node.lineno, "read", attr, recv, _memory_like(recv)))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in vocab["save_tools"]:
                out.add((node.lineno, "save", node.value, "<tool-name>", True))
            elif node.value in vocab["read_tools"]:
                out.add((node.lineno, "read", node.value, "<tool-name>", True))
    return sorted(out)


def _test_files(repo, tests_dir):
    for p in sorted((Path(repo) / tests_dir).rglob("*.py")):
        if not (set(p.relative_to(repo).parts) & SKIP_DIRS):
            yield p


def scan(repo, vocab, *, tests_dir="tests", ignore=(), read_source=None):
    """The census of ``repo``: every save site, and every unit that saves directly or by fixture/helper.

    A unit is a function with a memory-like save site, or one that consumes a fixture or helper that has one
    (a fixture by parameter name, an autouse fixture by sharing its class, a helper by calling it).
    ``reads_after_save`` is True when any read call follows the save point of the unit (conservative: the read
    receiver need not look like memory, so a read through a store handle still flags it). ``ignore`` lists
    repo-relative files skipped by name. ``read_source(path) -> str`` lets a test feed synthetic text.
    """
    repo = Path(repo)
    read_source = read_source or (lambda p: Path(p).read_text())
    sites, funcs, parse_errors = [], {}, []
    for path in _test_files(repo, tests_dir):
        rel = path.relative_to(repo).as_posix()
        if rel in ignore:
            continue
        try:
            tree = ast.parse(read_source(path))
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            parse_errors.append({"file": rel, "error": f"{type(exc).__name__}: {exc}"})
            continue
        for qual, fn in _walk_functions(tree):
            calls = call_sites(fn, vocab)
            call_lines = {}
            for n in _own_nodes(fn):
                if isinstance(n, ast.Call):
                    call_lines[_name(n.func).split(".")[-1]] = min(
                        n.lineno, call_lines.get(_name(n.func).split(".")[-1], n.lineno)
                    )
            funcs[(rel, qual)] = {
                "line": fn.lineno,
                "bare": fn.name,
                "fixture": _fixture_kind(fn),
                "params": [a.arg for a in fn.args.args + fn.args.kwonlyargs],
                "calls": calls,
                "call_lines": call_lines,
            }
            for line, kind, name, recv, mem in calls:
                if kind == "save":
                    sites.append(
                        {
                            "file": rel,
                            "line": line,
                            "function": qual,
                            "call": name,
                            "receiver": recv,
                            "memory_like": mem,
                        }
                    )
    units = {}

    def add_unit(rel, qual, info, via, save_line, saves):
        key = f"{rel}::{qual}"
        row = units.setdefault(
            key,
            {
                "key": key,
                "file": rel,
                "line": info["line"],
                "function": qual,
                "via": set(),
                "saves": set(),
                "reads": set(),
                "save_point": save_line,
            },
        )
        row["via"].add(via)
        row["saves"] |= {(s[0], s[2]) for s in saves}
        row["save_point"] = min(row["save_point"], save_line)
        row["reads"] |= {(r[0], r[2]) for r in info["calls"] if r[1] == "read"}

    for (rel, qual), info in sorted(funcs.items()):
        saves = [c for c in info["calls"] if c[1] == "save" and c[4]]
        if not saves:
            continue
        add_unit(rel, qual, info, "direct", min(s[0] for s in saves), saves)
        if not (info["fixture"] or not info["bare"].startswith("test")):
            continue
        cls = qual.rsplit(".", 1)[0] if "." in qual else None
        for (crel, cqual), cinfo in sorted(funcs.items()):
            if (crel, cqual) == (rel, qual):
                continue
            ccls = cqual.rsplit(".", 1)[0] if "." in cqual else None
            if info["fixture"] == "autouse":
                hit, point = (
                    crel == rel and ccls == cls and cinfo["bare"].startswith("test"),
                    cinfo["line"],
                )
            elif info["fixture"]:
                hit, point = (
                    crel.rsplit("/", 1)[0] == rel.rsplit("/", 1)[0]
                    and info["bare"] in cinfo["params"],
                    cinfo["line"],
                )
            else:
                hit, point = (
                    crel == rel and info["bare"] in cinfo["call_lines"],
                    cinfo["call_lines"].get(info["bare"], cinfo["line"]),
                )
            if hit:
                kind = {"autouse": "autouse fixture", "fixture": "fixture"}.get(
                    info["fixture"], "helper"
                )
                add_unit(crel, cqual, cinfo, f"{kind} {rel}::{qual}", point, [])
    rows = []
    for row in units.values():
        row["reads_after_save"] = any(r[0] >= row["save_point"] for r in row["reads"])
        row["via"] = sorted(row["via"])
        row["saves"] = [list(x) for x in sorted(row["saves"])]
        row["reads"] = [list(x) for x in sorted(row["reads"])]
        del row["save_point"]
        rows.append(row)
    return {
        "sites": sorted(sites, key=lambda s: (s["file"], s["line"], s["call"])),
        "rows": sorted(rows, key=lambda r: r["key"]),
        "parse_errors": parse_errors,
    }


def blind_spots(repo, *, tests_dir="tests", ignore=()):
    """What the AST census cannot read as save-then-read: sleep/poll/wait callers and non-Python suite files."""
    repo, out = Path(repo), {"waits": [], "non_python": []}
    for path in sorted((repo / tests_dir).rglob("*")):
        if not path.is_file() or set(path.relative_to(repo).parts) & SKIP_DIRS:
            continue
        rel = path.relative_to(repo).as_posix()
        if rel in ignore:
            continue
        if path.suffix == ".py":
            text = path.read_text(
                errors="replace"
            )  # an undecodable file is reported by scan(), not raised here
            out["waits"] += [
                f"{rel}:{i}"
                for i, line in enumerate(text.splitlines(), 1)
                if WAIT_NAME.search(line)
            ]
        elif path.suffix in (
            ".js",
            ".mjs",
            ".ts",
            ".tsx",
            ".sh",
            ".yaml",
            ".yml",
            ".json",
            ".feature",
        ):
            out["non_python"].append(rel)
    return out


def import_edges(repo, module_prefix, *, tests_dir="tests", ignore=()):
    """Test files that import ``module_prefix`` (the core wait helper must never appear here): sorted ``file:line``."""
    hits = []
    for path in _test_files(repo, tests_dir):
        rel = path.relative_to(repo).as_posix()
        if rel in ignore:
            continue
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue  # scan() records this file in parse_errors, which fails the census by name
        for node in ast.walk(tree):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            if any(
                n == module_prefix or n.startswith(module_prefix + ".") for n in names
            ):
                hits.append(f"{rel}:{node.lineno}")
    return sorted(hits)


# --- ENGINE END ---


REPO = "smart-memory-client"
IGNORE = (
    "tests/public_wait.py",
    "tests/test_public_wait.py",
    "tests/test_save_then_read_census.py",
)
SAVE_PATH = re.compile(r"^/memory/(add|ingest(/.*)?|import(/.*)?|okf/import)$")
MAYBE_SAVE = re.compile(r"add|ingest|import|save|store|bulk|upload|document")
# Methods that POST under a save-like name or path and are NOT a memory save, each with its reason.
NOT_SAVE = {
    "add_edge": "links two existing items, saves no content (/memory/edge)",
    "add_team_member": "membership admin, no memory content (/memory/teams/<id>/members)",
    "archive_put": "stores an archive blob keyed by the caller, outside the pipeline (/memory/archive/store)",
    "bulk_graph_upsert": "graph upsert of nodes and edges, no pipeline or extraction (/memory/graph/bulk)",
    "bulk_ontology_review_action": "ontology review queue admin (/memory/ontology/queue/bulk)",
    "get_edges_bulk": "a read posted as a body (/memory/graph/edges)",
    "import_registry": "ontology registry admin (/memory/ontology/registry/<id>/import)",
    "store_reasoning_trace": "reasoning trace log, not a memory item (/memory/reasoning/traces/store)",
}
NON_MEMORY = ["tests/conftest.py:142"]
WAIT_USERS = {}
OWNED_BY_U4_42 = None
SDK_OWNER = "C-01.activate.save.hosted-adapters (client receipt/status SDK, ring 3) via the real-SDK harness suite (graph C-49.contract.sdk-suites)"


def derive_vocab(repo):
    """Save methods are the SmartMemoryClient methods that POST to a save path. A save-looking POST outside the
    path set must be named in NOT_SAVE with a reason, so a new save path cannot slip past the census."""
    tree = ast.parse((Path(repo) / "smartmemory_client" / "client.py").read_text())
    methods, unnamed = set(), []
    for cls in (
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "SmartMemoryClient"
    ):
        for fn in (
            m
            for m in cls.body
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call)):
                if len(call.args) < 2 or not (
                    isinstance(call.args[0], ast.Constant)
                    and call.args[0].value == "POST"
                ):
                    continue
                path = (
                    call.args[1].value
                    if isinstance(call.args[1], ast.Constant)
                    else ast.unparse(call.args[1])
                )
                if SAVE_PATH.match(path):
                    methods.add(fn.name)
                elif MAYBE_SAVE.search(fn.name + path) and fn.name not in NOT_SAVE:
                    unnamed.append(fn.name)
    if unnamed:
        raise SystemExit(
            f"POST methods with a save-like name or path need a NOT_SAVE reason or a save path: {sorted(set(unnamed))}"
        )
    return {
        "save_methods": sorted(methods),
        "save_tools": [],
        "read_tools": [],
        "not_save": dict(sorted(NOT_SAVE.items())),
    }


def D(cls, why, where=None, prepared=None):
    out = {"class": cls, "why": why}
    if where:
        out |= {"where": where, "owner": SDK_OWNER, "prepared": prepared}
    return out


def _wait_get(who):
    return f'await_public(observe_get(client, {who}), wait="stored", deadline_s=30.0)'


def _wait_search(query, who, extra=""):
    return f'await_public(observe_search(client, {query}, {who}{extra}), wait="stored", deadline_s=30.0)'


MOCK = "the HTTP transport or the client call is mocked: no service and no worker, so there is nothing to wait for"
INT = "tests/integration/"
G, GO, CIT, SVC = (
    INT + "test_crud_golden.py",
    INT + "test_graph_operations.py",
    INT + "test_search_citations_roundtrip.py",
    INT + "test_local_service_fixture.py",
)
DISPOSITIONS = {
    f"{G}::TestCRUDGoldenFlow.test_add_different_memory_types": D(
        "save_only", "adds four items and only cleans up; nothing is read back"
    ),
    f"{G}::TestCRUDGoldenFlow.test_add_get_delete_flow": D(
        "deferred_ring3_sdk_harness",
        "add then an immediate get against the real service: reads an item whose visibility the service has not promised",
        [f"{G}:31", f"{G}:37"],
        _wait_get("item_id"),
    ),
    f"{G}::TestCRUDGoldenFlow.test_add_search_flow_with_pipeline": D(
        "deferred_ring3_sdk_harness",
        "add(use_pipeline=True) then an immediate search that asserts only the result type, so a queued save is read as empty",
        [f"{G}:66", f"{G}:70"],
        _wait_search("unique_id", "item_id", ", top_k=10"),
    ),
    f"{G}::TestCRUDGoldenFlow.test_add_with_metadata": D(
        "deferred_ring3_sdk_harness",
        "add then an immediate get against the real service",
        [f"{G}:90", f"{G}:96"],
        _wait_get("item_id"),
    ),
    f"{G}::TestCRUDGoldenFlow.test_search_with_filters": D(
        "deferred_ring3_sdk_harness",
        "two adds then an immediate filtered search that asserts at least one row",
        [f"{G}:127", f"{G}:138"],
        _wait_search("unique_id", "semantic_id", ', memory_type="semantic"'),
    ),
    f"{G}::TestIngestFlow.test_ingest_content": D(
        "save_only",
        "ingest returns a dict whose item_id or queued key is asserted; nothing is read back through a seam",
    ),
    f"{GO}::TestGraphOperationsFlow.setup_test_items": D(
        "save_only",
        "autouse fixture that adds two items; its readers are the consumer rows below",
    ),
    f"{GO}::TestGraphOperationsFlow.test_link_and_get_neighbors": D(
        "deferred_ring3_sdk_harness",
        "fixture saves two items, then link and get_neighbors read the graph with no wait for the saves",
        [f"{GO}:34", f"{GO}:60"],
        _wait_get("self.target_id"),
    ),
    f"{GO}::TestGraphOperationsFlow.test_link_nonexistent_source": D(
        "save_only",
        "uses the saving fixture and links a missing source; nothing is read back",
    ),
    f"{GO}::TestGraphOperationsFlow.test_link_nonexistent_target": D(
        "save_only",
        "uses the saving fixture and links a missing target; nothing is read back",
    ),
    f"{GO}::TestGraphOperationsFlow.test_link_with_different_types": D(
        "save_only",
        "adds targets and links them; the link result is asserted, no read follows",
    ),
    f"{GO}::TestZettelkastenOperations.setup_zettel_items": D(
        "save_only",
        "autouse fixture that adds two zettels; its readers are the consumer rows below",
    ),
    f"{GO}::TestZettelkastenOperations.test_backlinks_and_forward_links": D(
        "deferred_ring3_sdk_harness",
        "fixture saves two zettels, then forward links and backlinks are read with no wait for the saves",
        [f"{GO}:139", f"{GO}:161"],
        _wait_get("self.note2_id"),
    ),
    f"{GO}::TestZettelkastenOperations.test_get_connections": D(
        "deferred_ring3_sdk_harness",
        "fixture saves two zettels, then get_connections is read with no wait for the saves",
        [f"{GO}:139", f"{GO}:175"],
        _wait_get("self.note2_id"),
    ),
    f"{SVC}::test_owned_local_service_roundtrip": D(
        "deferred_ring3_sdk_harness",
        "add(use_pipeline=False, embed=False) then an immediate get and a direct service read",
        [f"{SVC}:17", f"{SVC}:19"],
        _wait_get("item_id"),
    ),
    f"{CIT}::TestSearchCitationRoundTrip.test_search_cite_false_leaves_last_citations_empty": D(
        "deferred_ring3_sdk_harness",
        "add then an immediate search whose empty-citations assertion would pass on an empty result",
        [f"{CIT}:53", f"{CIT}:59"],
        _wait_search('f"sdk no-cite roundtrip {tag}"', "item_id", ", top_k=5"),
    ),
    f"{CIT}::TestSearchCitationRoundTrip.test_search_cite_true_populates_last_citations": D(
        "deferred_ring3_sdk_harness",
        "six adds then an immediate cite=True search that asserts at least one row",
        [f"{CIT}:26", f"{CIT}:32"],
        _wait_search(
            'f"sdk citation roundtrip {tag}"', "item_id", ", top_k=10, cite=True"
        ),
    ),
}
for _key in (
    "test_chat_export_import.py::test_defaults_are_auto_detection_and_a_25_conversation_cap",
    "test_chat_export_import.py::test_import_chat_export_posts_multipart_with_form_fields",
    "test_chat_export_import.py::test_warnings_survive_to_the_caller",
    "test_chat_export_import.py::test_zip_payload_is_sent_with_a_zip_content_type",
    "test_client.py::test_add_memory_requires_auth",
    "test_client_errors.py::TestAddProfileNameSymmetry.test_add_with_profile_name_includes_it_in_body",
    "test_client_errors.py::TestAddProfileNameSymmetry.test_add_without_profile_name_omits_it",
    "test_embed_control_and_supersede_link.py::TestEmbedControl._add_body",
    "test_embed_control_and_supersede_link.py::TestEmbedControl.test_embed_false_forwarded",
    "test_embed_control_and_supersede_link.py::TestEmbedControl.test_embed_true_forwarded",
    "test_embed_control_and_supersede_link.py::TestEmbedControl.test_omitted_embed_is_absent_from_the_wire",
    "test_embed_control_and_supersede_link.py::TestEmbedControl.test_wire_field_name_matches_contract",
    "test_okf_portability.py::test_import_okf_uploads_archive_as_multipart_with_workspace_auth",
    "test_origin_propagation.py::test_ingest_and_conversation_context",
):
    DISPOSITIONS["tests/" + _key] = D("mocked_seam", MOCK)

# --- COMMON BEGIN (byte-identical in smart-memory-client and smart-memory-mcp scripts/save_then_read_census.py) ---

FIXTURE = "tests/data/save_then_read_census.json"
CLASSES = {
    "mocked_seam": "the transport or core is stubbed; no worker exists, so there is nothing to wait for",
    "local_inline": "a real local Lite core runs the save inline (G47); the read sees it, no wait, and no sync pin is added",
    "explicit_sync_kept": "a per-call sync=True the C1 guard classes EXPLICIT (G47 allows it); not a hidden pin",
    "save_only": "saves and never reads back, so it cannot observe a pending save",
    "not_a_save": "the name matches the vocabulary but nothing is saved (a tool-name list, a count, a registration)",
    "converted": "now waits with await_public (wait_line names the call)",
    "deferred_ring3_sdk_harness": "real-service SDK save-then-read, owned by the ring-3 real SDK harness (graph: C-49.contract.sdk-suites)",
    "deferred_real_worker": "real core or worker save-then-read candidate, carried into the later-ring real-worker harness (graph: C-49.contract.mcp-suites)",
}
DEFERRED = ("deferred_ring3_sdk_harness", "deferred_real_worker")


def engine_sha(script_text):
    """sha256 of the ENGINE region, so an edit to the engine without regenerating the fixture is caught."""
    start = script_text.index("# --- ENGINE BEGIN ---")
    end = script_text.index("# --- ENGINE END ---") + len("# --- ENGINE END ---")
    return hashlib.sha256(script_text[start:end].encode()).hexdigest()[:16]


def build(repo, *, script_text=None):
    """The census document for ``repo``: derived vocabulary, every unit with its disposition, every save site."""
    repo = Path(repo)
    script_text = script_text if script_text is not None else Path(__file__).read_text()
    vocab = derive_vocab(repo)
    engine_vocab = {
        "save_methods": set(vocab["save_methods"]),
        "save_tools": set(vocab["save_tools"]),
        "read_tools": set(vocab["read_tools"]),
    }
    found = scan(repo, engine_vocab, ignore=IGNORE)
    spots = blind_spots(repo, ignore=(FIXTURE,) + IGNORE)
    units = []
    for row in found["rows"]:
        units.append({**row, "disposition": DISPOSITIONS.get(row["key"])})
    return {
        "repo": REPO,
        "engine_sha": engine_sha(script_text),
        "vocab": {
            k: sorted(v) if isinstance(v, (set, list)) else v for k, v in vocab.items()
        },
        "ignore": sorted(IGNORE),
        "units": units,
        "sites": found["sites"],
        "non_memory_sites": NON_MEMORY,
        "parse_errors": found["parse_errors"],
        "blind_spots": {
            "waits": spots["waits"],
            "wait_users": WAIT_USERS,
            "non_python": spots["non_python"],
        },
        "core_wait_imports": import_edges(
            repo, "smartmemory.testing.waits", ignore=IGNORE
        ),
        "owned_by_u4_42": OWNED_BY_U4_42,
        "deferred": [
            {
                key: u["disposition"].get(key)
                for key in ("class", "where", "owner", "prepared")
            }
            | {"key": u["key"]}
            for u in units
            if u["disposition"] and u["disposition"]["class"] in DEFERRED
        ],
    }


def render(doc):
    return json.dumps(doc, indent=1, sort_keys=True) + "\n"


def problems(doc, repo):
    """Every reason the census is not trustworthy, as sentences. Empty means the census is complete and consistent."""
    repo, out = Path(repo), []
    keys = {u["key"] for u in doc["units"]}
    for key in sorted(set(DISPOSITIONS) - keys):
        out.append(
            f"disposition for {key} has no unit: the test or its save was removed or renamed"
        )
    for unit in doc["units"]:
        d = unit["disposition"]
        if d is None:
            out.append(
                f"{unit['key']} (line {unit['line']}) saves and has no disposition"
            )
            continue
        if d.get("class") not in CLASSES:
            out.append(f"{unit['key']}: unknown class {d.get('class')!r}")
            continue
        if not d.get("why"):
            out.append(f"{unit['key']}: a disposition needs a why")
        if d["class"] in DEFERRED:
            if not d.get("where") or not d.get("owner"):
                out.append(
                    f"{unit['key']}: a deferral names where (file:line) and its owner step"
                )
            prepared = d.get("prepared", "")
            try:
                call = ast.parse(prepared, mode="eval").body
                ok = isinstance(call, ast.Call) and _name(call.func) == "await_public"
                ok = ok and {k.arg for k in call.keywords} >= {"wait", "deadline_s"}
                ok = ok and any(
                    isinstance(a, ast.Call)
                    and _name(a.func) in ("observe_get", "observe_search")
                    for a in call.args
                )
            except SyntaxError:
                ok = False
            if not ok:
                out.append(
                    f"{unit['key']}: a deferral carries the prepared await_public(observe_get|observe_search(...), wait=, deadline_s=) call"
                )
            for where in d.get("where", []):
                path, _, line = where.rpartition(":")
                target = repo / path
                if not (
                    target.is_file()
                    and line.isdigit()
                    and 1 <= int(line) <= len(target.read_text().splitlines())
                ):
                    out.append(
                        f"{unit['key']}: where {where} is not a line of this tree"
                    )
        if d["class"] == "converted" and not d.get("wait_line"):
            out.append(
                f"{unit['key']}: converted needs the wait_line of its await_public call"
            )
        if d["class"] == "save_only" and unit["reads_after_save"]:
            out.append(
                f"{unit['key']}: classed save_only but a read follows the save (lines {unit['reads']})"
            )
    memory_less = {
        f"{s['file']}:{s['line']}" for s in doc["sites"] if not s["memory_like"]
    }
    for site in sorted(memory_less - set(NON_MEMORY)):
        out.append(
            f"{site}: a save-named call on a receiver that does not look like memory, name it in NON_MEMORY"
        )
    for site in sorted(set(NON_MEMORY) - memory_less):
        out.append(f"NON_MEMORY names {site}, which is not a non-memory save site now")
    for spot in sorted(
        {w.rsplit(":", 1)[0] for w in doc["blind_spots"]["waits"]} - set(WAIT_USERS)
    ):
        out.append(f"{spot} sleeps, polls or waits and is not named in WAIT_USERS")
    for user in sorted(
        set(WAIT_USERS) - {w.rsplit(":", 1)[0] for w in doc["blind_spots"]["waits"]}
    ):
        out.append(f"WAIT_USERS names {user}, which no longer waits")
    if doc["parse_errors"]:
        out.append(
            f"{len(doc['parse_errors'])} test file(s) could not be parsed: {doc['parse_errors']}"
        )
    if doc["core_wait_imports"]:
        out.append(
            f"the core wait helper is imported by an outer suite: {doc['core_wait_imports']}"
        )
    if OWNED_BY_U4_42 and (repo / OWNED_BY_U4_42["file"]).exists():
        out.append(
            f"{OWNED_BY_U4_42['file']} landed: convert the owned_by_u4_42 rows into dispositions and delete the list"
        )
    return out


def main(argv):
    root = Path(__file__).resolve().parents[1]
    doc = build(root)
    text = render(doc)
    fixture = root / FIXTURE
    if "--write" in argv:
        fixture.parent.mkdir(parents=True, exist_ok=True)
        fixture.write_text(text)
        print(
            f"wrote {FIXTURE}: {len(doc['units'])} units, {len(doc['sites'])} save sites"
        )
    for line in problems(doc, root):
        print("PROBLEM:", line)
    if "--table" in argv:
        for u in doc["units"]:
            d = u["disposition"] or {"class": "MISSING"}
            print(
                f"{u['file']}:{u['line']} {u['function']} [{d['class']}] saves={[s[0] for s in u['saves']]}"
            )
    stale = not fixture.exists() or fixture.read_text() != text
    print("fixture " + ("STALE: run with --write" if stale else "current"))
    return 1 if stale or problems(doc, root) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
# --- COMMON END ---
