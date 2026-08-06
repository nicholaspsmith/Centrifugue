"""Locate a browser profile holding a usable YouTube session for yt-dlp.

YouTube rejects unauthenticated requests with "Sign in to confirm you're not
a bot", so yt-dlp needs cookies from a browser that is actually signed in.
Hardcoding a browser breaks the moment the user browses somewhere else, so
the profile is detected by looking for real login cookies.

Zen, Firefox, and other Firefox forks all share the cookies.sqlite format,
so every detected profile is passed to yt-dlp as `firefox:<path>`.
"""

import json
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
    """Count YouTube login cookies, or None if the database cannot be read.

    None and 0 mean different things. 0 is "this profile has no session";
    None is "we could not tell". Treating an unreadable database as 0 makes
    a transient failure look like a signed-out profile, and we then fall
    back to a browser with no cookies at all -- which YouTube answers with
    "Sign in to confirm you're not a bot".
    """
    db = Path(profile_dir) / "cookies.sqlite"
    if not db.is_file():
        return 0

    # The live database is locked while the browser runs, so read a copy.
    # Firefox journals in WAL mode: without the sidecars the copy can miss
    # recent writes or fail to open outright.
    try:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "cookies.sqlite"
            shutil.copy2(db, copy)
            for suffix in ("-wal", "-shm"):
                sidecar = db.with_name(db.name + suffix)
                if sidecar.is_file():
                    try:
                        shutil.copy2(sidecar, copy.with_name(copy.name + suffix))
                    except OSError:
                        pass
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
        return None


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
    holds a session worth using. An unreadable profile (score None) is
    never selected, but it is also not evidence of a signed-out browser.
    """
    best, best_score = None, 0
    for profile in profiles:
        score = scorer(profile)
        if score is None:
            continue
        if score > best_score:
            best, best_score = profile, score
    return f"firefox:{best}" if best is not None else None


def get_state_path():
    return Path.home() / ".centrifugue" / "cookie_source.json"


def remember_source(spec):
    """Persist a working cookie source. Never raises."""
    try:
        path = get_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"spec": spec}) + "\n")
    except Exception:
        pass


def recall_source():
    """The last source known to work, if its profile still exists."""
    try:
        spec = json.loads(get_state_path().read_text()).get("spec")
    except Exception:
        return None
    if not spec:
        return None
    if spec.startswith("firefox:"):
        profile = spec.split(":", 1)[1]
        if not Path(profile).is_dir():
            return None
    return spec


def resolve_cookie_spec(configured):
    """Turn the configured value into a --cookies-from-browser argument.

    Anything other than "auto" (or unset) is passed straight through, so a
    user can name any browser yt-dlp supports.
    """
    global _cached_spec
    if configured and configured != "auto":
        return configured
    if _cached_spec is None:
        detected = choose_cookie_source(find_profiles())
        if detected:
            remember_source(detected)
            _cached_spec = detected
        else:
            # Detection came up empty. While a browser is running that is
            # usually a transient read failure rather than a signed-out
            # profile, so prefer the last source that actually worked over
            # falling back to a browser we may have no cookies for.
            _cached_spec = recall_source() or "firefox"
    return _cached_spec
