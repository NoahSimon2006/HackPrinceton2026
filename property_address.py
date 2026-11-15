"""Shared formatting of CoStar's structured addresses and optional display text."""
import re


def display_text(value, fallback='', limit=240):
    if not isinstance(value, str):
        return fallback
    clean = ' '.join(re.sub(r'[\x00-\x1f\x7f]', ' ', value).split())
    return clean[:limit] or fallback


def format_property_address(address):
    """Preserve explicit number ranges and suffix directions; never fuzzy-match."""
    def part(key):
        value = address.get(key)
        return ' '.join(str(value).split()) if value is not None else ''
    number, end = part('streetNumber'), part('streetNumberEndRange')
    if number and end and end != number:
        number += '-' + end
    return ' '.join(value for value in (number, part('streetDirection'), part('streetName'),
                                        part('streetType'), part('streetSuffix')) if value)
