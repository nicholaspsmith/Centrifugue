"""Locate a browser profile holding a usable YouTube session for yt-dlp.

YouTube rejects unauthenticated requests with "Sign in to confirm you're not
a bot", so yt-dlp needs cookies from a browser that is actually signed in.
Hardcoding a browser breaks the moment the user browses somewhere else, so
the profile is detected by looking for real login cookies.

Zen, Firefox, and other Firefox forks all share the cookies.sqlite format,
so every detected profile is passed to yt-dlp as `firefox:<path>`.
"""

import shutil
import sqlite3
import tempfile
from pathlib import Path

# Presence of any of these means the profile has a signed-in YouTube session
LOGIN_COOKIE_NAMES = ("SID", "__Secure-1PSID", "__Secure-3PSID", "LOGIN_INFO")

# macOS locations for Firefox-family browsers
PROFILE_GLOBS = (
    "~/Library/Application Support/zen/Profiles/*",
    "~/Library/Application Support/Firefox/Profiles/*",
)

_cached_spec = None


def reset_cache():
    """Forget any previously detected profile (used by tests)."""
    global _cached_spec
    _cached_spec = None


def score_profile(profile_dir):
    """Count YouTube login cookies in a Firefox-family profile.

    Never raises: a locked, missing, or corrupt database simply scores 0.
    """
    db = Path(profile_dir) / "cookies.sqlite"
    if not db.is_file():
        return 0

    # The live database is locked while the browser runs, so read a copy
    try:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "cookies.sqlite"
            shutil.copy2(db, copy)
            con = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
            try:
                placeholders = ",".join("?" * len(LOGIN_COOKIE_NAMES))
                cur = con.execute(
                    "SELECT COUNT(*) FROM moz_cookies "
                    "WHERE host LIKE '%youtube.com' "
                    f"AND name IN ({placeholders})",
                    LOGIN_COOKIE_NAMES,
                )
                return int(cur.fetchone()[0])
            finally:
                con.close()
    except Exception:
        return 0


def find_profiles(globs=PROFILE_GLOBS):
    """All Firefox-family profile directories on this machine."""
    found = []
    for pattern in globs:
        expanded = Path(pattern).expanduser()
        found.extend(sorted(p for p in expanded.parent.glob(expanded.name)
                            if p.is_dir()))
    return found


def choose_cookie_source(profiles, scorer=score_profile):
    """Pick the profile with the most YouTube login cookies.

    Returns a yt-dlp --cookies-from-browser spec, or None when no profile
    holds a session worth using.
    """
    best, best_score = None, 0
    for profile in profiles:
        score = scorer(profile)
        if score > best_score:
            best, best_score = profile, score
    return f"firefox:{best}" if best is not None else None


def resolve_cookie_spec(configured):
    """Turn the configured value into a --cookies-from-browser argument.

    Anything other than "auto" (or unset) is passed straight through, so a
    user can name any browser yt-dlp supports.
    """
    global _cached_spec
    if configured and configured != "auto":
        return configured
    if _cached_spec is None:
        _cached_spec = choose_cookie_source(find_profiles()) or "firefox"
    return _cached_spec
