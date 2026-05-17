from __future__ import annotations

import re

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(\(?\d{3}\)?[\s\-\.]?\d{3}[\s\-\.]\d{4})")
ADDR_RE = re.compile(
    r"\d+\s+\w[\w\s]+(?:St|Ave|Rd|Blvd|Dr|Way|Ln|Ct|Street|Avenue|Road|Boulevard|Drive)"
)
JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']+application/ld\+json["\']+[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
OBFUSC_RE = re.compile(r"([\w.+-]+)\s*(?:\[at\]|\(at\)|\bAT\b)\s*([\w.-]+\.[a-z]{2,})", re.I)
FILENAME_RE = re.compile(r"\.(png|jpg|gif|svg|webp|ico|js|css|php)$", re.I)

ROLE_EMAILS = {
    "info",
    "contact",
    "service",
    "office",
    "admin",
    "support",
    "hello",
    "sales",
    "mail",
    "webmaster",
    "team",
    "help",
    "enquiries",
    "enquiry",
}

BAD_EMAIL = {
    "example.",
    "test@",
    "user@",
    "admin@example",
    "info@example",
    "email@email",
    "your@email",
    "yourname@",
    "youremail",
    "name@domain",
    "email@domain",
    "wixpress",
    "sentry",
    "schema",
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "bounce@",
    "postmaster@",
    "mailer-daemon",
    "abuse@",
    "cloudflare",
    "cdn.",
    "static.",
    "assets.",
    "images.",
    "img.",
    "tracking",
    "analytics",
    "pixel",
    "beacon",
    ".png",
    "@2x",
    "@3x",
    ".jpg",
    ".gif",
    ".svg",
    ".webp",
}

BAD_EMAIL_DOMAINS = {
    "cloudflare.com",
    "amazonaws.com",
    "akamai.net",
    "fastly.net",
    "cdnjs.com",
    "jsdelivr.net",
    "unpkg.com",
    "sentry.io",
}

SKIP_DOMAINS = {
    "yelp.com",
    "yellowpages.com",
    "bbb.org",
    "facebook.com",
    "linkedin.com",
    "google.com",
    "mapquest.com",
    "whitepages.com",
    "angi.com",
    "homeadvisor.com",
    "thumbtack.com",
    "angieslist.com",
    "nextdoor.com",
    "duckduckgo.com",
    "buildzoom.com",
    "threebestrated.com",
    "todayshomeowner.com",
    "birdeye.com",
    "houzz.com",
    "cozywise.com",
    "expertise.com",
    "homeguide.com",
    "porch.com",
    "bark.com",
    "myhomequote.com",
    "improvenet.com",
    "networx.com",
    "fixr.com",
    "remodelingcosts.org",
}

SCRAPE_SKIP = {
    "yellowpages.com",
    "yelp.com",
    "google.com",
    "facebook.com",
    "scheduler.netic.ai",
    "servicetitan.com",
    "localsearch.com",
    "rwg_token",
    "netic.ai",
    "buildzoom.com",
    "threebestrated.com",
    "todayshomeowner.com",
    "birdeye.com",
    "houzz.com",
    "cozywise.com",
    "expertise.com",
    "homeguide.com",
    "porch.com",
    "bark.com",
    "myhomequote.com",
    "improvenet.com",
    "networx.com",
    "fixr.com",
    "remodelingcosts.org",
}

OVERPASS_EPS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

