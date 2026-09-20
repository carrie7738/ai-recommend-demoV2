"""Conservative local guards for explicit procurement constraints."""
import math
import re


class RequestClarificationError(ValueError):
    """A stated constraint cannot safely be interpreted by the local parser."""


def fallback_budget(request: str) -> float | None:
    text = request.casefold()
    marker = r'(?:\bbudget\b|\bnzd\b|nz\$|\$|预算)'
    unlimited = r'\b(?:no budget(?: limit)?|without (?:a )?budget|budget not specified)\b|不设预算|没有预算限制'
    if re.search(unlimited, text):
        if re.search(marker, re.sub(unlimited, '', text)):
            raise RequestClarificationError('Please clarify whether the budget is limited and specify one amount.')
        return None
    if not re.search(marker, text):
        return None
    matches = list(re.finditer(
        marker + r'\s*(?:(?:is|of|under|up to|within|为|是|不超过|最多)\s*)?'
        r'(?:(?:nzd|nz\$|\$)\s*)?([+-]?\d[\d,]*(?:\.\d+)?)([k千万]?)'
        r'(?:\s*(?:nzd\b|dollars?\b))?'
        r'(?=$|[\s,，。;；!?]|\.(?!\d))', text,
    ))
    # Every budget marker must belong to a parsed amount, including repeated
    # declarations. Do not silently ignore an invalid second constraint.
    remainder = list(text)
    for match in matches:
        remainder[match.start():match.end()] = ' ' * (match.end() - match.start())
    if re.search(marker, ''.join(remainder)):
        raise RequestClarificationError('Please specify one clear budget amount, for example NZD 1,000.')
    amounts = []
    for match in matches:
        raw, suffix = match.groups()
        # A comma separating the following clause is not a thousands separator.
        raw = raw.rstrip(',')
        if not re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?', raw):
            raise RequestClarificationError('Please provide a valid non-negative budget, for example NZD 1,000.')
        amount = float(raw.replace(',', '')) * {'': 1, 'k': 1000, '千': 1000, '万': 10000}[suffix]
        if not math.isfinite(amount):
            raise RequestClarificationError('Please provide a finite budget.')
        amounts.append(amount)
    if not amounts or len(set(amounts)) != 1:
        raise RequestClarificationError('Please specify one clear budget amount, for example NZD 1,000.')
    return amounts[0]


def product_is_excluded(request: str, reference: str) -> bool:
    """Recognize explicit negative clauses; a later positive clause ends scope."""
    if not reference:
        return False
    text = request.casefold()
    pattern = r'(?<![a-z0-9])' + re.escape(reference.casefold()) + r'(?![a-z0-9])'
    for mention in re.finditer(pattern, text):
        prefix = text[:mention.start()]
        clause = re.split(r'[.;!?。；！？\n]|\bbut\b|但是|但|改为', prefix)[-1]
        negative = list(re.finditer(r"\b(?:do not|don't|dont|avoid|exclude|without|no)\b|不要|不采购|不购买|排除", clause))
        if not negative:
            continue
        tail = clause[negative[-1].end():]
        if re.match(r'\s*(?:budget|spending limit|stockouts?)\b', tail):
            continue
        # Lists stay negative; a fresh instruction such as ', buy ...' does not.
        if re.search(r'(?:,|\band\b|，|并且|同时)\s*(?:please\s+)?(?:buy|purchase|add|include|采购|购买|买)', tail):
            continue
        return True
    return False


def catalog_exclusions(request, products):
    return [str(row['ProductId']).strip().upper() for _, row in products.iterrows()
            if product_is_excluded(request, str(row['ProductId']))
            or product_is_excluded(request, str(row.get('ProductName') or ''))]
