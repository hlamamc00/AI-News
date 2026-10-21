"""Regions, categories and the keyword hints used by the template writer."""

from __future__ import annotations

REGIONS: list[str] = ["global", "africa", "americas", "asia", "europe", "middle-east", "oceania"]
REGION_LABELS: dict[str, str] = {
    "global": "World",
    "africa": "Africa",
    "americas": "Americas",
    "asia": "Asia",
    "europe": "Europe",
    "middle-east": "Middle East",
    "oceania": "Oceania",
}

CATEGORIES: list[str] = [
    "world",
    "politics",
    "business",
    "technology",
    "science",
    "health",
    "environment",
    "sport",
    "culture",
]
CATEGORY_LABELS: dict[str, str] = {
    "world": "World",
    "politics": "Politics",
    "business": "Business",
    "technology": "Technology",
    "science": "Science",
    "health": "Health",
    "environment": "Environment",
    "sport": "Sport",
    "culture": "Culture",
}

# Lower-case place names that strongly suggest a region. Used only by the
# template writer and as a tie-breaker; the LLM writer classifies on its own.
REGION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "africa": (
        "africa", "african", "nigeria", "lagos", "abuja", "kenya", "nairobi", "ethiopia", "addis",
        "south africa", "johannesburg", "cape town", "pretoria", "ghana", "accra", "egypt", "cairo",
        "sudan", "khartoum", "somalia", "mogadishu", "congo", "kinshasa", "uganda", "kampala",
        "tanzania", "rwanda", "kigali", "zimbabwe", "harare", "zambia", "mozambique", "angola",
        "senegal", "dakar", "mali", "bamako", "niger", "burkina", "sahel", "ivory coast",
        "côte d'ivoire", "cameroon", "morocco", "rabat", "algeria", "algiers", "tunisia", "tunis",
        "libya", "tripoli", "eritrea", "djibouti", "malawi", "botswana", "namibia", "madagascar",
        "sierra leone", "liberia", "guinea", "chad", "gabon", "togo", "benin", "mauritius",
    ),
    "americas": (
        "america", "american", "united states", "u.s.", "us ", "washington", "white house",
        "congress", "senate", "new york", "california", "texas", "florida", "chicago", "pentagon",
        "canada", "canadian", "ottawa", "toronto", "quebec", "mexico", "mexican", "brazil",
        "brazilian", "brasília", "rio de janeiro", "são paulo", "argentina", "argentine",
        "buenos aires", "chile", "chilean", "santiago", "colombia", "colombian", "bogotá",
        "peru", "peruvian", "lima", "venezuela", "venezuelan", "caracas", "cuba", "cuban",
        "havana", "haiti", "jamaica", "caribbean", "ecuador", "quito", "bolivia", "la paz",
        "uruguay", "paraguay", "guatemala", "honduras", "el salvador", "nicaragua", "costa rica",
        "panama", "dominican", "puerto rico", "latin america", "latin american", "trump",
        "biden", "harris", "supreme court", "fbi", "nasa",
    ),
    "asia": (
        "asia", "asian", "china", "chinese", "beijing", "shanghai", "hong kong", "taiwan",
        "taipei", "japan", "japanese", "tokyo", "korea", "korean", "seoul", "pyongyang",
        "india", "indian", "delhi", "mumbai", "bengaluru", "modi", "pakistan", "pakistani",
        "islamabad", "karachi", "bangladesh", "dhaka", "sri lanka", "colombo", "nepal",
        "kathmandu", "afghanistan", "kabul", "taliban", "myanmar", "thailand", "thai", "bangkok",
        "vietnam", "vietnamese", "hanoi", "cambodia", "laos", "malaysia", "malaysian",
        "kuala lumpur", "singapore", "indonesia", "indonesian", "jakarta", "philippines",
        "philippine", "manila", "kazakhstan", "uzbekistan", "kyrgyzstan", "tajikistan",
        "mongolia", "bhutan", "maldives", "xinjiang", "tibet", "asean",
    ),
    "europe": (
        "europe", "european", "eu ", "brussels", "britain", "british", "uk ", "london",
        "england", "scotland", "wales", "northern ireland", "ireland", "irish", "dublin",
        "france", "french", "paris", "macron", "germany", "german", "berlin", "italy", "italian",
        "rome", "spain", "spanish", "madrid", "portugal", "lisbon", "netherlands", "dutch",
        "amsterdam", "belgium", "belgian", "switzerland", "swiss", "austria", "vienna", "poland",
        "polish", "warsaw", "ukraine", "ukrainian", "kyiv", "zelensky", "russia", "russian",
        "moscow", "kremlin", "putin", "belarus", "sweden", "swedish", "stockholm", "norway",
        "norwegian", "oslo", "denmark", "danish", "copenhagen", "finland", "finnish", "helsinki",
        "greece", "greek", "athens", "turkey", "turkish", "ankara", "istanbul", "hungary",
        "budapest", "czech", "prague", "slovakia", "romania", "bucharest", "bulgaria", "serbia",
        "belgrade", "croatia", "bosnia", "kosovo", "albania", "moldova", "georgia", "armenia",
        "azerbaijan", "baltic", "estonia", "latvia", "lithuania", "nato", "downing street",
        "westminster", "starmer",
    ),
    "middle-east": (
        "middle east", "israel", "israeli", "jerusalem", "tel aviv", "netanyahu", "gaza",
        "palestinian", "palestine", "west bank", "hamas", "hezbollah", "lebanon", "lebanese",
        "beirut", "syria", "syrian", "damascus", "iraq", "iraqi", "baghdad", "iran", "iranian",
        "tehran", "saudi", "riyadh", "yemen", "houthi", "sanaa", "jordan", "amman", "qatar",
        "doha", "uae", "emirates", "dubai", "abu dhabi", "kuwait", "bahrain", "oman", "gulf",
        "kurdish", "kurds", "red sea",
    ),
    "oceania": (
        "australia", "australian", "sydney", "melbourne", "canberra", "brisbane", "perth",
        "queensland", "new south wales", "victoria", "tasmania", "new zealand", "zealand",
        "auckland", "wellington", "pacific islands", "fiji", "samoa", "tonga", "papua new guinea",
        "solomon islands", "vanuatu", "kiribati", "micronesia", "guam", "polynesia",
    ),
}

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "business": (
        "stocks", "shares", "markets", "economy", "economic", "inflation", "interest rate",
        "central bank", "fed ", "federal reserve", "earnings", "profit", "revenue", "merger",
        "acquisition", "ipo", "investors", "tariff", "tariffs", "gdp", "oil price",
        "crypto", "bitcoin", "ceo", "startup", "layoffs", "shareholders",
    ),
    "technology": (
        "ai ", "artificial intelligence", "chatbot", "software", "apple", "google",
        "microsoft", "meta ", "amazon", "openai", "nvidia", "semiconductor", "smartphone",
        "iphone", "android", "cyber", "hack", "hackers", "data breach", "robot", "tesla", "spacex",
        "social media", "tiktok", "algorithm", "cloud computing", "quantum",
    ),
    "science": (
        "scientists", "researchers", "study finds", "telescope", "nasa", "esa", "asteroid",
        "space station", "rocket launch", "fossil", "dinosaur", "physics", "genome", "dna",
        "archaeolog", "astronom", "mars", "moon landing", "black hole", "particle",
    ),
    "health": (
        "health", "hospital", "doctors", "nurses", "vaccine", "virus", "outbreak", "pandemic",
        "disease", "cancer", "who ", "world health", "nhs", "mental health", "obesity",
        "malaria", "cholera", "measles", "ebola", "mpox", "patients",
    ),
    "environment": (
        "climate", "emissions", "carbon", "wildfire", "wildfires", "flood", "floods", "flooding",
        "drought", "heatwave", "hurricane", "typhoon", "cyclone", "earthquake", "pollution",
        "biodiversity", "deforestation", "renewable", "solar", "wind farm", "conservation",
        "wildlife", "glacier", "coral", "cop30", "cop31", "environment",
    ),
    "sport": (
        "football", "soccer", "premier league", "champions league", "europa league", "world cup",
        "fifa", "uefa", "la liga", "serie a", "bundesliga", "ligue 1", "midfielder", "striker",
        "goalkeeper", "defender", "penalty", "half-time", "first half", "second half", "stoppage time",
        "matchday", "fixture", "fixtures", "points table", "league table", "transfer window",
        "cricket", "test match", "rugby", "tennis", "wimbledon", "grand slam", "golf", "olympic",
        "olympics", "nba", "nfl", "mlb", "nhl", "formula 1", "f1 ", "grand prix", "athletics",
        "marathon", "boxing", "ufc", "cycling", "tour de france", "manager",
        "striker", "wicket", "innings", "medal",
    ),
    "culture": (
        "film", "movie", "box office", "oscar", "oscars", "emmy", "grammy", "album", "singer",
        "concert", "festival", "netflix", "hbo", "tv show",
        "actor", "actress", "director", "novel", "museum", "gallery",
        "exhibition", "theatre", "theater", "broadway", "fashion", "celebrity", "hollywood",
        "bollywood", "k-pop", "anime", "streaming", "premiere",
    ),
    "politics": (
        "election", "elections", "vote", "voters", "parliament", "prime minister",
        "coalition", "opposition", "cabinet", "senate", "congress",
        "legislation", "referendum", "campaign", "coup", "sanctions",
        "diplomat", "summit", "treaty", "lawmakers",
    ),
}


