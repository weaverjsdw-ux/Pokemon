"""Homegrown Pokemon price intelligence API (Track A) + ledger-backed
history/momentum (Track B).

A read-first, local price-intelligence API over our own comp + evidence layers.
External price sources are *pluggable adapters*, never the program's identity: no
endpoint here calls any paid external provider on a read path, and a refresh spends
credits only when an external card source is explicitly configured. Any provider-
branded token that remains (e.g. the ``ppt_cards`` source slug, or upstream wire
fields like ``smartMarketPrice`` / ``salesByGrade``) is retained solely as honest
source provenance / adapter wire-format. Sealed-first; singles/graded (Phase D) and
the paper-trade/outcome loop (Phase C) build on these modules without reshaping them.
"""
