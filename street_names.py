"""Shared normalization for matching LADOT street names to OSM roads."""
import re


def street_key(name: str | None) -> str:
    text = (name or "").upper()
    text = re.sub(r"\b(\d+)\s*(ST|ND|RD|TH)\b", r"\1", text)
    for pattern, replacement in [(r"\b(NORTH|SOUTH|EAST|WEST|N|S|E|W)\b", ""), (r"\b(AVENUE|AVE|AV)\b", "AV"),
                                 (r"\b(STREET|STR|ST)\b", "ST"), (r"\b(BOULEVARD|BLVD|BL)\b", "BL"),
                                 (r"\b(PLACE|PL)\b", "PL"), (r"\b(DRIVE|DR)\b", "DR"), (r"\b(ROAD|RD)\b", "RD")]:
        text = re.sub(pattern, replacement, text)
    return " ".join(re.findall(r"[A-Z0-9]+", text))
