# -*- coding: utf-8 -*-
"""Pure logic for am-shared-text-check (no Revit dependency).

Runs under IronPython 2.7 and CPython 3 (no f-strings, ASCII only).
The CLI and the tests import this module; read_shared_text.py runs in
Revit and only lists notes, it does not import this module.

Search rules (from archi-magic issue #101):
- User terms match whole-word and case-sensitive. A short firm
  abbreviation must not match a common word that holds the same letters
  ("AB" matches "AB-01" but not "ABLE"; "IT" matches "IT team" but
  not "WITH").
- Personal paths: drive-letter paths, UNC paths, user folders, cloud
  sync folders (OneDrive, Dropbox, Google Drive, Box, iCloudDrive)
  and %USERPROFILE% / %ONEDRIVE% / %HOMEPATH% forms. A bare folder
  name with no path around it is not a finding.
- Email addresses match a plain address pattern.
- @ names match @name, except the @ part of an email address.
- First names match only names the user gives, whole-word and
  case-sensitive. The check never guesses a first name from a
  capitalised word.
"""

import re

WORD_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")

DRIVE_RE = re.compile(r"[A-Za-z]:[\\/][^\s\"<>|]*")
UNC_RE = re.compile(r"\\\\[A-Za-z0-9_.$-]+\\[^\s\"<>|]*")
ENV_RE = re.compile(r"%(USERPROFILE|ONEDRIVE|HOMEPATH)%")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
AT_RE = re.compile(r"@[A-Za-z0-9_][A-Za-z0-9_.-]*")

CLOUD_FOLDERS = set(["onedrive", "dropbox", "box", "iclouddrive", "google drive"])


def is_word_char(c):
    return c in WORD_CHARS


def find_term_matches(text, term):
    """Whole-word, case-sensitive matches of term. Returns [(start, end)]."""
    out = []
    if not term:
        return out
    n = len(term)
    i = 0
    while True:
        j = text.find(term, i)
        if j < 0:
            break
        before_ok = (j == 0) or (not is_word_char(text[j - 1]))
        after = j + n
        after_ok = (after >= len(text)) or (not is_word_char(text[after]))
        if before_ok and after_ok:
            out.append((j, after))
        i = j + 1
    return out


def _spans_overlap(a_start, a_end, spans):
    for s, e in spans:
        if a_start < e and s < a_end:
            return True
    return False


def classify_path(token):
    """Subtype of a path token: cloud_sync, user_folder, env_var, unc, drive."""
    if token.startswith("%"):
        return "env_var"
    if token.startswith("\\\\"):
        return "unc"
    segments = re.split(r"[\\/]", token)
    lowered = [s.lower() for s in segments]
    for s in lowered:
        if s in CLOUD_FOLDERS:
            return "cloud_sync"
    if "users" in lowered:
        return "user_folder"
    return "drive"


def find_paths(text):
    """Path tokens with spans. Returns [(start, end, token, subtype)]."""
    found = []
    spans = []
    for pattern in (DRIVE_RE, UNC_RE, ENV_RE):
        for m in pattern.finditer(text):
            if _spans_overlap(m.start(), m.end(), spans):
                continue
            spans.append((m.start(), m.end()))
            found.append((m.start(), m.end(), m.group(0), classify_path(m.group(0))))
    found.sort()
    return found


def find_emails(text):
    """Email spans. Returns [(start, end, address)]."""
    return [(m.start(), m.end(), m.group(0)) for m in EMAIL_RE.finditer(text)]


def find_at_names(text):
    """@ names, skipping the @ part of an email address."""
    email_spans = [(s, e) for s, e, _ in find_emails(text)]
    out = []
    for m in AT_RE.finditer(text):
        if _spans_overlap(m.start(), m.end(), email_spans):
            continue
        out.append((m.start(), m.end(), m.group(0)))
    return out


