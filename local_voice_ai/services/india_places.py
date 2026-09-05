"""India states, UTs, and major cities for voice matching — no network calls."""
from __future__ import annotations

IN_STATES: tuple[str, ...] = (
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chhattisgarh",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
)

IN_UTS: tuple[str, ...] = (
    "Andaman and Nicobar Islands",
    "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi",
    "Jammu and Kashmir",
    "Ladakh",
    "Lakshadweep",
    "Puducherry",
)

IN_CITIES: tuple[str, ...] = (
    "Amaravati",
    "Itanagar",
    "Dispur",
    "Guwahati",
    "Patna",
    "Raipur",
    "Panaji",
    "Gandhinagar",
    "Ahmedabad",
    "Shimla",
    "Ranchi",
    "Bengaluru",
    "Thiruvananthapuram",
    "Bhopal",
    "Mumbai",
    "Imphal",
    "Shillong",
    "Aizawl",
    "Kohima",
    "Bhubaneswar",
    "Jaipur",
    "Gangtok",
    "Chennai",
    "Hyderabad",
    "Agartala",
    "Lucknow",
    "Dehradun",
    "Kolkata",
    "New Delhi",
    "Srinagar",
    "Jammu",
    "Leh",
    "Pune",
    "Nagpur",
    "Nashik",
    "Surat",
    "Vadodara",
    "Rajkot",
    "Indore",
    "Gwalior",
    "Kanpur",
    "Agra",
    "Varanasi",
    "Prayagraj",
    "Noida",
    "Ghaziabad",
    "Gurugram",
    "Faridabad",
    "Coimbatore",
    "Madurai",
    "Kochi",
    "Kozhikode",
    "Visakhapatnam",
    "Vijayawada",
    "Warangal",
    "Mysuru",
    "Mangaluru",
    "Jodhpur",
    "Udaipur",
    "Kota",
    "Ludhiana",
    "Amritsar",
    "Jalandhar",
    "Patiala",
    "Bathinda",
    "Mohali",
    "Firozpur",
    "Ferozepur",
    "Pathankot",
    "Moga",
    "Hoshiarpur",
    "Gurdaspur",
    "Faridkot",
    "Muktsar",
    "Kapurthala",
    "Rupnagar",
)

# Dual spellings / old names. Do not add short tokens like "up" or "mp".
_EXTRA_ALIASES: dict[str, tuple[str, ...]] = {
    "firozpur": ("ferozepur", "ferozpore", "ferozpur"),
    "ferozepur": ("firozpur", "ferozpore", "ferozpur"),
    "mohali": ("sas nagar", "s.a.s. nagar", "sahibzada ajit singh nagar"),
    "chandigarh": ("tricity",),
    "bengaluru": ("bangalore",),
    "bangalore": ("bengaluru",),
    "gurugram": ("gurgaon",),
    "gurgaon": ("gurugram",),
    "mumbai": ("bombay",),
    "kolkata": ("calcutta",),
    "chennai": ("madras",),
    "odisha": ("orissa",),
    "orissa": ("odisha",),
    "puducherry": ("pondicherry",),
    "pondicherry": ("puducherry",),
    "thiruvananthapuram": ("trivandrum",),
    "trivandrum": ("thiruvananthapuram",),
    "prayagraj": ("allahabad",),
    "allahabad": ("prayagraj",),
    "varanasi": ("banaras", "benaras"),
    "kochi": ("cochin",),
    "mysuru": ("mysore",),
    "mangaluru": ("mangalore",),
    "vadodara": ("baroda",),
    "delhi": ("new delhi", "ncr"),
    "new delhi": ("delhi", "ncr"),
    "uttarakhand": ("uttaranchal",),
    "tamil nadu": ("tamilnadu",),
    "andhra pradesh": ("andhra",),
    "arunachal pradesh": ("arunachal",),
    "himachal pradesh": ("himachal",),
    "jammu and kashmir": ("jammu", "kashmir"),
    "west bengal": ("bengal",),
}


def all_place_names() -> tuple[str, ...]:
    seen: set[str] = set()
    names: list[str] = []
    for name in (*IN_STATES, *IN_UTS, *IN_CITIES):
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return tuple(names)


def _build_alias_table() -> dict[str, tuple[str, ...]]:
    table: dict[str, tuple[str, ...]] = {}
    for name in all_place_names():
        key = name.lower()
        extras = _EXTRA_ALIASES.get(key, ())
        table[key] = tuple(dict.fromkeys((key, *extras)))
    for key, extras in _EXTRA_ALIASES.items():
        grouped = tuple(dict.fromkeys((key, *extras, *table.get(key, ()))))
        table[key] = grouped
        for alias in extras:
            table[alias] = grouped
    return table


PLACE_ALIASES = _build_alias_table()


def aliases_for(query: str) -> tuple[str, ...]:
    key = query.strip().lower()
    if not key:
        return ()
    return PLACE_ALIASES.get(key, (key,))
