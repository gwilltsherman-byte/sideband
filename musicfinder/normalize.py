"""Name normalisation so that the same artist/track matches across Spotify, Last.fm and Deezer."""

from __future__ import annotations

import re
import unicodedata

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")
_LEADING_THE = re.compile(r"^the\s+")
# "(feat. X)", "[with Y]", "(Remastered 2011)", "(Live at ...)" etc.
_BRACKETED = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
# "Song - 2011 Remaster", "Song - Radio Edit", "Song - Live"
_DASH_SUFFIX = re.compile(
    r"\s+-\s+.*\b(remaster(ed)?|version|edit|mix|live|mono|stereo|acoustic|demo|bonus|session|single|"
    r"instrumental|deluxe|anniversary|recorded|take)\b.*$",
    re.IGNORECASE,
)
_FEAT = re.compile(r"\s+(feat\.?|ft\.?|featuring)\s+.*$", re.IGNORECASE)

VARIOUS_ARTISTS = {"various artists", "various", "va", "unknown artist", "unknown"}


def _fold(text: str) -> str:
    """Case-fold and drop Latin/Greek/Cyrillic accents (é -> e) while leaving other scripts intact."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not 0x300 <= ord(ch) <= 0x36F)
    return unicodedata.normalize("NFC", stripped).casefold()


def artist_key(name: str) -> str:
    """Canonical key for an artist name: case/accent-insensitive, '&' == 'and', no leading 'The'."""
    if not name:
        return ""
    s = _fold(name).replace("&", " and ").replace("+", " and ")
    s = _PUNCT.sub(" ", s)
    s = _SPACE.sub(" ", s).strip()
    s = _LEADING_THE.sub("", s)
    return s or name.casefold().strip()


def track_key(title: str) -> str:
    """Canonical key for a track title: drops remaster/feat./live suffixes so versions collapse together."""
    if not title:
        return ""
    s = _BRACKETED.sub("", title)
    s = _DASH_SUFFIX.sub("", s)
    s = _FEAT.sub("", s)
    s = _fold(s).replace("&", " and ")
    s = _PUNCT.sub(" ", s)
    s = _SPACE.sub(" ", s).strip()
    return s or _fold(title).strip()


def is_various(name: str) -> bool:
    return artist_key(name) in VARIOUS_ARTISTS


# Last.fm-style tags that describe the listener or the format rather than the music.
_TAG_STOPLIST = {
    "seen live", "favorite", "favorites", "favourite", "favourites", "my favorite", "love", "loved",
    "awesome", "beautiful", "amazing", "cool", "good", "great", "best", "albums i own", "all",
    "spotify", "check out", "under 2000 listeners", "fip", "favorite artists", "favourite artists",
    "music", "musik", "other", "unknown", "male vocalists", "female vocalists", "male vocalist",
    "female vocalist",
    "american", "british", "uk", "usa", "english", "canadian", "australian", "german", "french",
    "swedish", "japanese", "korean", "brazilian", "spanish", "italian", "irish", "scottish",
}
_TAG_ALIASES = {
    "hip-hop": "hip hop", "hiphop": "hip hop", "rap": "hip hop", "r&b": "rnb", "r and b": "rnb",
    "rhythm and blues": "rnb", "singer-songwriter": "singer songwriter", "electronica": "electronic",
    "electro": "electronic", "post rock": "post-rock", "post punk": "post-punk", "lofi": "lo-fi",
    "lo fi": "lo-fi", "dnb": "drum and bass", "drum n bass": "drum and bass", "kpop": "k-pop",
    "jpop": "j-pop", "alt rock": "alternative rock", "alternative": "alternative rock",
    "indie": "indie", "synth pop": "synthpop", "synth-pop": "synthpop", "trip hop": "trip-hop",
    "shoegazing": "shoegaze", "neo soul": "neo-soul", "dreampop": "dream pop",
}
_YEARish = re.compile(r"^(\d{2,4}s?|\d{4})$")


def clean_tag(tag: str) -> str | None:
    """Return a canonical genre-ish tag, or None if the tag is noise (decades, 'seen live', nationalities...)."""
    t = _SPACE.sub(" ", tag.strip().casefold())
    if not t or len(t) > 40:
        return None
    t = _TAG_ALIASES.get(t, t)
    if t in _TAG_STOPLIST or _YEARish.match(t):
        return None
    return t
