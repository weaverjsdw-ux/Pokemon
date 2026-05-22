from .base import Retailer, Store, StockResult
from .amazon import Amazon
from .barnesnoble import BarnesNoble
from .bestbuy import BestBuy
from .costco import Costco
from .fivebelow import FiveBelow
from .gamestop import GameStop
from .lgs_crystalcommerce import LGSCrystalCommerce
from .lgs_shopify import LGSShopify
from .meijer import Meijer
from .pokemoncenter import PokemonCenter
from .samsclub import SamsClub
from .target import Target
from .tcgplayer import TCGPlayer
from .walmart import Walmart

ALL = {
    "target": Target,
    "walmart": Walmart,
    "bestbuy": BestBuy,
    "pokemoncenter": PokemonCenter,
    "gamestop": GameStop,
    "costco": Costco,
    "samsclub": SamsClub,
    "amazon": Amazon,
    "tcgplayer": TCGPlayer,
    "barnesnoble": BarnesNoble,
    "meijer": Meijer,
    "fivebelow": FiveBelow,
    "lgs_shopify": LGSShopify,
    "lgs_crystalcommerce": LGSCrystalCommerce,
}

__all__ = ["Retailer", "Store", "StockResult", "ALL"]
