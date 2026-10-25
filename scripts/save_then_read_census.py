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
# Direct store setup: a test that seeds the store without the public save seam still saves, so it is a unit.
STORE_SETUP = {"add_node", "publish", "publish_bundle", "code_index"}
# ``x.add.assert_called_once()``, ``x.add.return_value``: the attribute is configured or asserted, not used as a save.
MOCK_ATTR = re.compile(
    r"^(assert\w*|return_value|side_effect|called|call_args\w*|call_count|await_\w+|mock_calls|method_calls|reset_mock)$"
)


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


def _parametrized(fn, tables):
    """``{parameter: [(line, string)]}`` for the string cells of every ``parametrize`` table on ``fn`` (a literal table, or a
    module-level name bound to one), so a ``getattr(client, method_name)`` dispatch is read as the methods the table names."""
    out = {}
    for d in fn.decorator_list:
        if not (
            isinstance(d, ast.Call)
            and _name(d.func).split(".")[-1] == "parametrize"
            and len(d.args) >= 2
        ):
            continue
        names, rows = d.args[0], d.args[1]
        if isinstance(names, ast.Constant) and isinstance(names.value, str):
            argnames = [n.strip() for n in names.value.split(",")]
        elif isinstance(names, (ast.Tuple, ast.List)):
            argnames = [
                e.value
                for e in names.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            ]
        else:
            continue
        if isinstance(rows, ast.Name):
            rows = tables.get(rows.id)
        if not isinstance(rows, (ast.List, ast.Tuple)):
            continue
        for row in rows.elts:
            if isinstance(row, ast.Call) and _name(row.func).split(".")[-1] == "param":
                cells = row.args
            elif isinstance(row, (ast.Tuple, ast.List)) and len(argnames) > 1:
                cells = row.elts
            else:
                cells = [row]
            for i, arg in enumerate(argnames):
                if (
                    i < len(cells)
                    and isinstance(cells[i], ast.Constant)
                    and isinstance(cells[i].value, str)
                ):
                    out.setdefault(arg, []).append((cells[i].lineno, cells[i].value))
    return out


def _dispatch(fn, tables):
    """The ``getattr(receiver, name)`` dispatches of ``fn``: ``(resolved, unresolved)``. ``resolved`` is
    ``(line, name, receiver)`` for a constant name or each string a parametrize table feeds into the name parameter
    (the line is the ``getattr`` call that runs it, so the order of the table never changes the verdict);
    ``unresolved`` is the line of a dispatch whose name no literal table names (reported, never ignored)."""
    resolved, unresolved, table = [], [], _parametrized(fn, tables)
    params = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
    for node in _own_nodes(fn):
        if not (
            isinstance(node, ast.Call)
            and _name(node.func) == "getattr"
            and len(node.args) >= 2
        ):
            continue
        recv, what = _name(node.args[0]), node.args[1]
        if isinstance(what, ast.Constant) and isinstance(what.value, str):
            resolved.append((node.lineno, what.value, recv))
        elif isinstance(what, ast.Name) and what.id in params and what.id in table:
            resolved += [(node.lineno, value, recv) for _, value in table[what.id]]
        elif _memory_like(recv):
            unresolved.append(node.lineno)
    return resolved, unresolved


def call_sites(fn, vocab, tables=None):
    """Every save and read site in ``fn``: sorted (line, kind, name, receiver, memory_like).

    Beyond ``recv.method(...)`` it recognizes an attribute used as a value (``run = client.add``), a ``getattr``
    dispatch (a constant, or the strings of a parametrize table), a store-setup call (``STORE_SETUP``) and the
    registered tool names as string constants.
    """
    out, tables = set(), tables or {}
    configured = {
        id(n.value)
        for n in _own_nodes(fn)
        if isinstance(n, ast.Attribute) and MOCK_ATTR.match(n.attr)
    }
    for node in _own_nodes(fn):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            attr, recv = node.attr, _name(node.value)
            if attr in STORE_SETUP:
                out.add((node.lineno, "save", attr, recv, True))
            elif attr in vocab["save_methods"] and id(node) not in configured:
                out.add((node.lineno, "save", attr, recv, _memory_like(recv)))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and READ_NAME.match(node.func.attr)
        ):
            recv = _name(node.func.value)
            out.add((node.lineno, "read", node.func.attr, recv, _memory_like(recv)))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in vocab["save_tools"]:
                out.add((node.lineno, "save", node.value, "<tool-name>", True))
            elif node.value in vocab["read_tools"]:
                out.add((node.lineno, "read", node.value, "<tool-name>", True))
    for line, name, recv in _dispatch(fn, tables)[0]:
        if name in STORE_SETUP:
            out.add((line, "save", name, recv, True))
        elif name in vocab["save_methods"]:
            out.add((line, "save", name, recv, _memory_like(recv)))
        elif READ_NAME.match(name):
            out.add((line, "read", name, recv, _memory_like(recv)))
    return sorted(out)


