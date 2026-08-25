import pytest

from media_bridge.contracts_v2 import HopMetadata
from media_bridge_gateway.hops import HopGuardError, advance_hop


def test_revisited_gateway_is_blocked() -> None:
    hop = HopMetadata(hop_id="request", visited_gateways=["eoul"], max_hops=3)
    with pytest.raises(HopGuardError, match="loop"):
        advance_hop(hop, gateway_id="eoul")


def test_max_hops_is_blocked() -> None:
    hop = HopMetadata(hop_id="request", visited_gateways=["one", "two"], max_hops=2)
    with pytest.raises(HopGuardError, match="limit"):
        advance_hop(hop, gateway_id="three")


def test_new_gateway_is_added_once() -> None:
    hop = advance_hop(HopMetadata(hop_id="request", max_hops=2), gateway_id="eoul")
    assert hop.visited_gateways == ["eoul"]