def neutral_form(token, subtype):
    """Suggested neutral wording for a personal path. Suggestion only;
    the user approves each change through am-safe-change."""
    if subtype == "cloud_sync":
        return "personal cloud folder"
    if subtype in ("user_folder", "env_var"):
        return "personal folder"
    if subtype == "unc":
        return "network path"
    return "local drive path"


def split_lines(text):
    """Lines with start offsets. Handles \\r\\n, \\r and \\n."""
    out = []
    start = 0
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\r":
            if i + 1 < n and text[i + 1] == "\n":
                out.append((start, text[start:i]))
                i += 2
                start = i
            else:
                out.append((start, text[start:i]))
                i += 1
                start = i
        elif c == "\n":
            out.append((start, text[start:i]))
            i += 1
            start = i
        else:
            i += 1
    if start < n or not out:
        out.append((start, text[start:]))
    return out


def line_number_for(lines, offset):
    """1-based line number that holds offset."""
    num = 1
    for idx in range(len(lines)):
        if lines[idx][0] <= offset:
            num = idx + 1
        else:
            break
    return num


def _finding(lines, offset, match, kind, subtype=None, suggestion=None):
    num = line_number_for(lines, offset)
    line_text = lines[num - 1][1] if num - 1 < len(lines) else ""
    context = line_text.strip()
    if len(context) > 120:
        context = context[:117] + "..."
    f = {"kind": kind, "match": match, "line": num, "context": context,
         "offset": offset}
    if subtype is not None:
        f["subtype"] = subtype
    if suggestion is not None:
        f["suggestion"] = suggestion
    return f


def check_note(text, terms, first_names):
    """Findings in one note's text, sorted by offset."""
    lines = split_lines(text)
    findings = []
    for term in terms or []:
        for s, _ in find_term_matches(text, term):
            findings.append(_finding(lines, s, term, "term"))
    for s, _, token, subtype in find_paths(text):
        findings.append(_finding(lines, s, token, "personal_path",
                                 subtype=subtype,
                                 suggestion=neutral_form(token, subtype)))
    for s, _, address in find_emails(text):
        findings.append(_finding(lines, s, address, "email"))
    for s, _, name in find_at_names(text):
        findings.append(_finding(lines, s, name, "at_name"))
    for name in first_names or []:
        for s, _ in find_term_matches(text, name):
            findings.append(_finding(lines, s, name, "first_name"))
    findings.sort(key=lambda f: f["offset"])
    return findings


def check_notes(notes, terms, first_names):
    """Findings across notes. Each note: id, view, view_id, text."""
    out = []
    counts = {}
    for note in notes:
        for f in check_note(note.get("text", ""), terms, first_names):
            f["note_id"] = note.get("id")
            f["view"] = note.get("view")
            f["view_id"] = note.get("view_id")
            out.append(f)
            counts[f["kind"]] = counts.get(f["kind"], 0) + 1
    return {"findings": out, "counts": counts}


def is_prose_note(text, min_words=6):
    """Check if text note is prose (>= min_words alphanumeric words). Table cells and short labels are False."""
    words = [w for w in (text or "").split() if any(c.isalnum() for c in w)]
    return len(words) >= min_words


def extract_fact_tokens(text):
    """Tokens that must be preserved: containing digits, _, $, <>, or non-punctuation symbols."""
    facts = set()
    for tok in (text or "").split():
        stripped = tok.strip(".,;:!?'()[]{}").strip('"')
        if not stripped:
            continue
        if any(c.isdigit() or c in "_$<>/\\#%*+=" for c in stripped):
            facts.add(stripped)
    return facts


def check_fact_preservation(original_text, rewritten_text):
    """Verify that all technical tokens (numbers, IDs, codes, symbols) survive in rewritten text.

    Returns (ok, missing_tokens).
    """
    orig_facts = extract_fact_tokens(original_text)
    rewritten_tokens = set(t.strip(".,;:!?'()[]{}").strip('"') for t in (rewritten_text or "").split())
    missing = sorted(list(orig_facts - rewritten_tokens))
    return len(missing) == 0, missing
