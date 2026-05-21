from .base import Retailer, Store, StockResult
from .bestbuy import BestBuy
from .target import Target
from .walmart import Walmart
from .pokemoncenter import PokemonCenter
from .gamestop import GameStop

ALL = {
    "target": Target,
    "walmart": Walmart,
    "bestbuy": BestBuy,
    "pokemoncenter": PokemonCenter,
    "gamestop": GameStop,
}

__all__ = ["Retailer", "Store", "StockResult", "ALL"]
