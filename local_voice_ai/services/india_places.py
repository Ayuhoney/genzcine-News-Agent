"""India states, UTs, and cities for voice matching — no network calls.

Fetch stays one place per request. This file only names places so STT
correction and headline matching work for any state or city, not just Punjab.
"""
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

# Major cities + district HQs by state/UT. One spoken place → one news query.
CITIES_BY_STATE: dict[str, tuple[str, ...]] = {
    "Andhra Pradesh": (
        "Amaravati", "Visakhapatnam", "Vijayawada", "Guntur", "Nellore", "Kurnool",
        "Tirupati", "Rajahmundry", "Kakinada", "Kadapa", "Anantapur", "Eluru",
        "Ongole", "Chittoor", "Srikakulam", "Vizianagaram",
    ),
    "Arunachal Pradesh": (
        "Itanagar", "Naharlagun", "Tawang", "Pasighat", "Ziro", "Bomdila",
    ),
    "Assam": (
        "Dispur", "Guwahati", "Dibrugarh", "Silchar", "Jorhat", "Nagaon",
        "Tinsukia", "Tezpur", "Bongaigaon", "Diphu",
    ),
    "Bihar": (
        "Patna", "Gaya", "Bhagalpur", "Muzaffarpur", "Darbhanga", "Purnia",
        "Bihar Sharif", "Arrah", "Begusarai", "Katihar", "Munger", "Chhapra",
        "Sasaram", "Hajipur", "Motihari", "Samastipur", "Bettiah", "Saharsa",
        "Siwan",
    ),
    "Chhattisgarh": (
        "Raipur", "Bilaspur", "Durg", "Bhilai", "Korba", "Raigarh",
        "Jagdalpur", "Ambikapur", "Dhamtari", "Rajnandgaon",
    ),
    "Goa": (
        "Panaji", "Margao", "Vasco da Gama", "Mapusa", "Ponda",
    ),
    "Gujarat": (
        "Gandhinagar", "Ahmedabad", "Surat", "Vadodara", "Rajkot", "Bhavnagar",
        "Jamnagar", "Junagadh", "Gandhidham", "Anand", "Nadiad", "Morbi",
        "Mehsana", "Bharuch", "Vapi", "Navsari", "Porbandar", "Godhra", "Palanpur",
    ),
    "Haryana": (
        "Gurugram", "Faridabad", "Panipat", "Ambala", "Hisar", "Karnal",
        "Rohtak", "Yamunanagar", "Panchkula", "Sonipat", "Sirsa", "Bhiwani",
        "Rewari", "Bahadurgarh", "Jind", "Kaithal", "Palwal",
    ),
    "Himachal Pradesh": (
        "Shimla", "Dharamshala", "Solan", "Mandi", "Kullu", "Manali",
        "Hamirpur", "Una", "Chamba", "Kangra", "Nahan",
    ),
    "Jharkhand": (
        "Ranchi", "Jamshedpur", "Dhanbad", "Bokaro", "Deoghar", "Hazaribagh",
        "Giridih", "Ramgarh", "Medininagar",
    ),
    "Karnataka": (
        "Bengaluru", "Mysuru", "Mangaluru", "Hubballi", "Belagavi", "Kalaburagi",
        "Ballari", "Davangere", "Vijayapura", "Shivamogga", "Tumakuru", "Raichur",
        "Bidar", "Hassan", "Udupi", "Mandya", "Chitradurga", "Kolar",
    ),
    "Kerala": (
        "Thiruvananthapuram", "Kochi", "Kozhikode", "Thrissur", "Kollam",
        "Kannur", "Alappuzha", "Palakkad", "Kottayam", "Malappuram", "Kasaragod",
        "Pathanamthitta",
    ),
    "Madhya Pradesh": (
        "Bhopal", "Indore", "Gwalior", "Jabalpur", "Ujjain", "Sagar", "Dewas",
        "Satna", "Ratlam", "Rewa", "Katni", "Singrauli", "Burhanpur", "Khandwa",
        "Chhindwara", "Guna",
    ),
    "Maharashtra": (
        "Mumbai", "Pune", "Nagpur", "Nashik", "Thane", "Chhatrapati Sambhajinagar",
        "Solapur", "Amravati", "Kolhapur", "Navi Mumbai", "Kalyan", "Nanded",
        "Sangli", "Jalgaon", "Akola", "Latur", "Ahmednagar", "Chandrapur",
        "Parbhani", "Jalna",
    ),
    "Manipur": (
        "Imphal", "Thoubal", "Bishnupur", "Churachandpur", "Ukhrul",
    ),
    "Meghalaya": (
        "Shillong", "Tura", "Jowai", "Nongpoh",
    ),
    "Mizoram": (
        "Aizawl", "Lunglei", "Champhai", "Kolasib",
    ),
    "Nagaland": (
        "Kohima", "Dimapur", "Mokokchung", "Tuensang", "Wokha",
    ),
    "Odisha": (
        "Bhubaneswar", "Cuttack", "Rourkela", "Berhampur", "Sambalpur", "Puri",
        "Balasore", "Bhadrak", "Baripada", "Jharsuguda", "Angul",
    ),
    "Punjab": (
        "Ludhiana", "Amritsar", "Jalandhar", "Patiala", "Bathinda", "Mohali",
        "Firozpur", "Pathankot", "Moga", "Hoshiarpur", "Gurdaspur",
        "Faridkot", "Muktsar", "Kapurthala", "Rupnagar", "Sangrur", "Barnala",
        "Fatehgarh Sahib", "Tarn Taran", "Fazilka", "Abohar", "Khanna",
        "Phagwara", "Rajpura", "Batala", "Malerkotla",
    ),
    "Rajasthan": (
        "Jaipur", "Jodhpur", "Kota", "Bikaner", "Ajmer", "Udaipur", "Bhilwara",
        "Alwar", "Sikar", "Sri Ganganagar", "Pali", "Tonk", "Hanumangarh",
        "Chittorgarh", "Bharatpur", "Jaisalmer", "Bundi", "Jhunjhunu", "Beawar",
        "Kishangarh",
    ),
    "Sikkim": (
        "Gangtok", "Namchi", "Gyalshing", "Mangan",
    ),
    "Tamil Nadu": (
        "Chennai", "Coimbatore", "Madurai", "Tiruchirappalli", "Salem",
        "Tirunelveli", "Erode", "Vellore", "Thoothukudi", "Dindigul",
        "Thanjavur", "Nagercoil", "Kanchipuram", "Cuddalore", "Karur",
        "Sivakasi", "Hosur", "Kumbakonam", "Ooty",
    ),
    "Telangana": (
        "Hyderabad", "Warangal", "Nizamabad", "Karimnagar", "Khammam",
        "Ramagundam", "Mahbubnagar", "Nalgonda", "Adilabad", "Siddipet", "Suryapet",
    ),
    "Tripura": (
        "Agartala", "Dharmanagar", "Kailashahar",
    ),
    "Uttar Pradesh": (
        "Lucknow", "Kanpur", "Agra", "Varanasi", "Prayagraj", "Meerut",
        "Ghaziabad", "Noida", "Bareilly", "Aligarh", "Moradabad", "Saharanpur",
        "Gorakhpur", "Firozabad", "Jhansi", "Muzaffarnagar", "Mathura", "Ayodhya",
        "Shahjahanpur", "Rampur", "Hapur", "Etawah", "Mirzapur", "Bulandshahr",
        "Sambhal", "Amroha", "Hardoi", "Fatehpur", "Raebareli", "Sitapur",
        "Bahraich", "Unnao", "Jaunpur", "Azamgarh",
    ),
    "Uttarakhand": (
        "Dehradun", "Haridwar", "Haldwani", "Roorkee", "Rudrapur", "Kashipur",
        "Rishikesh", "Nainital", "Mussoorie", "Almora", "Pithoragarh",
    ),
    "West Bengal": (
        "Kolkata", "Howrah", "Durgapur", "Asansol", "Siliguri", "Bardhaman",
        "Malda", "Kharagpur", "Haldia", "Darjeeling", "Jalpaiguri",
        "Cooch Behar", "Krishnanagar",
    ),
    "Andaman and Nicobar Islands": ("Port Blair",),
    "Chandigarh": ("Chandigarh",),
    "Dadra and Nagar Haveli and Daman and Diu": ("Silvassa", "Daman", "Diu"),
    "Delhi": ("New Delhi", "Delhi"),
    "Jammu and Kashmir": (
        "Srinagar", "Jammu", "Anantnag", "Baramulla", "Udhampur", "Kathua",
        "Sopore", "Pulwama", "Rajouri", "Poonch",
    ),
    "Ladakh": ("Leh", "Kargil"),
    "Lakshadweep": ("Kavaratti",),
    "Puducherry": ("Puducherry", "Karaikal", "Mahe", "Yanam"),
}

