"""Gift slug handling and public link building.

A unique (upgraded) Telegram gift is addressable at
    https://t.me/nft/<CollectionSlug>-<number>
where the slug is the collection name in CamelCase with spaces and
punctuation stripped. That link is what Telegram renders a preview for, so
getting the slug right is the difference between a post with a picture and a
post with a dead link.

Traders type names in every imaginable spelling ("plushpepe", "Plush Pepe",
"plush-pepe"), so lookup is done on a squashed key and the canonical slug is
stored explicitly rather than guessed.
"""

import json
import os
import re
from pathlib import Path

NFT_LINK_BASE = "https://t.me/nft/"

# Canonical slugs of known collections, keyed by their squashed form.
# Extend at runtime with GIFT_ALIASES_FILE (a JSON {"<any spelling>": "<Slug>"}).
_KNOWN_SLUGS = [
    "PlushPepe", "DurovsCap", "PreciousPeach", "EternalRose", "HeartLocket",
    "LootBag", "SwissWatch", "ScaredCat", "NekoHelmet", "ToyBear",
    "JellyBunny", "MadPumpkin", "HypnoLollipop", "DeskCalendar", "BDayCandle",
    "RecordPlayer", "JesterHat", "SantaHat", "SignetRing", "SpyAgaric",
    "HomemadeCake", "GenieLamp", "LunarSnake", "PartySparkler", "WitchHat",
    "HangingStar", "LoveCandle", "CookieHeart", "SakuraFlower", "SleighBell",
    "GingerCookie", "SpicedWine", "SnowMittens", "WinterWreath", "SnowGlobe",
    "ElectricSkull", "VoodooDoll", "DiamondRing", "CrystalBall", "EternalCandle",
    "BerryBox", "VintageCigar", "MagicPotion", "KissedFrog", "HexPot",
    "EvilEye", "SharpTongue", "TrappedHeart", "SkullFlower", "TopHat",
    "BunnyMuffin", "AstralShard", "FlyingBroom", "CandyCane", "LightSword",
    "RestlessJar", "NailBracelet", "HeroicHelmet", "BondedRing", "PetSnake",
    "SnakeBox", "XmasStocking", "BigYear", "GemSignet", "LowRider",
    "IonGem", "PerfumeBottle", "JoyfulBundle", "WhipCupcake", "StarNotepad",
    "LolPop", "IonicDryer", "StellarRocket", "MoonPendant", "TamaGadget",
    "MiniOscar", "LovePotion", "ToyTrain", "GingerBread", "CupidCharm",
    "ValentineBox", "SnoopDogg", "SnoopCigar", "SwagBag", "WestsideSign",
    "PlushPepeCap",
]


def squash(raw: str) -> str:
    """Collapse any spelling to a comparable key: 'Durov's Cap' -> 'durovscap'."""
    return re.sub(r"[^a-z0-9]", "", raw.lower())


_ALIASES = {squash(slug): slug for slug in _KNOWN_SLUGS}


def _load_extra_aliases() -> None:
    path = os.environ.get("GIFT_ALIASES_FILE")
    if not path:
        return
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return  # a broken alias file must never stop the bot from posting
    for spelling, slug in data.items():
        if isinstance(spelling, str) and isinstance(slug, str) and slug:
            _ALIASES[squash(spelling)] = slug


_load_extra_aliases()


def normalize_slug(raw: str) -> tuple[str, bool]:
    """Return (canonical_slug, is_known).

    An unknown name still produces a best-effort slug so the bot stays usable
    the day a new collection drops — the caller decides whether to warn.
    """
    key = squash(raw)
    if key in _ALIASES:
        return _ALIASES[key], True

    words = re.split(r"[^A-Za-z0-9]+", raw.strip())
    words = [w for w in words if w]
    if len(words) > 1:
        # Multi-word input carries its own boundaries: "plush pepe" -> PlushPepe
        return "".join(w[:1].upper() + w[1:] for w in words), False
    if words and not words[0].islower():
        # Already CamelCase or mixed case — trust what was typed.
        return words[0], False
    return (words[0][:1].upper() + words[0][1:]) if words else "", False


def gift_link(slug: str, number: int) -> str:
    return f"{NFT_LINK_BASE}{slug}-{number}"


#: Names that CamelCase splitting cannot reconstruct (apostrophes, hyphens).
_DISPLAY_OVERRIDES = {
    "DurovsCap": "Durov's Cap",
    "BDayCandle": "B-Day Candle",
    "SnoopDogg": "Snoop Dogg",
    "LolPop": "Lol Pop",
    "XmasStocking": "Xmas Stocking",
}


def gift_title(slug: str) -> str:
    """'PlushPepe' -> 'Plush Pepe' for display inside the post."""
    if slug in _DISPLAY_OVERRIDES:
        return _DISPLAY_OVERRIDES[slug]
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", slug)
    return re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", spaced)


def known_slugs() -> list[str]:
    return sorted(set(_ALIASES.values()))
