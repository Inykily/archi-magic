"""embed_settings.py: URL settings and link checks for a public embed page (issue #288)."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import embed_settings as es  # noqa: E402

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "embed_settings.py"


def test_defaults():
    settings, warnings = es.parse_embed_query("")
    assert settings == {"option": 1, "bar": True, "view": "3d", "display": "clay", "spin": True}
    assert warnings == []


def test_issue_example_link():
    settings, warnings = es.parse_embed_query(
        "https://example.com/embed/a1b2.html?option=2&bar=0&view=e&display=clay")
    assert settings == {"option": 2, "bar": False, "view": "e", "display": "clay", "spin": True}
    assert warnings == []


@pytest.mark.parametrize("query,key,value", [
    ("option=0", "option", 1), ("option=abc", "option", 1), ("option=100", "option", 1),
    ("bar=maybe", "bar", True), ("view=top", "view", "3d"), ("display=realistic", "display", "clay"),
    ("spin=2", "spin", True),
])
def test_bad_values_fall_back_with_a_warning(query, key, value):
    settings, warnings = es.parse_embed_query(query)
    assert settings[key] == value
    assert len(warnings) == 1


def test_unknown_and_repeated_settings_warn():
    settings, warnings = es.parse_embed_query("?zoom=3&view=n&view=s&SPIN=off&Display=PEN")
    assert settings["view"] == "n" and settings["spin"] is False and settings["display"] == "pen"
    assert len(warnings) == 2


def test_build_is_short_and_round_trips():
    assert es.build_embed_query(dict(es.DEFAULTS)) == ""
    q = es.build_embed_query({"option": 3, "bar": False, "view": "plan", "display": "pen", "spin": False})
    assert q == "option=3&bar=0&view=plan&display=pen&spin=0"
    assert es.parse_embed_query(q)[0] == {"option": 3, "bar": False, "view": "plan", "display": "pen", "spin": False}
    with pytest.raises(ValueError):
        es.build_embed_query({"view": "top"})


ALLOW = ["/embed/a1b2c3.html", "/embed/a1b2c3.json"]


@pytest.mark.parametrize("path", ["/embed/a1b2c3.html", "/embed/a1b2c3.json"])
def test_exact_files_pass(path):
    assert es.is_allowed_path(path, ALLOW)


@pytest.mark.parametrize("path", [
    "/embed/", "/embed", "/embed/a1b2c3.html/", "/embed/a1b2c3.htm", "/embed/a1b2c3.html.bak",
    "/embed/..%2fprivate/index.html", "/embed/..%2Fa1b2c3.html", "/embed/%2e%2e/a1b2c3.html",
    "/embed/%252e%252e/x", "/embed/../embed/a1b2c3.html", "/embed//a1b2c3.html",
    "/embed/./a1b2c3.html", "/embed\\a1b2c3.html", "/embed/a1b2c3.html?x=1", "embed/a1b2c3.html",
    "/embed/a1b2c3.html%00", "/EMBED/a1b2c3.html",
])
def test_prefix_and_traversal_paths_are_refused(path):
    assert not es.is_allowed_path(path, ALLOW)


def test_missing_headers():
    assert es.missing_headers({}) == ["referrer-policy", "x-robots-tag"]
    ok = {"Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, nofollow"}
    assert es.missing_headers(ok) == []
    assert es.missing_headers({"Referrer-Policy": "origin", "X-Robots-Tag": "noindex"}) == ["referrer-policy"]


def test_cli():
    run = subprocess.run([sys.executable, str(SCRIPT), "build", "--option", "2", "--bar", "0", "--view", "e"],
                         capture_output=True, text=True)
    assert run.returncode == 0 and run.stdout.strip() == "?option=2&bar=0&view=e"
    run = subprocess.run([sys.executable, str(SCRIPT), "check-path", "/embed/..%2fx", "--allow", "/embed/x"],
                         capture_output=True, text=True)
    assert run.returncode == 1 and "REFUSED" in run.stdout