IN_CITIES: tuple[str, ...] = tuple(
    dict.fromkeys(city for cities in CITIES_BY_STATE.values() for city in cities)
)

_NATIONAL_KEYS = frozenset(
    {
        "india",
        "all india",
        "whole india",
        "entire india",
        "national",
        "nationwide",
        "all states",
        "every state",
        "all cities",
        "country",
        "pan india",
    }
)

# Dual spellings / old names. Do not add short tokens like "up" or "mp".
_EXTRA_ALIASES: dict[str, tuple[str, ...]] = {
    "firozpur": ("ferozepur", "ferozpore", "ferozpur", "frostburt", "frostburg", "frostburn"),
    "ferozepur": ("firozpur", "ferozpore", "ferozpur"),
    "mohali": ("sas nagar", "s.a.s. nagar", "sahibzada ajit singh nagar", "mohaly", "mohalli"),
    "chandigarh": (
        "tricity", "chandigrah", "chandigar", "chandigargh", "chandigarr",
        "chaldea girl", "chaldea", "chandi garh", "chander garh",
    ),
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
    "jammu and kashmir": ("kashmir",),
    "west bengal": ("bengal",),
    "hubballi": ("hubli", "hubballi dharwad"),
    "belagavi": ("belgaum",),
    "kalaburagi": ("gulbarga",),
    "vijayapura": ("bijapur",),
    "shivamogga": ("shimoga",),
    "tiruchirappalli": ("trichy", "tiruchi"),
    "thoothukudi": ("tuticorin",),
    "kozhikode": ("calicut",),
    "kollam": ("quilon",),
    "alappuzha": ("alleppey",),
    "palakkad": ("palghat",),
    "kannur": ("cannanore",),
    "thrissur": ("trichur",),
    "chhatrapati sambhajinagar": ("aurangabad", "sambhajinagar"),
    "ayodhya": ("faizabad",),
    "visakhapatnam": ("vizag", "vishakhapatnam"),
    "vijayawada": ("bezawada",),
    "panaji": ("panjim",),
    "margao": ("madgaon",),
    "jamshedpur": ("tatanagar",),
    "berhampur": ("brahmapur",),
    "balasore": ("baleshwar",),
    "sri ganganagar": ("ganganagar",),
    "ooty": ("udhagamandalam",),
    "andaman and nicobar islands": ("andaman", "andaman and nicobar", "port blair"),
    "dadra and nagar haveli and daman and diu": ("daman and diu", "dadra and nagar haveli"),
    "noida": ("gautam buddha nagar",),
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

_DISPLAY: dict[str, str] = {}
for _name in all_place_names():
    _DISPLAY[_name.lower()] = _name
    for _alias in PLACE_ALIASES.get(_name.lower(), ()):
        _DISPLAY.setdefault(_alias, _name)
for _key, _extras in _EXTRA_ALIASES.items():
    _canon = _DISPLAY.get(_key, _key.title())
    _DISPLAY.setdefault(_key, _canon)
    for _alias in _extras:
        _DISPLAY.setdefault(_alias, _canon)

def aliases_for(query: str) -> tuple[str, ...]:
    key = query.strip().lower()
    if not key:
        return ()
    return PLACE_ALIASES.get(key, (key,))


def is_national_query(query: str) -> bool:
    return " ".join(query.lower().split()) in _NATIONAL_KEYS


def canonical_place(query: str) -> str | None:
    key = " ".join(query.lower().split())
    if not key:
        return None
    if is_national_query(key):
        return "national"
    return _DISPLAY.get(key)


def extract_place(text: str) -> str | None:
    """Pull a known city/state out of a longer LLM topic like 'news from Firozpur city'."""
    key = " ".join((text or "").lower().split())
    if not key:
        return None
    if is_national_query(key):
        return "national"
    exact = _DISPLAY.get(key)
    if exact:
        return exact
    hits: list[str] = []
    for alias, display in _DISPLAY.items():
        if len(alias) < 4:
            continue
        if alias in key:
            hits.append(display)
    if not hits:
        return None
    return max(hits, key=len)


def news_query_for(place: str | None) -> str | None:
    """One search term per request. National → None (India bulletin, no city loop)."""
    if not place or not place.strip():
        return None
    if is_national_query(place):
        return None
    found = extract_place(place)
    if found == "national":
        return None
    return found or place.strip() or None
