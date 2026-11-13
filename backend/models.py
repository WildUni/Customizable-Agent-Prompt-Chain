"""Chain data model: a chain is a directed acyclic graph of prompt nodes.

See SPEC.md section 4.
"""
from collections import deque
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field as PydanticField, model_validator
from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from llm import LLMSettings


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------- graph pieces ----------

class Position(BaseModel):
    x: float = 0
    y: float = 0


class Node(BaseModel):
    id: str = PydanticField(min_length=1)
    type: Literal["prompt"] = "prompt"
    label: str = ""
    prompt_template: str = ""
    settings: LLMSettings = PydanticField(default_factory=LLMSettings)
    position: Position = PydanticField(default_factory=Position)


class Edge(BaseModel):
    id: str = PydanticField(min_length=1)
    source: str
    target: str
    condition: str | None = None
    label: str = ""


class ChainGraph(BaseModel):
    nodes: list[Node] = PydanticField(default_factory=list)
    edges: list[Edge] = PydanticField(default_factory=list)

    @model_validator(mode="after")
    def _validate_graph(self) -> "ChainGraph":
        node_ids: set[str] = set()
        for node in self.nodes:
            if node.id in node_ids:
                raise ValueError(f"duplicate node id: {node.id!r}")
            node_ids.add(node.id)

        edge_ids: set[str] = set()
        pairs: set[tuple[str, str]] = set()
        for edge in self.edges:
            if edge.id in edge_ids:
                raise ValueError(f"duplicate edge id: {edge.id!r}")
            edge_ids.add(edge.id)
            for end in (edge.source, edge.target):
                if end not in node_ids:
                    raise ValueError(f"edge {edge.id!r} references unknown node {end!r}")
            if edge.source == edge.target:
                raise ValueError(f"edge {edge.id!r} is a self-loop on {edge.source!r}")
            pair = (edge.source, edge.target)
            if pair in pairs:
                raise ValueError(
                    f"edge {edge.id!r} duplicates connection {edge.source!r} -> {edge.target!r}"
                )
            pairs.add(pair)

        order = self._kahn()
        if len(order) < len(self.nodes):
            in_cycle = [n.id for n in self.nodes if n.id not in set(order)]
            raise ValueError(f"graph contains a cycle involving nodes: {in_cycle}")
        return self

    # ---------- queries ----------

    def get_node(self, node_id: str) -> Node:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(node_id)

    def outgoing(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.source == node_id]

    def incoming(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.target == node_id]

    def roots(self) -> list[Node]:
        targets = {e.target for e in self.edges}
        return [n for n in self.nodes if n.id not in targets]

    def leaves(self) -> list[Node]:
        sources = {e.source for e in self.edges}
        return [n for n in self.nodes if n.id not in sources]

    def topological_order(self) -> list[str]:
        return self._kahn()

    def _kahn(self) -> list[str]:
        """Kahn's algorithm; ties broken by node-list order. Returns a partial
        order (missing some nodes) if the graph has a cycle."""
        index = {n.id: i for i, n in enumerate(self.nodes)}
        indegree = {n.id: 0 for n in self.nodes}
        children: dict[str, list[str]] = {n.id: [] for n in self.nodes}
        for e in self.edges:
            if e.source in children and e.target in indegree:
                children[e.source].append(e.target)
                indegree[e.target] += 1

        # Ready set kept sorted by node-list position for determinism.
        ready = deque(sorted((nid for nid, d in indegree.items() if d == 0), key=index.get))
        order: list[str] = []
        while ready:
            nid = ready.popleft()
            order.append(nid)
            newly_ready = []
            for child in children[nid]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    newly_ready.append(child)
            if newly_ready:
                ready = deque(sorted([*ready, *newly_ready], key=index.get))
        return order


# ---------- database table ----------

class Chain(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    graph: dict[str, Any] = Field(
        default_factory=lambda: ChainGraph().model_dump(mode="json"),
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    def get_graph(self) -> ChainGraph:
        return ChainGraph.model_validate(self.graph)

    def set_graph(self, graph: ChainGraph) -> None:
        self.graph = graph.model_dump(mode="json")
        self.updated_at = _utcnow()


# ---------- API schemas ----------

class ChainCreate(BaseModel):
    name: str
    graph: ChainGraph = PydanticField(default_factory=ChainGraph)


class ChainRead(BaseModel):
    id: int
    name: str
    graph: ChainGraph
    created_at: datetime
    updated_at: datetime
