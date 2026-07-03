from .base import DiscoverySource, StubSource
from .ebay_browse import EbayBrowse
from .slickdeals import Slickdeals
from .target_search import TargetSearch
from .trackalacker import TrackaLacker

ALL = {
    "target_search": TargetSearch,
    "slickdeals": Slickdeals,
    "ebay_browse": EbayBrowse,
    "trackalacker": TrackaLacker,
}

__all__ = ["DiscoverySource", "StubSource", "ALL"]
