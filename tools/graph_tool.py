"""Bounded NetworkX analysis for AML transaction topologies."""
from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations, islice
from typing import Any

import networkx as nx
import pandas as pd


DEFAULT_MAX_EDGES = 500_000
DEFAULT_MAX_RESULTS = 100
DEFAULT_CYCLE_SEARCH_EDGES = 50_000
_MIN_FAN_DEGREE = 3


def _empty_result(status: str, note: str, input_rows: int) -> dict:
    return {
        "status": status,
        "summary": {
            "input_rows": int(input_rows),
            "nodes": 0,
            "edges": 0,
            "self_loops": 0,
            "density": 0.0,
        },
        "cycles": [],
        "fan_in": [],
        "fan_out": [],
        "bipartite": [],
        "gather_scatter": [],
        "scatter_gather": [],
        "note": note,
    }


def _build_graph(df: pd.DataFrame) -> nx.DiGraph:
    amount_column = (
        "amount_paid"
        if "amount_paid" in df
        else "amount"
        if "amount" in df
        else None
    )
    working = pd.DataFrame(
        {
            "source": df["from_account"].astype("string").fillna("").str.strip(),
            "target": df["to_account"].astype("string").fillna("").str.strip(),
            "amount": (
                pd.to_numeric(df[amount_column], errors="coerce").fillna(0.0)
                if amount_column
                else 0.0
            ),
            "timestamp": (
                pd.to_datetime(df["timestamp"], errors="coerce")
                if "timestamp" in df
                else pd.NaT
            ),
        }
    )
    working = working.loc[
        working["source"].ne("") & working["target"].ne("")
    ]

    graph = nx.DiGraph()
    for source, target, amount, timestamp in working.itertuples(
        index=False,
        name=None,
    ):
        amount = float(amount)
        timestamp_value = (
            timestamp.isoformat() if not pd.isna(timestamp) else None
        )
        if graph.has_edge(source, target):
            edge = graph[source][target]
            edge["transaction_count"] += 1
            edge["total_amount"] += amount
            edge["last_timestamp"] = timestamp_value
        else:
            graph.add_edge(
                str(source),
                str(target),
                transaction_count=1,
                total_amount=amount,
                first_timestamp=timestamp_value,
                last_timestamp=timestamp_value,
            )
    return graph


def _cycle_result(graph: nx.DiGraph, cycle: list[str]) -> dict:
    edges = list(zip(cycle, cycle[1:] + cycle[:1]))
    return {
        "accounts": [str(node) for node in cycle],
        "length": len(cycle),
        "transaction_count": int(
            sum(graph[source][target]["transaction_count"] for source, target in edges)
        ),
        "total_amount": round(
            float(
                sum(
                    graph[source][target]["total_amount"]
                    for source, target in edges
                )
            ),
            2,
        ),
    }


def _fan_results(
    graph: nx.DiGraph,
    direction: str,
    max_results: int,
) -> list[dict]:
    degree_view = graph.in_degree if direction == "in" else graph.out_degree
    candidates = sorted(
        (
            (str(node), int(degree))
            for node, degree in degree_view
            if degree >= _MIN_FAN_DEGREE
        ),
        key=lambda item: (-item[1], item[0]),
    )[:max_results]

    results = []
    for node, degree in candidates:
        neighbors = (
            sorted(str(value) for value in graph.predecessors(node))
            if direction == "in"
            else sorted(str(value) for value in graph.successors(node))
        )
        edges = (
            [(source, node) for source in graph.predecessors(node)]
            if direction == "in"
            else [(node, target) for target in graph.successors(node)]
        )
        results.append(
            {
                "account": node,
                "degree": degree,
                "counterparties": neighbors[:20],
                "transaction_count": int(
                    sum(
                        graph[source][target]["transaction_count"]
                        for source, target in edges
                    )
                ),
                "total_amount": round(
                    float(
                        sum(
                            graph[source][target]["total_amount"]
                            for source, target in edges
                        )
                    ),
                    2,
                ),
            }
        )
    return results


def _bipartite_patterns(
    graph: nx.DiGraph,
    max_results: int,
    max_pair_operations: int = 100_000,
) -> tuple[list[dict], bool]:
    """Find bounded K(2,n) sender/recipient structures."""
    shared_targets: dict[tuple[str, str], list[str]] = defaultdict(list)
    operations = 0
    truncated = False
    for target in graph.nodes:
        predecessors = sorted(str(node) for node in graph.predecessors(target))
        if len(predecessors) < 2:
            continue
        for pair in combinations(predecessors, 2):
            shared_targets[pair].append(str(target))
            operations += 1
            if operations >= max_pair_operations:
                truncated = True
                break
        if truncated:
            break

    patterns = [
        {
            "sources": list(pair),
            "destinations": sorted(destinations)[:20],
            "source_count": 2,
            "destination_count": len(destinations),
            "edge_count": 2 * len(destinations),
        }
        for pair, destinations in shared_targets.items()
        if len(destinations) >= 2
    ]
    patterns.sort(
        key=lambda item: (
            -item["destination_count"],
            item["sources"],
        )
    )
    return patterns[:max_results], truncated


