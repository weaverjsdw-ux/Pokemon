"""Private sealed price API (Track A) + ledger-backed history/momentum (Track B).

A read-first, local, PokemonPriceTracker-class API over our own comp + evidence
layers. Structurally PPT-free: no endpoint here ever calls PokemonPriceTracker.
Sealed-first; singles/graded (Phase D) and the paper-trade/outcome loop (Phase C)
build on these modules without reshaping them.
"""
