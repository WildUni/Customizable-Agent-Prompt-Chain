import math

import pytest
from pydantic import ValidationError
from sqlmodel import Session, SQLModel, create_engine

from models import (
    NAME_MAX_LENGTH,
    Chain,
    ChainCreate,
    ChainGraph,
    ChainRead,
    Edge,
    Node,
    Position,
)

# ---------- helpers ----------

def graph(node_ids, edges=()):
    """graph(["a", "b"], [("a", "b")]) -> ChainGraph with edge ids e0, e1, ..."""
    return ChainGraph(
        nodes=[Node(id=n) for n in node_ids],
        edges=[Edge(id=f"e{i}", source=s, target=t) for i, (s, t) in enumerate(edges)],
    )


# ---------- defaults ----------

def test_empty_graph_is_valid():
    g = ChainGraph()
    assert g.nodes == [] and g.edges == []
    assert g.topological_order() == []


def test_node_defaults():
    n = Node(id="a")
    assert n.type == "prompt"
    assert n.prompt_template == ""
    assert n.position.x == 0 and n.position.y == 0
    assert n.settings.temperature == 0.7


def test_empty_ids_rejected():
    with pytest.raises(ValidationError):
        Node(id="")
    with pytest.raises(ValidationError):
        Edge(id="", source="a", target="b")


def test_disconnected_nodes_are_valid():
    g = graph(["a", "b", "c"])
    assert [n.id for n in g.roots()] == ["a", "b", "c"]


# ---------- validation ----------

@pytest.mark.parametrize(
    "build, message",
    [
        (lambda: graph(["a", "a"]), "duplicate node id"),
        (
            lambda: ChainGraph(
                nodes=[Node(id="a"), Node(id="b"), Node(id="c")],
                edges=[Edge(id="e", source="a", target="b"), Edge(id="e", source="b", target="c")],
            ),
            "duplicate edge id",
        ),
        (lambda: graph(["a"], [("a", "missing")]), "unknown node 'missing'"),
        (lambda: graph(["a"], [("missing", "a")]), "unknown node 'missing'"),
        (lambda: graph(["a"], [("a", "a")]), "self-loop"),
        (lambda: graph(["a", "b"], [("a", "b"), ("a", "b")]), "duplicates connection"),
        (lambda: graph(["a", "b", "c"], [("a", "b"), ("b", "c"), ("c", "a")]), "cycle"),
    ],
)
def test_invalid_graphs_rejected(build, message):
    with pytest.raises(ValidationError, match=message):
        build()


# ---------- queries ----------

@pytest.fixture
def diamond():
    #     a
    #    / \
    #   b   c
    #    \ /
    #     d
    return graph(["a", "b", "c", "d"], [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")])


def test_multiple_outgoing_and_incoming(diamond):
    assert [e.target for e in diamond.outgoing("a")] == ["b", "c"]
    assert [e.source for e in diamond.incoming("d")] == ["b", "c"]
    assert diamond.incoming("a") == []
    assert diamond.outgoing("d") == []


def test_roots_and_leaves(diamond):
    assert [n.id for n in diamond.roots()] == ["a"]
    assert [n.id for n in diamond.leaves()] == ["d"]


def test_get_node(diamond):
    assert diamond.get_node("c").id == "c"
    with pytest.raises(KeyError):
        diamond.get_node("zzz")


def test_topological_order_diamond(diamond):
    assert diamond.topological_order() == ["a", "b", "c", "d"]


def test_topological_order_respects_edges_not_list_order():
    g = graph(["c", "b", "a"], [("a", "b"), ("b", "c")])
    assert g.topological_order() == ["a", "b", "c"]


def test_topological_order_ties_follow_node_list_order():
    g = graph(["x", "a", "y"], [("a", "y")])
    assert g.topological_order() == ["x", "a", "y"]


def test_edge_condition_defaults_to_none():
    assert Edge(id="e", source="a", target="b").condition is None


# ---------- persistence ----------

@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_chain_round_trip(session, diamond):
    chain = Chain(name="demo")
    chain.set_graph(diamond)
    session.add(chain)
    session.commit()
    session.refresh(chain)

    loaded = session.get(Chain, chain.id)
    assert loaded.name == "demo"
    assert loaded.get_graph() == diamond


def test_new_chain_has_empty_graph(session):
    chain = Chain(name="empty")
    session.add(chain)
    session.commit()
    assert session.get(Chain, chain.id).get_graph() == ChainGraph()


def test_set_graph_bumps_updated_at(diamond):
    chain = Chain(name="demo")
    before = chain.updated_at
    chain.set_graph(diamond)
    assert chain.updated_at >= before


# ---------- API schemas ----------

def test_chain_create_validates_graph():
    with pytest.raises(ValidationError):
        ChainCreate(name="bad", graph={"nodes": [{"id": "a"}], "edges": [
            {"id": "e", "source": "a", "target": "a"}]})


def test_chain_read_from_table(diamond):
    chain = Chain(id=1, name="demo")
    chain.set_graph(diamond)
    read = ChainRead(
        id=chain.id, name=chain.name, graph=chain.get_graph(),
        created_at=chain.created_at, updated_at=chain.updated_at,
    )
    assert read.graph.topological_order() == ["a", "b", "c", "d"]


# ---------- field validation ----------


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("axis", ["x", "y"])
def test_position_must_be_finite(axis, value):
    with pytest.raises(ValidationError):
        Position(**{axis: value})


def test_position_accepts_negative_and_fractional():
    p = Position(x=-12.5, y=3.25)
    assert (p.x, p.y) == (-12.5, 3.25)


@pytest.mark.parametrize("bad_id", [" a", "a ", "\ta", " "])
def test_node_id_surrounding_whitespace_rejected(bad_id):
    with pytest.raises(ValidationError):
        Node(id=bad_id)


@pytest.mark.parametrize("bad_id", [" e", "e ", " "])
def test_edge_id_surrounding_whitespace_rejected(bad_id):
    with pytest.raises(ValidationError):
        Edge(id=bad_id, source="a", target="b")


def test_ids_with_inner_whitespace_allowed():
    assert Node(id="node 1").id == "node 1"


def test_chain_name_is_trimmed():
    assert ChainCreate(name="  My chain  ").name == "My chain"


@pytest.mark.parametrize("name", ["", "   ", "x" * (NAME_MAX_LENGTH + 1)])
def test_chain_name_invalid_rejected(name):
    with pytest.raises(ValidationError):
        ChainCreate(name=name)


def test_chain_name_at_max_length_accepted():
    assert len(ChainCreate(name="x" * NAME_MAX_LENGTH).name) == NAME_MAX_LENGTH


@pytest.mark.parametrize(
    "build",
    [
        lambda: Position(x=1, z=2),
        lambda: Node(id="a", selected=True),
        lambda: Node(id="a", settings={"temp": 0.5}),
        lambda: Edge(id="e", sourceId="a", source="a", target="b"),
        lambda: ChainGraph(nodes=[], edges=[], viewport={}),
        lambda: ChainCreate(name="c", owner="me"),
    ],
    ids=["position", "node", "node.settings", "edge", "graph", "chain_create"],
)
def test_unknown_fields_rejected(build):
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        build()


def test_invalid_node_settings_rejected_inside_graph():
    with pytest.raises(ValidationError):
        ChainGraph(nodes=[{"id": "a", "settings": {"temperature": 5}}])
