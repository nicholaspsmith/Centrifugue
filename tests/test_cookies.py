import sqlite3
import centrifugue_cookies as ck


import pytest


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Keep the remembered cookie source out of the real home directory."""
    monkeypatch.setattr(ck, "get_state_path", lambda: tmp_path / "cookie_source.json")


def _make_profile(path, youtube_login_cookies=0, junk_cookies=0):
    path.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path / "cookies.sqlite")
    con.execute("CREATE TABLE moz_cookies (host TEXT, name TEXT)")
    for i in range(youtube_login_cookies):
        con.execute("INSERT INTO moz_cookies VALUES (?, ?)",
                    (".youtube.com", ck.LOGIN_COOKIE_NAMES[i % len(ck.LOGIN_COOKIE_NAMES)]))
    for i in range(junk_cookies):
        con.execute("INSERT INTO moz_cookies VALUES (?, ?)", (".example.com", f"c{i}"))
    con.commit()
    con.close()
    return path


def test_scores_profile_by_youtube_login_cookies(tmp_path):
    p = _make_profile(tmp_path / "zen", youtube_login_cookies=3, junk_cookies=10)
    assert ck.score_profile(p) == 3


def test_profile_without_login_cookies_scores_zero(tmp_path):
    p = _make_profile(tmp_path / "empty", youtube_login_cookies=0, junk_cookies=5)
    assert ck.score_profile(p) == 0


def test_missing_database_scores_zero(tmp_path):
    (tmp_path / "nodb").mkdir()
    assert ck.score_profile(tmp_path / "nodb") == 0


def test_chooses_the_profile_with_the_most_login_cookies():
    scores = {"/a": 0, "/b": 4, "/c": 1}
    spec = ck.choose_cookie_source(list(scores), scorer=lambda p: scores[p])
    assert spec == "firefox:/b"


def test_returns_none_when_no_profile_has_a_session():
    spec = ck.choose_cookie_source(["/a", "/b"], scorer=lambda p: 0)
    assert spec is None


def test_explicit_config_value_is_passed_through_untouched():
    assert ck.resolve_cookie_spec("chrome") == "chrome"
    assert ck.resolve_cookie_spec("firefox:/custom/path") == "firefox:/custom/path"


def test_auto_falls_back_to_plain_firefox_when_nothing_detected(monkeypatch):
    monkeypatch.setattr(ck, "find_profiles", lambda: [])
    ck.reset_cache()
    assert ck.resolve_cookie_spec("auto") == "firefox"


def test_auto_uses_the_detected_profile(monkeypatch, tmp_path):
    good = _make_profile(tmp_path / "zen", youtube_login_cookies=2)
    monkeypatch.setattr(ck, "find_profiles", lambda: [good])
    ck.reset_cache()
    assert ck.resolve_cookie_spec("auto") == f"firefox:{good}"


def test_none_and_empty_config_behave_as_auto(monkeypatch):
    monkeypatch.setattr(ck, "find_profiles", lambda: [])
    ck.reset_cache()
    assert ck.resolve_cookie_spec(None) == "firefox"
    ck.reset_cache()
    assert ck.resolve_cookie_spec("") == "firefox"


# --- Regression: an unreadable database must not look like "no session" ----
# A torn copy of a live 2MB DB used to return 0, which is indistinguishable
# from a signed-out profile, so we silently fell back to plain "firefox"
# (a profile with no cookies) and YouTube answered "not a bot".

def test_unreadable_database_scores_unknown_not_zero(tmp_path):
    p = tmp_path / "corrupt"
    p.mkdir()
    (p / "cookies.sqlite").write_text("not a database")
    assert ck.score_profile(p) is None


def test_readable_profile_with_no_session_scores_zero(tmp_path):
    p = _make_profile(tmp_path / "empty", youtube_login_cookies=0, junk_cookies=5)
    assert ck.score_profile(p) == 0


def test_unknown_scores_are_never_selected():
    spec = ck.choose_cookie_source(["/a", "/b"], scorer=lambda p: None)
    assert spec is None


def test_unknown_does_not_outrank_a_real_session():
    scores = {"/a": None, "/b": 2}
    spec = ck.choose_cookie_source(list(scores), scorer=lambda p: scores[p])
    assert spec == "firefox:/b"


def test_detected_source_is_remembered(monkeypatch, tmp_path):
    good = _make_profile(tmp_path / "zen", youtube_login_cookies=2)
    monkeypatch.setattr(ck, "get_state_path", lambda: tmp_path / "src.json")
    monkeypatch.setattr(ck, "find_profiles", lambda: [good])
    ck.reset_cache()
    assert ck.resolve_cookie_spec("auto") == f"firefox:{good}"
    assert ck.recall_source() == f"firefox:{good}"


def test_transient_failure_falls_back_to_last_good_not_plain_firefox(monkeypatch, tmp_path):
    good = _make_profile(tmp_path / "zen", youtube_login_cookies=2)
    monkeypatch.setattr(ck, "get_state_path", lambda: tmp_path / "src.json")

    # first run detects and remembers
    monkeypatch.setattr(ck, "find_profiles", lambda: [good])
    ck.reset_cache()
    ck.resolve_cookie_spec("auto")

    # second run: the database is briefly unreadable
    monkeypatch.setattr(ck, "score_profile", lambda p: None)
    ck.reset_cache()
    assert ck.resolve_cookie_spec("auto") == f"firefox:{good}"


def test_last_good_is_ignored_if_the_profile_is_gone(monkeypatch, tmp_path):
    state = tmp_path / "src.json"
    state.write_text('{"spec": "firefox:/nowhere/at/all"}')
    monkeypatch.setattr(ck, "get_state_path", lambda: state)
    monkeypatch.setattr(ck, "find_profiles", lambda: [])
    ck.reset_cache()
    assert ck.resolve_cookie_spec("auto") == "firefox"
