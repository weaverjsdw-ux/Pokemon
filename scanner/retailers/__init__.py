from .base import Retailer, Store, StockResult
from .target import Target
from .walmart import Walmart
from .pokemoncenter import PokemonCenter
from .gamestop import GameStop
from .bestbuy import BestBuy
from .costco import Costco
from .samsclub import SamsClub

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