def _gather_scatter_patterns(
    graph: nx.DiGraph,
    max_results: int,
) -> list[dict]:
    patterns = []
    for node in graph.nodes:
        predecessors = sorted(str(value) for value in graph.predecessors(node))
        successors = sorted(str(value) for value in graph.successors(node))
        if (
            len(predecessors) >= _MIN_FAN_DEGREE
            and len(successors) >= _MIN_FAN_DEGREE
        ):
            patterns.append(
                {
                    "hub": str(node),
                    "sources": predecessors[:20],
                    "destinations": successors[:20],
                    "source_count": len(predecessors),
                    "destination_count": len(successors),
                }
            )
    patterns.sort(
        key=lambda item: (
            -(item["source_count"] + item["destination_count"]),
            item["hub"],
        )
    )
    return patterns[:max_results]


def _scatter_gather_patterns(
    graph: nx.DiGraph,
    max_results: int,
) -> list[dict]:
    patterns = []
    for source in graph.nodes:
        intermediaries = list(graph.successors(source))
        if len(intermediaries) < _MIN_FAN_DEGREE:
            continue
        destination_counts: Counter[str] = Counter()
        paths: dict[str, list[str]] = defaultdict(list)
        for intermediary in intermediaries:
            for destination in graph.successors(intermediary):
                if destination == source:
                    continue
                destination_key = str(destination)
                destination_counts[destination_key] += 1
                paths[destination_key].append(str(intermediary))
        for destination, count in destination_counts.items():
            if count >= _MIN_FAN_DEGREE:
                patterns.append(
                    {
                        "source": str(source),
                        "destination": destination,
                        "intermediaries": sorted(paths[destination])[:20],
                        "path_count": int(count),
                    }
                )
    patterns.sort(
        key=lambda item: (
            -item["path_count"],
            item["source"],
            item["destination"],
        )
    )
    return patterns[:max_results]


def run_graph(
    df: pd.DataFrame,
    max_edges: int = DEFAULT_MAX_EDGES,
    max_results: int = DEFAULT_MAX_RESULTS,
    cycle_search_edge_limit: int = DEFAULT_CYCLE_SEARCH_EDGES,
) -> dict[str, Any]:
    """Build a directed graph and return bounded, non-fabricated patterns."""
    required = {"from_account", "to_account"}
    missing = sorted(required.difference(df.columns))
    if missing:
        raise ValueError("graph analysis requires columns: " + ", ".join(missing))
    if max_edges <= 0 or max_results <= 0:
        raise ValueError("graph limits must be greater than zero")
    if len(df) > max_edges:
        result = _empty_result(
            status="skipped",
            note=(
                f"Graph analysis skipped: {len(df):,} transaction rows exceed "
                f"the configured {max_edges:,}-row safety limit."
            ),
            input_rows=len(df),
        )
        result["summary"]["edges"] = None
        return result
    if df.empty:
        return _empty_result(
            status="ok",
            note="No transactions were available for graph analysis.",
            input_rows=0,
        )

    graph = _build_graph(df)
    node_count = graph.number_of_nodes()
    edge_count = graph.number_of_edges()
    notes: list[str] = []

    cycles: list[dict] = []
    if edge_count <= cycle_search_edge_limit:
        cycle_iter = (
            cycle
            for cycle in nx.simple_cycles(graph, length_bound=4)
            if 2 <= len(cycle) <= 4
        )
        cycles = [
            _cycle_result(graph, cycle)
            for cycle in islice(cycle_iter, max_results)
        ]
        if not cycles:
            notes.append("No circular transfers detected in this time window.")
        elif len(cycles) >= max_results:
            notes.append(
                f"Cycle results were capped at {max_results:,} patterns."
            )
    else:
        notes.append(
            "Cycle search skipped because the aggregated graph exceeded "
            f"{cycle_search_edge_limit:,} edges."
        )

    bipartite, bipartite_truncated = _bipartite_patterns(
        graph,
        max_results=max_results,
    )
    if bipartite_truncated:
        notes.append(
            "Bipartite pair search reached its bounded operation limit."
        )

    density = (
        float(nx.density(graph))
        if node_count > 1
        else 0.0
    )
    return {
        "status": "ok",
        "summary": {
            "input_rows": int(len(df)),
            "nodes": int(node_count),
            "edges": int(edge_count),
            "self_loops": int(nx.number_of_selfloops(graph)),
            "density": round(density, 8),
        },
        "cycles": cycles,
        "fan_in": _fan_results(graph, "in", max_results),
        "fan_out": _fan_results(graph, "out", max_results),
        "bipartite": bipartite,
        "gather_scatter": _gather_scatter_patterns(graph, max_results),
        "scatter_gather": _scatter_gather_patterns(graph, max_results),
        "note": " ".join(notes) if notes else "Graph analysis completed.",
    }