def _module_tables(tree):
    """Module-level ``NAME = [...]`` / ``(...)`` literals, so a parametrize table held in a name can be read."""
    return {
        t.id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, (ast.List, ast.Tuple))
        for t in node.targets
        if isinstance(t, ast.Name)
    }


def _imports(tree, stems):
    """``(names, modules)`` this file imports from other test files: ``names`` maps a local name to
    ``([files], original name)``, ``modules`` maps a local module alias to ``[files]``. ``stems`` is
    ``{module stem: [repo-relative files]}``."""
    names, modules = {}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            stem = (node.module or "").split(".")[-1]
            for a in node.names:
                if stem in stems:
                    names[a.asname or a.name] = (stems[stem], a.name)
                elif a.name in stems:
                    modules[a.asname or a.name] = stems[a.name]
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[-1] in stems:
                    modules[a.asname or a.name] = stems[a.name.split(".")[-1]]
    return names, modules


def _imported(imports, crel, rel, bare, cinfo, how):
    """The line at which ``cinfo`` (in ``crel``) uses ``bare`` defined in ``rel``, when ``crel`` imports it from ``rel``
    (``from m import bare [as x]``, or ``module.bare`` through an imported module alias); 0 when it does not."""
    names, modules = imports.get(crel, ({}, {}))
    if crel == rel:
        return 0
    for local, (files, orig) in names.items():
        if rel in files and orig == bare:
            if how == "params":
                return cinfo["line"] if local in cinfo["params"] else 0
            return cinfo["call_full"].get(local, 0)
    if how == "calls":
        for alias, files in modules.items():
            if rel in files and f"{alias}.{bare}" in cinfo["call_full"]:
                return cinfo["call_full"][f"{alias}.{bare}"]
    return 0


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
    sites, funcs, parse_errors, dynamic, imports = [], {}, [], [], {}
    trees, stems = {}, {}
    for path in _test_files(repo, tests_dir):
        rel = path.relative_to(repo).as_posix()
        if rel in ignore:
            continue
        try:
            trees[rel] = ast.parse(read_source(path))
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            parse_errors.append({"file": rel, "error": f"{type(exc).__name__}: {exc}"})
            continue
        stems.setdefault(path.stem, []).append(rel)
    for rel, tree in trees.items():
        imports[rel] = _imports(tree, stems)
        tables = _module_tables(tree)
        for qual, fn in _walk_functions(tree):
            calls = call_sites(fn, vocab, tables)
            dynamic += [f"{rel}:{line}" for line in _dispatch(fn, tables)[1]]
            call_lines, call_full = {}, {}
            for n in _own_nodes(fn):
                if isinstance(n, ast.Call):
                    full = _name(n.func)
                    call_lines[full.split(".")[-1]] = min(
                        n.lineno, call_lines.get(full.split(".")[-1], n.lineno)
                    )
                    call_full[full] = min(n.lineno, call_full.get(full, n.lineno))
            funcs[(rel, qual)] = {
                "line": fn.lineno,
                "bare": fn.name,
                "fixture": _fixture_kind(fn),
                "params": [a.arg for a in fn.args.args + fn.args.kwonlyargs],
                "calls": calls,
                "call_lines": call_lines,
                "call_full": call_full,
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
                    (
                        crel.rsplit("/", 1)[0] == rel.rsplit("/", 1)[0]
                        or _imported(imports, crel, rel, info["bare"], cinfo, "params")
                    )
                    and info["bare"] in cinfo["params"],
                    cinfo["line"],
                )
            else:
                imported = _imported(imports, crel, rel, info["bare"], cinfo, "calls")
                hit, point = (
                    (crel == rel and info["bare"] in cinfo["call_lines"])
                    or bool(imported),
                    imported or cinfo["call_lines"].get(info["bare"], cinfo["line"]),
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
        "dynamic": sorted(dynamic),
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
SAVE_PATH = re.compile(
    r"^/memory/(add|ingest(/.*)?|import(/.*)?|okf/import|code/index)$"
)
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
DYNAMIC = {}
WAIT_USERS = {
    "tests/test_save_receipt.py": "tests the SDK await helper itself against a fake transport and a fake clock; it waits on no live save",
}
OWNED_BY_U4_42 = None
SDK_OWNER = "C-01.activate.save.hosted-adapters"


def derive_vocab(repo):
    """Save methods are the SmartMemoryClient methods that POST to a save path. A save-looking POST outside the
    path set must be named in NOT_SAVE with a reason, so a new save path cannot slip past the census."""
    tree = ast.parse((Path(repo) / "smartmemory_client" / "client.py").read_text())
    methods, unnamed, other_posts = set(), [], set()
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
            if fn.name == "_save":
                continue  # the retry/receipt helper: its callers below are the save methods
            for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call)):
                # 2.0: add()/ingest() reach the service through self._save("<path>", ...), one POST per call
                if (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "_save"
                    and call.args
                    and isinstance(call.args[0], ast.Constant)
                ):
                    path = call.args[0].value
                elif len(call.args) < 2 or not (
                    isinstance(call.args[0], ast.Constant)
                    and call.args[0].value == "POST"
                ):
                    continue
                else:
                    path = (
                        call.args[1].value
                        if isinstance(call.args[1], ast.Constant)
                        else ast.unparse(call.args[1])
                    )
                if SAVE_PATH.match(path):
                    methods.add(fn.name)
                elif MAYBE_SAVE.search(fn.name + path) and fn.name not in NOT_SAVE:
                    unnamed.append(fn.name)
                else:
                    other_posts.add(fn.name)
    if unnamed:
        raise SystemExit(
            f"POST methods with a save-like name or path need a NOT_SAVE reason or a save path: {sorted(set(unnamed))}"
        )
    return {
        "save_methods": sorted(methods),
        "save_tools": [],
        "read_tools": [],
        "not_save": dict(sorted(NOT_SAVE.items())),
        # every other POST method, listed so a path left out of SAVE_PATH is visible in the fixture, never silent
        "other_post_methods": sorted(other_posts - methods - set(NOT_SAVE)),
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
    "test_url_contracts.py::test_code_index_defaults_and_validates_before_request",
    "test_url_contracts.py::test_code_index_sends_exact_service_body",
    "test_url_contracts.py::test_code_index_sends_repo_identity_only_when_given",
    "test_url_contracts.py::test_public_api_method_urls",
    "test_save_receipt.py::test_a_409_on_a_save_is_the_typed_scoped_conflict_with_one_request",
    "test_save_receipt.py::test_a_caller_key_is_kept_and_a_malformed_key_is_refused_before_any_request",
    "test_save_receipt.py::test_a_fake_that_always_fails_gets_exactly_four_attempts_then_the_typed_error_with_the_key",
    "test_save_receipt.py::test_a_future_major_through_add_raises_the_typed_error_with_the_handle",
    "test_save_receipt.py::test_a_raw_connection_error_is_transport_loss_and_comes_back_typed",
    "test_save_receipt.py::test_a_retry_after_is_a_minimum_delay_and_one_that_cannot_fit_stops_the_retries",
    "test_save_receipt.py::test_a_status_less_error_with_no_transport_cause_is_not_retried",
    "test_save_receipt.py::test_add_returns_the_receipt_and_sends_one_minted_key",
    "test_save_receipt.py::test_an_empty_save_answer_is_a_typed_error_not_a_receipt",
    "test_save_receipt.py::test_ingest_omits_wait_when_unset_and_refuses_an_unknown_wait_before_sending",
    "test_save_receipt.py::test_ingest_with_wait_extracted_replaces_ingest_full",
    "test_save_receipt.py::test_statuses_outside_the_retry_list_are_one_request_and_never_a_new_key",
    "test_save_receipt.py::test_three_transport_losses_then_success_is_four_identical_requests",
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
# An owner is the WHOLE string: a graph step id (C-49.contract.sdk-suites) or a filed unit id (C49-RW-HARNESS-1).
# It is matched with fullmatch, so a prefix that looks like an id never passes ("NOT AN OWNER" starts with "NOT").
OWNER_ID = re.compile(
    r"C-\d+(?:\.[a-z0-9]+(?:-[a-z0-9]+)*)*|[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)+"
)


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
            "dynamic_dispatch": {line: DYNAMIC.get(line) for line in found["dynamic"]},
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
            elif not OWNER_ID.fullmatch(d["owner"]):
                out.append(
                    f"{unit['key']}: owner {d['owner']!r} is not a graph step id or a filed unit id (a description is not an owner)"
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
    dynamic = set(doc["blind_spots"]["dynamic_dispatch"])
    for line in sorted(dynamic - set(DYNAMIC)):
        out.append(
            f"{line}: a getattr dispatch on a memory-like receiver whose name no literal table names, name it in DYNAMIC with a reason"
        )
    for line in sorted(set(DYNAMIC) - dynamic):
        out.append(f"DYNAMIC names {line}, which is not an unresolved dispatch now")
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
