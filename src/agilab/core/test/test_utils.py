from agi_node.utils import MutableNamespace


def test_mutable_namespace_supports_item_access():
    ns = MutableNamespace()

    ns["alpha"] = 1
    assert ns.alpha == 1
    assert ns["alpha"] == 1
