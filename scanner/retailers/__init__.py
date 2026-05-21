from .base import Retailer, Store, StockResult
from .bestbuy import BestBuy
from .costco import Costco
from .gamestop import GameStop
from .pokemoncenter import PokemonCenter
from .samsclub import SamsClub
from .target import Target
from .walmart import Walmart

ALL = {
    "target": Target,
    "walmart": Walmart,
    "bestbuy": BestBuy,
    "pokemoncenter": PokemonCenter,
    "gamestop": GameStop,
    "costco": Costco,
    "samsclub": SamsClub,
}

__all__ = ["Retailer", "Store", "StockResult", "ALL"]
