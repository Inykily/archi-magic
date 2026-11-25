"""URL settings and link checks for a public embed page (issue #288, first step).

A whiteboard frame (for example Miro) keeps only the link. So the embed page reads its state from
the URL, and each frame shows the same state to everyone. This module holds that contract:

  option   design option number, 1 to 99            (default 1)
  bar      0 hides the option switch, 1 shows it     (default 1)
  view     3d | plan | n | e | s | w                 (default 3d; plan = site plan, n/e/s/w = elevations)
  display  clay | shaded | pen                       (default clay)
  spin     0 stops the idle spin, 1 spins            (default 1)

An embed link must always open, so a bad value falls back to its default with a warning. It does
not stop the page.

It also checks the public side of the link:
  is_allowed_path   an exact-file allowlist. It refuses encoded separators and dot segments
                    (for example "..%2f"), which a prefix rule lets through.
  missing_headers   the response headers a public embed needs (no referrer, no index).

Usage:
  python embed_settings.py parse "https://example.com/embed/a1b2.html?option=2&bar=0&view=e"
  python embed_settings.py build --option 2 --bar 0 --view e --display pen
  python embed_settings.py check-path "/embed/a1b2.html" --allow /embed/a1b2.html

Pure Python 3. It does not build the embed page itself.
"""

import argparse
import json
import posixpath
import sys

from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

VIEWS = ("3d", "plan", "n", "e", "s", "w")
DISPLAYS = ("clay", "shaded", "pen")
DEFAULTS = {"option": 1, "bar": True, "view": "3d", "display": "clay", "spin": True}
ORDER = ("option", "bar", "view", "display", "spin")
MAX_OPTION = 99

# Headers every public embed response needs. The value check is a lower-case "contains".
REQUIRED_HEADERS = {
    "referrer-policy": "no-referrer",
    "x-robots-tag": "noindex",
}


def _flag(value):
    v = value.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return None


def parse_embed_query(query):
    """Settings dict and a list of warnings from a query string or a full URL."""
    if "?" in query or "://" in query:
        query = urlsplit(query).query
    query = query.lstrip("?")
    settings = dict(DEFAULTS)
    warnings = []
    seen = set()
    for key, value in parse_qsl(query, keep_blank_values=True):
        key = key.strip().lower()
        if key not in DEFAULTS:
            warnings.append("unknown setting '%s' is ignored" % key)
            continue
        if key in seen:
            warnings.append("setting '%s' is given more than once; the first value is used" % key)
            continue
        seen.add(key)
        if key == "option":
            v = value.strip()
            if v.isdigit() and 1 <= int(v) <= MAX_OPTION:
                settings["option"] = int(v)
            else:
                warnings.append("option '%s' is not 1 to %d; option 1 is used" % (value, MAX_OPTION))
        elif key in ("bar", "spin"):
            f = _flag(value)
            if f is None:
                warnings.append("%s '%s' is not 0 or 1; the default is used" % (key, value))
            else:
                settings[key] = f
        elif key == "view":
            v = value.strip().lower()
            if v in VIEWS:
                settings["view"] = v
            else:
                warnings.append("view '%s' is not one of %s; 3d is used" % (value, ", ".join(VIEWS)))
        elif key == "display":
            v = value.strip().lower()
            if v in DISPLAYS:
                settings["display"] = v
            else:
                warnings.append("display '%s' is not one of %s; clay is used" % (value, ", ".join(DISPLAYS)))
    return settings, warnings


def build_embed_query(settings):
    """Shortest query string for the settings: only values that differ from the defaults."""
    clean, warnings = parse_embed_query(urlencode([(k, _text(settings[k])) for k in ORDER if k in settings]))
    if warnings:
        raise ValueError("; ".join(warnings))
    pairs = [(k, _text(clean[k])) for k in ORDER if clean[k] != DEFAULTS[k]]
    return urlencode(pairs)


def _text(v):
    if v is True:
        return "1"
    if v is False:
        return "0"
    return str(v)


def is_allowed_path(raw_path, allowlist):
    """True only when the request path is exactly one allowed file.

    The raw path is the path as the client sent it, still percent-encoded. Any encoded "/", "\\"
    or ".", a backslash, a dot segment, an empty segment or a query is refused before the match.
    """
    if not isinstance(raw_path, str) or not raw_path.startswith("/"):
        return False
    if "?" in raw_path or "#" in raw_path or "\\" in raw_path:
        return False
    low = raw_path.lower()
    for bad in ("%2f", "%5c", "%2e", "%25", "%00"):
        if bad in low:
            return False
    path = unquote(raw_path)
    segments = path.split("/")[1:]
    if any(s in ("", ".", "..") for s in segments):
        return False
    if posixpath.normpath(path) != path:
        return False
    return path in set(allowlist or [])


def missing_headers(headers):
    """Names of required public-embed headers that are absent or have the wrong value."""
    have = dict((str(k).lower(), str(v).lower()) for k, v in (headers or {}).items())
    return [name for name, want in sorted(REQUIRED_HEADERS.items()) if want not in have.get(name, "")]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("parse", help="read the settings from a link or a query string")
    p.add_argument("link")
    b = sub.add_parser("build", help="write the shortest query string for these settings")
    b.add_argument("--option", type=int, default=DEFAULTS["option"])
    b.add_argument("--bar", choices=("0", "1"), default="1")
    b.add_argument("--view", choices=VIEWS, default=DEFAULTS["view"])
    b.add_argument("--display", choices=DISPLAYS, default=DEFAULTS["display"])
    b.add_argument("--spin", choices=("0", "1"), default="1")
    c = sub.add_parser("check-path", help="check one request path against the exact-file allowlist")
    c.add_argument("path")
    c.add_argument("--allow", action="append", default=[], help="one allowed file path (repeat)")
    args = ap.parse_args(argv)
    if args.cmd == "parse":
        settings, warnings = parse_embed_query(args.link)
        print(json.dumps({"settings": settings, "warnings": warnings}, indent=2))
        return 0
    if args.cmd == "build":
        try:
            q = build_embed_query({"option": args.option, "bar": args.bar == "1", "view": args.view,
                                   "display": args.display, "spin": args.spin == "1"})
        except ValueError as exc:
            print("FAIL: %s" % exc)
            return 1
        print(("?" + q) if q else "")
        return 0
    if args.cmd == "check-path":
        ok = is_allowed_path(args.path, args.allow)
        print("ALLOWED" if ok else "REFUSED")
        return 0 if ok else 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