def _scores(text: str, table: dict[str, tuple[str, ...]]) -> dict[str, int]:
    lowered = f" {text.lower()} "
    scores: dict[str, int] = {}
    for key, words in table.items():
        hits = 0
        for w in words:
            # Short tokens are word-anchored to avoid "us" matching "bus".
            needle = f" {w}" if len(w) <= 4 and not w.endswith(" ") else w
            hits += lowered.count(needle)
        if hits:
            scores[key] = hits
    return scores


def region_scores(text: str) -> dict[str, int]:
    """Keyword hit counts per region, highest first."""
    return dict(sorted(_scores(text, REGION_KEYWORDS).items(), key=lambda kv: -kv[1]))


def category_scores(text: str) -> dict[str, int]:
    return dict(sorted(_scores(text, CATEGORY_KEYWORDS).items(), key=lambda kv: -kv[1]))


def guess_region(text: str, default: str = "global", min_hits: int = 2) -> str:
    """The region with the most keyword hits, if it has at least *min_hits*."""
    scores = region_scores(text)
    if not scores:
        return default
    best, hits = next(iter(scores.items()))
    return best if hits >= min_hits else default


def guess_category(text: str, default: str = "world", min_hits: int = 3) -> str:
    """The category with the most keyword hits, if the evidence is strong enough."""
    scores = category_scores(text)
    if not scores:
        return default
    best, hits = next(iter(scores.items()))
    return best if hits >= min_hits else default