TRADE_KW = {
    "HVAC": {
        "osm": ["heating", "hvac", "furnace", "cooling", "air conditioning"],
        "yp": "hvac+contractor",
        "google": "HVAC contractor",
        "yelp": "hvac",
        "yelp_cflt": "hvac",
        "gsearch": [
            "HVAC contractor",
            "heating cooling contractor",
            "furnace AC repair",
        ],
    },
    "Electrical": {
        "osm": ["electrician", "electrical", "electric"],
        "yp": "electrician",
        "google": "electrical contractor",
        "yelp": "electricians",
        "yelp_cflt": "electricians",
        "gsearch": [
            "electrician",
            "electrical contractor",
            "electric repair service",
        ],
    },
    "Excavating": {
        "osm": ["excavating", "earthwork", "grading", "dirt work", "excavation"],
        "yp": "excavating+contractor",
        "google": "excavating grading contractor",
        "yelp": "excavation services",
        "yelp_cflt": "excavation_services",
        "gsearch": [
            "excavating contractor",
            "grading excavation contractor",
            "site work dirt contractor",
        ],
    },
    "Construction Staking": {
        "osm": ["survey", "land survey", "surveyor", "staking"],
        "yp": "construction+staking",
        "google": "construction staking contractor",
        "yelp": "surveyors",
        "yelp_cflt": "surveyors",
        "gsearch": [
            "construction staking contractor",
            "land surveying contractor",
            "survey staking service",
        ],
    },
    "Fencing": {
        "osm": ["fence", "fencing"],
        "yp": "fencing+contractor",
        "google": "fencing contractor",
        "yelp": "fences-gates",
        "yelp_cflt": "fences-gates",
        "gsearch": [
            "fencing contractor",
            "fence installation company",
            "fence contractor",
        ],
    },
    "Dirtwork": {
        "osm": ["earthwork", "dirt work", "site work"],
        "yp": "dirt+work+contractor",
        "google": "dirt work contractor",
        "yelp": "excavation-services",
        "yelp_cflt": "excavation_services",
        "gsearch": [
            "dirt work contractor",
            "earthwork contractor",
            "site work contractor",
        ],
    },
    "Grading": {
        "osm": ["grading", "land grading", "site grading"],
        "yp": "grading+contractor",
        "google": "grading contractor",
        "yelp": "excavation-services",
        "yelp_cflt": "excavation_services",
        "gsearch": [
            "grading contractor",
            "land grading contractor",
            "finish grading contractor",
        ],
    },
    "Geotechnical Contractor": {
        "osm": ["geotechnical", "soil testing", "geotechnical engineer"],
        "yp": "geotechnical+engineer",
        "google": "geotechnical contractor",
        "yelp": "geotechnical_engineer",
        "yelp_cflt": "geotechnical_engineer",
        "gsearch": [
            "geotechnical contractor",
            "soil testing contractor",
            "geotechnical engineering firm",
        ],
    },
    "Pre Cast Company": {
        "osm": ["precast", "precast concrete", "concrete plant"],
        "yp": "precast+concrete",
        "google": "precast concrete company",
        "yelp": "contractors",
        "yelp_cflt": "contractors",
        "gsearch": [
            "precast concrete company",
            "precast contractor",
            "precast concrete manufacturer",
        ],
    },
    "Fire Hydrant Contractor": {
        "osm": ["fire hydrant", "fire protection", "fire service"],
        "yp": "fire+hydrant+contractor",
        "google": "fire hydrant contractor",
        "yelp": "fire-protection-services",
        "yelp_cflt": "fire-protection-services",
        "gsearch": [
            "fire hydrant contractor",
            "fire hydrant installation contractor",
            "water main fire hydrant contractor",
        ],
    },
    "Fire Suppression Company": {
        "osm": ["fire suppression", "fire sprinkler", "fire protection"],
        "yp": "fire+suppression+contractor",
        "google": "fire suppression company",
        "yelp": "fire-protection-services",
        "yelp_cflt": "fire-protection-services",
        "gsearch": [
            "fire suppression company",
            "fire sprinkler contractor",
            "fire protection contractor",
        ],
    },
}

TRADE_COLORS = {
    "HVAC": "#10b981",
    "Electrical": "#3b82f6",
    "Excavating": "#f59e0b",
    "Construction Staking": "#8b5cf6",
    "Fencing": "#ec4899",
    "Dirtwork": "#a78bfa",
    "Grading": "#d97706",
    "Geotechnical Contractor": "#06b6d4",
    "Pre Cast Company": "#6366f1",
    "Fire Hydrant Contractor": "#ef4444",
    "Fire Suppression Company": "#f97316",
}
SOURCE_COLORS = {
    "OSM": "#8b5cf6",
    "YellowPages": "#f97316",
    "Yelp": "#06b6d4",
    "Google": "#34d399",
    "Google Places": "#4ade80",
    "Direct": "#94a3b8",
}

PROXY_SOURCES = [
    # proxifly — updated every 30 min, tiered quality
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/quality/high/data.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt",  # noqa: E501
    # monosans — frequently updated, clean ip:port format
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    # clarketm — stable long-running list
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    # ShiftyTR — additional coverage
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
    # TheSpeedX — large fallback
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
]

_FATAL_PROXY_ERRORS = (
    "CONNECT tunnel",
    "TLS connect",
    "SSL",
    "OPENSSL",
    "handshake",
    "certificate",
    "403",
    "407",
    "CONNECT aborted",
)
