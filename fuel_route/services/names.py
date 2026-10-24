"""Place-name normalisation shared by the offline gazetteer build and runtime lookups.

Census names ("Oklahoma City city", "Nashville-Davidson metropolitan government
(balance)") and OPIS city names ("Mc Calla", "Saint Johns") must collapse to the
same key so stations and user input can be geocoded without any network call.
"""

import re

US_STATES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}
_STATE_BY_NAME = {name.lower(): code for code, name in US_STATES.items()}

# Legal/statistical descriptors the Census Bureau appends to place names.
_CENSUS_SUFFIX = re.compile(
    r"\s+(city and borough|urban county|city|town|village|borough|cdp|municipality|"
    r"township|plantation|gore|grant|location|purchase|ccd|ut|corporation)$",
    re.IGNORECASE,
)
_CONSOLIDATED = re.compile(
    r"\s*(\(balance\)|(city|town)?\s*(consolidated|metropolitan|unified|metro) government)$",
    re.IGNORECASE,
)


def normalize_state(value: str) -> str | None:
    """Return the two-letter USPS code for a code or full state name, else None."""
    value = value.strip()
    if value.upper() in US_STATES:
        return value.upper()
    return _STATE_BY_NAME.get(value.lower())


def place_key(name: str) -> str:
    """Canonical lookup key: lowercase, abbreviations unified, spaces/punctuation dropped.

    Dropping spaces makes "Mc Calla" == "McCalla" and "De Forest" == "DeForest".
    """
    s = name.strip().lower()
    s = re.sub(r"\bsaint\b|\bst\.", "st", s)
    s = re.sub(r"\bfort\b|\bft\.", "ft", s)
    s = re.sub(r"\bmount\b|\bmt\.", "mt", s)
    return re.sub(r"[^a-z0-9]", "", s)


def census_name_variants(census_name: str) -> set[str]:
    """Names a Census gazetteer entry should be findable by.

    "Nashville-Davidson metropolitan government (balance)" -> {"Nashville-Davidson", "Nashville"}
    """
    name = census_name
    for _ in range(2):
        name = _CONSOLIDATED.sub("", name).strip()
    variants = {name, _CENSUS_SUFFIX.sub("", name)}
    for v in list(variants):
        if "-" in v:
            variants.add(v.split("-", 1)[0])
    return {v for v in variants if v}
