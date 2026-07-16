"""Public-weather CLI with proxy-rotating HTTP session.

A small, self-contained tool that pulls forecast data from a public weather
API while staying within per-IP rate limits by cycling through a pool of
proxy servers loaded from a JSON file.
"""
