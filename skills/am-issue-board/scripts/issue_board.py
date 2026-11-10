# -*- coding: utf-8 -*-
"""Pure logic for the am-issue-board skill: an issue tracker kept in a Revit text note.

Runs under IronPython 2.7 (inside Revit, through run_query / run_modify with
`workspace` set to this folder) and under CPython 3 (tests, board_cli.py).
No f-strings, no type annotations, no nonlocal. The only functions that touch
a Revit object are apply_formats() and apply_plan(); they receive the
FormattedText and two small adapters, so tests can pass a fake.

Board format (one paragraph per line, paragraphs separated by "\\r" in Revit):

    AUDIT - 2026-01-05 (by @user1)                      bold, list None, indent 0
    Issues use fixed numbers; next new issue is #3. ...  list None, indent 0
    <blank>                                              list None, indent 0
    #1 [OPEN] Title text - @user2                        bold, list None, indent 0
    Severity: High                                       bullet, indent 1
    Finding: ... (id1001) ...                            bullet, indent 1, ids underlined
    detail row                                           bullet, indent 2
    To do: ...                                           bullet, indent 1
    2026-01-05 @user1: dated comment                     bullet, indent 1
    Related: #2. Path: see #2.                           bullet, indent 1

In Revit the bullet comes from the list type, so child lines have no "- " in
the plain text. The parser also accepts a leading "- " (hand-written boards).
"""
import hashlib
import re

STATUSES = ("OPEN", "IN PROGRESS", "DONE")
PARA_BREAK = "\r"

RULES_TEMPLATE = ("Issues use fixed numbers; next new issue is #%d. Never renumber. "
                  "Status: [OPEN], [IN PROGRESS], [DONE]. Close an issue by setting [DONE] "
                  "and adding a dated comment.")

TITLE_RE = re.compile(r"^#(\d+)\s+\[(OPEN|IN PROGRESS|DONE)\]\s+(.*?)"
                      r"(?:\s+-\s+(@\S+(?:\s+@\S+)*))?\s*$", re.UNICODE)
NEXT_RE = re.compile(r"next new issue is #(\d+)", re.IGNORECASE)
COMMENT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+(@\S+(?:\s+@\S+)*)\s*:\s*(.*)$", re.UNICODE)
ID_RE = re.compile(r"\bid(\d+)\b")
REF_RE = re.compile(r"#(\d+)")
PARENT_RE = re.compile(r"see\s+#(\d+)", re.IGNORECASE)
FIELD_PREFIXES = (("severity", "Severity:"), ("finding", "Finding:"),
                  ("todo", "To do:"), ("related", "Related:"))
ARCHIVE_RULES = "Archived issues use fixed numbers. Never renumber."
ARCHIVE_RE = re.compile(r"archived issues use fixed numbers", re.IGNORECASE)


class BoardError(Exception):
    """A plan cannot be made (bad input, unknown issue)."""


class BoardChanged(Exception):
    """The note text changed since it was read. Nothing was written."""


# ---------------------------------------------------------------- paragraphs

def split_paragraphs(text):
    """Return [(start, text)] for each paragraph, with offsets in the raw text.

    Accepts "\\r", "\\r\\n" and "\\n" breaks. The empty piece after a final
    break is not a paragraph (Revit throws on a TextRange there).
    """
    out = []
    i = 0
    start = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\r" or c == "\n":
            out.append((start, text[start:i]))
            if c == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            start = i + 1
        i += 1
    if start < n:
        out.append((start, text[start:]))
    return out


def text_sha1(text):
    if not isinstance(text, bytes):
        text = text.encode("utf-8")
    return hashlib.sha1(text).hexdigest()


def saved_document_identity(document):
    path = document.PathName
    project = document.ProjectInformation
    if not path or project is None or not project.UniqueId:
        raise ValueError("Open the saved project used for this plan.")
    return {"project_uid": str(project.UniqueId),
            "path_sha256": hashlib.sha256(path.encode("utf-8")).hexdigest()}


def id_spans(text):
    """[(offset, length)] of every element id written as id<number>."""
    return [(m.start(), m.end() - m.start()) for m in ID_RE.finditer(text)]


def unescape(text):
    """Undo the read script's ASCII escaping (\\uXXXX and doubled backslashes)."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "\\":
                out.append("\\")
                i += 2
                continue
            if nxt == "u" and i + 6 <= n:
                try:
                    out.append(unichr_(int(text[i + 2:i + 6], 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
        out.append(c)
        i += 1
    return "".join(out)


def unichr_(code):
    try:
        return unichr(code)  # noqa: F821  (IronPython 2.7)
    except NameError:
        return chr(code)


# ---------------------------------------------------------------- parsing

def _strip_bullet(line):
    s = line.strip()
    if s.startswith("- "):
        s = s[2:].strip()
    return s


def classify(line):
    """Return (kind, value) for one paragraph of the board."""
    raw = line.strip()
    if not raw:
        return "blank", ""
    m = TITLE_RE.match(raw)
    if m:
        return "title", m
    s = _strip_bullet(raw)
    m = COMMENT_RE.match(s)
    if m:
        return "comment", m
    low = s.lower()
    for kind, prefix in FIELD_PREFIXES:
        if low.startswith(prefix.lower()):
            return kind, s[len(prefix):].strip()
    return "detail", s


def parse_related(value):
    """'#2, #5. Path: see #5.' -> ([2, 5], 5). Numbers after the first '. ' are not links."""
    head = value
    rest = ""
    m = re.search(r"\.(\s|$)", value)
    if m:
        head = value[:m.start()]
        rest = value[m.end():]
    related = [int(x) for x in REF_RE.findall(head)]
    pm = PARENT_RE.search(rest) or PARENT_RE.search(head)
    parent = int(pm.group(1)) if pm else None
    if parent is not None and PARENT_RE.search(head):
        related = [r for r in related if r != parent] or related
    return related, parent


def _new_issue(m, index):
    assignees = m.group(4).split() if m.group(4) else []
    return {"number": int(m.group(1)), "status": m.group(2), "title": m.group(3).strip(),
            "assignees": assignees, "severity": [], "findings": [], "todos": [],
            "comments": [], "related": [], "parent": None, "element_ids": [],
            "first_para": index, "last_para": index, "related_para": None,
            "lines": []}


def parse_board(text, formats=None):
    """Parse board text into {"header", "issues", "paragraphs", "warnings"}.

    `formats` is optional: one dict per paragraph (list, indent, bold) as the
    read script returns it. It is only copied onto each paragraph record.
    """
    paras = split_paragraphs(text)
    header = {"title": "", "lines": [], "next_number": None, "next_para": None,
              "archive": False}
    issues = []
    records = []
    warnings = []
    current = None
    last_field = None
    for idx, (start, line) in enumerate(paras):
        kind, val = classify(line)
        rec = {"index": idx, "start": start, "text": line, "kind": kind}
        if formats and idx < len(formats):
            rec["format"] = formats[idx]
        records.append(rec)
        if kind == "title":
            current = _new_issue(val, idx)
            issues.append(current)
            last_field = None
            continue
        if current is None:
            if kind != "blank":
                # Header lines keep header formatting (list None, indent 0) on edits.
                rec["kind"] = "rules" if header["title"] else "header"
                if not header["title"]:
                    header["title"] = line.strip()
                header["lines"].append(line.strip())
                if ARCHIVE_RE.search(line):
                    header["archive"] = True
                m = NEXT_RE.search(line)
                if m and header["next_number"] is None:
                    header["next_number"] = int(m.group(1))
                    header["next_para"] = idx
            continue
        if kind == "blank":
            continue
        current["last_para"] = idx
        current["lines"].append({"kind": kind, "text": _strip_bullet(line), "index": idx})
        current["element_ids"].extend(int(x) for x in ID_RE.findall(line))
        if kind == "comment":
            current["comments"].append({"date": val.group(1), "user": val.group(2),
                                        "text": val.group(3)})
        elif kind == "severity":
            current["severity"].append(val)
        elif kind == "finding":
            current["findings"].append(val)
        elif kind == "todo":
            current["todos"].append(val)
        elif kind == "related":
            rel, parent = parse_related(val)
            for r in rel:
                if r not in current["related"]:
                    current["related"].append(r)
            if parent is not None:
                current["parent"] = parent
            current["related_para"] = idx
        elif kind == "detail":
            target = {"severity": "severity", "todo": "todos"}.get(last_field, "findings")
            current[target].append(val)
        if kind in ("severity", "finding", "todo"):
            last_field = kind
    seen = {}
    for iss in issues:
        if iss["number"] in seen:
            warnings.append("issue #%d appears twice" % iss["number"])
        seen[iss["number"]] = True
    if header["next_number"] is None and not header["archive"]:
        warnings.append("header has no 'next new issue is #N' line")
    elif (issues and header["next_number"] is not None
          and header["next_number"] <= max(i["number"] for i in issues)):
        warnings.append("next new issue #%d is not above the highest issue #%d"
                        % (header["next_number"], max(i["number"] for i in issues)))
    for a, b in check_related_symmetry({"issues": issues}):
        warnings.append("#%d lists #%d in Related, but #%d does not list #%d" % (a, b, b, a))
    return {"header": header, "issues": issues, "paragraphs": records, "warnings": warnings}


def find_issue(board, number):
    for iss in board["issues"]:
        if iss["number"] == number:
            return iss
    raise BoardError("issue #%d is not on the board" % number)


def check_related_symmetry(board):
    """[(a, b)] where #a lists #b in Related but #b does not list #a (b must exist)."""
    rel = dict((i["number"], i["related"]) for i in board["issues"])
    out = []
    for a in sorted(rel):
        for b in rel[a]:
            if b in rel and a not in rel[b]:
                out.append((a, b))
    return out


def summary(board):
    """Counts only (no text): safe to print or return from Revit."""
    issues = board["issues"]
    by_status = dict((s, 0) for s in STATUSES)
    for i in issues:
        by_status[i["status"]] += 1
    return {"issues": len(issues), "next_number": board["header"]["next_number"],
            "by_status": by_status,
            "comments": sum(len(i["comments"]) for i in issues),
            "severity_lines": sum(1 for i in issues for ln in i["lines"] if ln["kind"] == "severity"),
            "related_lines": sum(1 for i in issues if i["related_para"] is not None),
            "with_parent": sum(1 for i in issues if i["parent"] is not None),
            "element_ids": sum(len(i["element_ids"]) for i in issues),
            "asymmetric_links": len(check_related_symmetry(board)),
            "numbers": [i["number"] for i in issues],
            "paragraphs": len(board["paragraphs"]),
            "warnings": len(board["warnings"])}


# ---------------------------------------------------------------- rendering

def para(text, kind, indent, bold=False):
    """One paragraph of the model. list is "bullet" when indent > 0."""
    return {"text": text, "kind": kind, "indent": indent,
            "list": "bullet" if indent > 0 else "none", "bold": bold,
            "underline": id_spans(text)}


def blank_para():
    return para("", "blank", 0)


def title_text(number, status, title, assignees):
    if status not in STATUSES:
        raise BoardError("status must be one of %s" % ", ".join(STATUSES))
    who = " ".join(_at(a) for a in (assignees or ["TBD"]))
    return "#%d [%s] %s - %s" % (number, status, title.strip(), who)


def _at(name):
    name = name.strip()
    return name if name.startswith("@") else "@" + name


def related_text(related, parent=None):
    rel = sorted(set(related))
    s = "Related: " + ", ".join("#%d" % r for r in rel)
    if parent is not None:
        s += ". Path: see #%d." % parent
    return s


def comment_text(date, user, text):
    return "%s %s: %s" % (date, _at(user), text.strip())


def render_header(title_line, next_number):
    return [para(title_line, "header", 0, bold=True),
            para(RULES_TEMPLATE % next_number, "rules", 0)]


def render_issue(issue):
    """Paragraphs for one issue dict (number, status, title, assignees, severity,
    findings, todos, comments, related, parent). A finding or to-do may be a
    list [line, detail1, detail2]; details go to indent 2."""
    out = [para(title_text(issue["number"], issue.get("status", "OPEN"), issue["title"],
                           issue.get("assignees")), "title", 0, bold=True)]
    sev = issue.get("severity")
    for s in ([sev] if isinstance(sev, str) else (sev or [])):
        out.append(para("Severity: " + s, "severity", 1))
    for label, kind, key in (("Finding: ", "finding", "findings"), ("To do: ", "todo", "todos")):
        for item in issue.get(key) or []:
            rows = item if isinstance(item, (list, tuple)) else [item]
            out.append(para(label + rows[0], kind, 1))
            for d in rows[1:]:
                out.append(para(d, "detail", 2))
    for c in issue.get("comments") or []:
        out.append(para(comment_text(c["date"], c["user"], c["text"]), "comment", 1))
    if issue.get("related") or issue.get("parent") is not None:
        rel = list(issue.get("related") or [])
        if issue.get("parent") is not None and issue["parent"] not in rel:
            rel.append(issue["parent"])
        out.append(para(related_text(rel, issue.get("parent")), "related", 1))
    return out


def render_board(title_line, issues, next_number=None):
    nums = [i["number"] for i in issues]
    if len(nums) != len(set(nums)):
        raise BoardError("issue numbers must be unique")
    if next_number is None:
        next_number = (max(nums) + 1) if nums else 1
    if nums and next_number <= max(nums):
        raise BoardError("next new issue number must be above every issue number")
    out = render_header(title_line, next_number)
    for iss in issues:
        out.append(blank_para())
        out.extend(render_issue(iss))
    return out


def paragraphs_text(paras):
    return PARA_BREAK.join(p["text"] for p in paras)


def format_ops(paras, base, text_len):
    """Format operations for paragraphs that start at offset `base` of a text of
    length `text_len`. Each range covers the paragraph text plus its break when
    one follows. A range never starts at or past the end of the text."""
    ops = []
    pos = base
    for p in paras:
        n = len(p["text"])
        length = n + 1 if pos + n < text_len else n
        if length > 0 and pos < text_len:
            length = min(length, text_len - pos)
            ops.append({"op": "para", "start": pos, "length": length, "list": p["list"],
                        "indent": p["indent"], "bold": bool(p["bold"])})
            if n > 0:
                ops.append({"op": "underline", "start": pos, "length": n, "value": False})
            for off, ln in p["underline"]:
                ops.append({"op": "underline", "start": pos + off, "length": ln, "value": True})
        pos += n + 1
    return ops


def plan_create(title_line, issues, next_number=None):
    paras = render_board(title_line, issues, next_number)
    text = paragraphs_text(paras)
    return {"kind": "issue-board-plan", "mode": "create", "final_text": text,
            "formats": format_ops(paras, 0, len(text)), "edits": [],
            "expected_sha1": None}


# ---------------------------------------------------------------- edit plans

def _default_model(rec):
    """Paragraph model for an existing paragraph, keeping its read format if known."""
    kind = rec["kind"]
    text = rec["text"]
    fmt = rec.get("format") or {}
    if kind in ("title", "header"):
        p = para(text, kind, 0, bold=True)
    elif kind in ("blank", "rules"):
        p = para(text, kind, 0)
    elif kind == "detail":
        p = para(text, kind, 2)
    else:
        p = para(text, kind, 1)
    if "indent" in fmt:
        p["indent"] = int(fmt["indent"])
    if "list" in fmt:
        p["list"] = "none" if str(fmt["list"]).lower() == "none" else "bullet"
    return p


class _Planner(object):
    """Collects paragraph replacements and deletions against one read of the board text.

    A batch applies several operations to one planner, so the planner tracks
    state that the first parse cannot see: the running next number, the
    current Related lines, and paragraphs that a block replacement deleted.
    """

    def __init__(self, text, formats=None):
        self.text = text
        self.board = parse_board(text, formats)
        self.repl = {}  # paragraph index -> list of paragraph models
        self.deletions = []  # (start, old text) spans, paragraph breaks included
        self.next_number = self.board["header"]["next_number"]
        self._rel = {}  # number -> (related list, parent)
        self._rel_model = {}  # number -> Related paragraph model, once placed
        self._block_owner = {}  # deleted paragraph index -> replacement paragraph index
        for iss in self.board["issues"]:
            self._rel[iss["number"]] = (list(iss["related"]), iss["parent"])

    def models_at(self, idx):
        if idx not in self.repl:
            self.repl[idx] = [_default_model(self.board["paragraphs"][idx])]
        return self.repl[idx]

    def _append_models(self, idx):
        """Models list to extend when inserting after paragraph idx.

        When idx was deleted by a block replacement, the insert goes after
        the replacement block instead, so it lands in the right place.
        """
        owner = self._block_owner.get(idx)
        if owner is not None:
            return self.models_at(owner)
        return self.models_at(idx)

    def replace(self, idx, new_text, kind=None):
        models = self.models_at(idx)
        old = models[0]
        p = para(new_text, kind or old["kind"], old["indent"], old["bold"])
        p["list"] = old["list"]
        models[0] = p

    def insert_after(self, idx, new_paras):
        rec = self.board["paragraphs"][idx]
        if not rec["text"]:
            raise BoardError("cannot anchor an insert on a blank paragraph")
        self._append_models(idx).extend(new_paras)

    def remove_span(self, start, end):
        """Delete text[start:end] (breaks included). Overlap is checked in build."""
        if start < 0 or end <= start or end > len(self.text):
            raise BoardError("cannot delete that text range")
        self.deletions.append((start, self.text[start:end]))

    def replace_block(self, first_idx, last_idx, new_paras):
        """Replace paragraphs first_idx..last_idx with new_paras.

        The first paragraph carries the new block; the rest are deleted with
        their breaks, so no blank paragraphs are left behind. Later inserts
        that anchor on a deleted paragraph follow the new block instead.
        """
        recs = self.board["paragraphs"]
        if not recs[first_idx]["text"]:
            raise BoardError("cannot replace a blank paragraph")
        self.repl[first_idx] = list(new_paras)
        for idx in range(first_idx + 1, last_idx + 1):
            self._block_owner[idx] = first_idx
        if last_idx > first_idx:
            start = recs[first_idx + 1]["start"]
            last_rec = recs[last_idx]
            end = last_rec["start"] + len(last_rec["text"])
            tail = self.text[end:end + 2]
            if tail == "\r\n":
                end += 2
            elif end < len(self.text) and self.text[end] in "\r\n":
                end += 1
            self.remove_span(start, end)

    def related_of(self, number):
        return list(self._rel[number][0])

    def parent_of(self, number):
        return self._rel[number][1]

    def set_related_line(self, iss, related, parent):
        """Write the Related line, updating it in place when one was already
        placed in this plan (a second insert would make two Related lines)."""
        new = related_text(related, parent)
        number = iss["number"]
        if number in self._rel_model:
            m = self._rel_model[number]
            p = para(new, "related", m["indent"], m["bold"])
            p["list"] = m["list"]
            m.clear()
            m.update(p)
        elif iss["related_para"] is not None:
            self.replace(iss["related_para"], new, "related")
            self._rel_model[number] = self.models_at(iss["related_para"])[0]
        else:
            self.insert_after(iss["last_para"], [para(new, "related", 1)])
            self._rel_model[number] = self._append_models(iss["last_para"])[-1]
        self._rel[number] = (list(related), parent)

    def add_comment(self, iss, date, user, comment):
        """Add a dated comment after the last line that is not the Related line.

        When a Related line was already placed on the anchor paragraph by an
        earlier operation in this plan, the comment goes before it, not after.
        """
        if "\r" in comment or "\n" in comment:
            raise BoardError("a comment must be one paragraph")
        p = para(comment_text(date, user, comment), "comment", 1)
        lines = [ln for ln in iss["lines"] if ln["kind"] != "related"]
        anchor = lines[-1]["index"] if lines else iss["first_para"]
        models = self._append_models(anchor)
        for j in range(1, len(models)):
            if models[j]["kind"] == "related":
                models.insert(j, p)
                return
        models.append(p)

    def build(self, action):
        ops = []  # (start, old, new, paragraph models or None for a deletion)
        for idx in sorted(self.repl):
            rec = self.board["paragraphs"][idx]
            if not rec["text"]:
                raise BoardError("cannot replace a blank paragraph")
            ops.append((rec["start"], rec["text"], paragraphs_text(self.repl[idx]),
                        self.repl[idx]))
        for start, old in self.deletions:
            ops.append((start, old, "", None))
        ops.sort(key=lambda o: o[0])
        for prev, cur in zip(ops, ops[1:]):
            if cur[0] < prev[0] + len(prev[1]):
                raise BoardError("plan edits overlap")
        final = self.text
        for start, old, new, _ in sorted(ops, key=lambda o: -o[0]):
            final = final[:start] + new + final[start + len(old):]
        # Format ops in final-text coordinates.
        formats = []
        shift = 0
        for start, old, new, paras in ops:
            if paras is not None:
                formats.extend(format_ops(paras, start + shift, len(final)))
            shift += len(new) - len(old)
        edits = [{"start": s, "old": o, "new": n} for s, o, n, _ in ops]
        return {"kind": "issue-board-plan", "mode": "edit", "action": action,
                "expected_sha1": text_sha1(self.text), "expected_length": len(self.text),
                "edits": edits, "final_text": final, "formats": formats}


def _bump_header(pl, new_next):
    h = pl.board["header"]
    if h["next_para"] is None:
        raise BoardError("the header has no 'next new issue is #N' line; fix the header first")
    rec = pl.board["paragraphs"][h["next_para"]]
    new = NEXT_RE.sub("next new issue is #%d" % new_next, rec["text"], count=1)
    pl.replace(h["next_para"], new, "rules")


def _do_add(pl, issue):
    """Add one issue to a planner. Returns the new issue number."""
    board = pl.board
    number = pl.next_number
    if number is None:
        raise BoardError("the header has no 'next new issue is #N' line; fix the header first")
    existing = [i["number"] for i in board["issues"]]
    if number in existing or (existing and number <= max(existing)):
        raise BoardError("next new issue #%d is already used; fix the header by hand" % number)
    new = dict(issue)
    new["number"] = number
    for r in list(new.get("related") or []) + ([new["parent"]] if new.get("parent") else []):
        find_issue(board, r)
    paras = [blank_para()] + render_issue(new)
    anchors = [r for r in board["paragraphs"] if r["text"]]
    if not anchors:
        raise BoardError("the board is empty")
    last = anchors[-1]["index"]
    _bump_header(pl, number + 1)
    pl.next_number = number + 1
    # Back-links first: when the last issue gets a new Related line, it shares
    # the anchor paragraph with the new issue and must come before it.
    for r in sorted(set(list(new.get("related") or []) + ([new["parent"]] if new.get("parent") else []))):
        other = find_issue(board, r)
        rel = pl.related_of(r)
        if number not in rel:
            pl.set_related_line(other, rel + [number], pl.parent_of(r))
    pl.insert_after(last, paras)
    return number


def plan_add_issue(text, issue, formats=None):
    """Add one issue at the end with number = the header's next number.
    Existing issues keep their numbers. Related links are made symmetric."""
    pl = _Planner(text, formats)
    number = _do_add(pl, issue)
    plan = pl.build("add #%d" % number)
    plan["number"] = number
    return plan


def _do_set_status(pl, number, status, date, user, comment):
    """Change the status of #number and add a dated comment (before Related)."""
    if status not in STATUSES:
        raise BoardError("status must be one of %s" % ", ".join(STATUSES))
    if not comment or not comment.strip():
        raise BoardError("a status change needs a dated comment")
    iss = find_issue(pl.board, number)
    pl.replace(iss["first_para"], title_text(number, status, iss["title"], iss["assignees"]),
               "title")
    pl.add_comment(iss, date, user, comment)


def plan_set_status(text, number, status, date, user, comment, formats=None):
    pl = _Planner(text, formats)
    _do_set_status(pl, number, status, date, user, comment)
    return pl.build("#%d -> %s" % (number, status))


def _do_comment(pl, number, date, user, comment):
    iss = find_issue(pl.board, number)
    pl.add_comment(iss, date, user, comment)


def plan_comment(text, number, date, user, comment, formats=None):
    pl = _Planner(text, formats)
    _do_comment(pl, number, date, user, comment)
    return pl.build("comment on #%d" % number)


def _do_relate(pl, a, b):
    """Link #a and #b both ways."""
    if a == b:
        raise BoardError("an issue cannot relate to itself")
    ia = find_issue(pl.board, a)
    ib = find_issue(pl.board, b)
    for x, y in ((ia, b), (ib, a)):
        rel = pl.related_of(x["number"])
        if y not in rel:
            pl.set_related_line(x, rel + [y], pl.parent_of(x["number"]))


def plan_relate(text, a, b, formats=None):
    pl = _Planner(text, formats)
    _do_relate(pl, a, b)
    return pl.build("relate #%d and #%d" % (a, b))


# ---------------------------------------------------------------- batch

def _batch_number(op, key):
    try:
        return int(op[key])
    except (KeyError, TypeError, ValueError):
        raise BoardError("batch operation %r needs an integer %s" % (op.get("op"), key))


def _batch_text(op, key):
    val = op.get(key)
    if not isinstance(val, str) or not val.strip():
        raise BoardError("batch operation %r needs a non-empty %s" % (op.get("op"), key))
    return val


def plan_batch(text, ops, formats=None):
    """Combine status / comment / relate / add operations into one plan.

    One plan means one SHA guard and one Keep prompt in Revit, however many
    operations the batch holds. An operation cannot target an issue that an
    earlier operation in the same batch added: the new issue exists only in
    the plan, not in the parsed board, so find_issue cannot see it yet.
    """
    if not isinstance(ops, (list, tuple)) or not ops:
        raise BoardError("a batch needs a non-empty list of operations")
    pl = _Planner(text, formats)
    parts = []
    for op in ops:
        if not isinstance(op, dict):
            raise BoardError("each batch operation must be an object")
        kind = op.get("op")
        if kind == "status":
            number = _batch_number(op, "number")
            _do_set_status(pl, number, _batch_text(op, "status"),
                           _batch_text(op, "date"), _batch_text(op, "user"),
                           _batch_text(op, "comment"))
            parts.append("#%d -> %s" % (number, op["status"]))
        elif kind == "comment":
            number = _batch_number(op, "number")
            _do_comment(pl, number, _batch_text(op, "date"), _batch_text(op, "user"),
                        _batch_text(op, "comment"))
            parts.append("comment #%d" % number)
        elif kind == "relate":
            a = _batch_number(op, "a")
            b = _batch_number(op, "b")
            _do_relate(pl, a, b)
            parts.append("relate #%d #%d" % (a, b))
        elif kind == "add":
            issue = op.get("issue")
            if not isinstance(issue, dict):
                raise BoardError("an add operation needs an issue object")
            parts.append("add #%d" % _do_add(pl, issue))
        else:
            raise BoardError("unknown batch operation: %r" % (kind,))
    plan = pl.build("batch: " + ", ".join(parts))
    plan["operations"] = parts
    return plan


# ---------------------------------------------------------------- archive

def _issue_block_span(board, iss):
    """(first, last) paragraph index of an issue block, blank separator included."""
    first = iss["first_para"]
    if first > 0 and board["paragraphs"][first - 1]["kind"] == "blank":
        first -= 1
    return first, iss["last_para"]


def _delete_span(pl, first_idx, last_idx):
    """Delete paragraphs first_idx..last_idx with the break after the last one."""
    recs = pl.board["paragraphs"]
    start = recs[first_idx]["start"]
    last_rec = recs[last_idx]
    end = last_rec["start"] + len(last_rec["text"])
    tail = pl.text[end:end + 2]
    if tail == "\r\n":
        end += 2
    elif end < len(pl.text) and pl.text[end] in "\r\n":
        end += 1
    pl.remove_span(start, end)


def plan_archive_main(text, numbers, formats=None):
    """Edit plan that cuts the given issues out of the main board."""
    pl = _Planner(text, formats)
    for n in sorted(numbers):
        iss = find_issue(pl.board, n)
        first, last = _issue_block_span(pl.board, iss)
        _delete_span(pl, first, last)
    return pl.build("archive " + ", ".join("#%d" % n for n in sorted(numbers)))


def _archive_issue_models(board, iss):
    """Paragraph models for one archived issue, keeping its read formats."""
    return [_default_model(rec)
            for rec in board["paragraphs"][iss["first_para"]:iss["last_para"] + 1]]


def _archive_title_index(board):
    for rec in board["paragraphs"]:
        if rec["text"]:
            return rec["index"]
    return None


def plan_archive_note(main_board, numbers, archive_text=None, archive_formats=None,
                      title_line=None):
    """Plan for the archive note. Returns (plan, title, mode).

    mode "create": the archive note does not exist yet. The agent creates it
    with apply_board.py create, to the right of the board, same type and width.
    mode "append": the archive note exists; new blocks go in number order.
    A note without the archive marker gets the marker line in the same plan,
    so the parser stops warning about it (this covers notes that an older
    hand script created without the marker).
    """
    models = []
    for n in sorted(numbers):
        models.append(blank_para())
        models.extend(_archive_issue_models(main_board, find_issue(main_board, n)))
    if not archive_text:
        title = title_line or ("ARCHIVE - " + main_board["header"]["title"])
        paras = [para(title, "header", 0, bold=True), para(ARCHIVE_RULES, "rules", 0)]
        paras.extend(models)
        text = paragraphs_text(paras)
        plan = {"kind": "issue-board-plan", "mode": "create", "action": "create archive",
                "final_text": text, "formats": format_ops(paras, 0, len(text)),
                "edits": [], "expected_sha1": None}
        return plan, title, "create"
    if title_line is not None:
        raise BoardError("--title only applies when the archive note is created")
    archive_board = parse_board(archive_text, archive_formats)
    if archive_board["header"]["next_number"] is not None:
        raise BoardError("the archive file is a board, not an archive note")
    for n in numbers:
        if any(i["number"] == n for i in archive_board["issues"]):
            raise BoardError("issue #%d is already in the archive" % n)
    pl = _Planner(archive_text, archive_formats)
    if not archive_board["header"]["archive"]:
        title_idx = _archive_title_index(archive_board)
        if title_idx is None:
            raise BoardError("the archive note has no title line")
        pl.insert_after(title_idx, [para(ARCHIVE_RULES, "rules", 0)])
    existing = archive_board["issues"]
    # The last header paragraph (title, then the rules line when present).
    # New blocks that sort before every existing issue go after it, never
    # between the title and the rules line: a block inserted there would
    # swallow the rules line into the first issue.
    header_end = None
    for rec in archive_board["paragraphs"]:
        if rec["kind"] in ("header", "rules"):
            header_end = rec["index"]
        else:
            break
    if header_end is None:
        raise BoardError("the archive note has no title line")
    for n in sorted(numbers):
        anchor = None
        for e in existing:
            if e["number"] > n:
                break
            anchor = e["last_para"]
        if anchor is None:
            anchor = header_end
        pl.insert_after(anchor, [blank_para()] +
                        _archive_issue_models(main_board, find_issue(main_board, n)))
    plan = pl.build("append to archive: " + ", ".join("#%d" % n for n in sorted(numbers)))
    return plan, archive_board["header"]["title"], "append"


def plan_archive(main_text, status="DONE", main_formats=None, archive_text=None,
                 archive_formats=None, title_line=None):
    """Archive every issue with the given status. Returns both plans plus
    checks: the main board plan, the archive plan, parent warnings (an open
    issue whose parent moves to the archive), and the warnings of both notes
    after the change. The agent applies the board plan first, then the
    archive plan; each plan has its own SHA guard and Keep prompt."""
    if status not in STATUSES:
        raise BoardError("status must be one of %s" % ", ".join(STATUSES))
    main_board = parse_board(main_text, main_formats)
    numbers = sorted(i["number"] for i in main_board["issues"] if i["status"] == status)
    if not numbers:
        raise BoardError("no issues with status %s on the board" % status)
    board_plan = plan_archive_main(main_text, numbers, main_formats)
    archive_plan, title, mode = plan_archive_note(main_board, numbers, archive_text,
                                                  archive_formats, title_line)
    parent_warnings = []
    for iss in main_board["issues"]:
        if iss["status"] != status and iss["parent"] in numbers:
            parent_warnings.append("#%d has parent #%d, which moves to the archive"
                                   % (iss["number"], iss["parent"]))
    return {"archived": numbers, "status": status, "board_plan": board_plan,
            "archive_plan": archive_plan, "archive_mode": mode, "archive_title": title,
            "parent_warnings": parent_warnings,
            "board_warnings_after": parse_board(board_plan["final_text"])["warnings"],
            "archive_warnings": parse_board(archive_plan["final_text"])["warnings"]}


# ---------------------------------------------------------------- replace

def _field_block(board, iss, field):
    """(first, last) paragraph index of one Finding or To do block, or None.

    A block is the field lines plus their detail rows. Detail rows belong to
    the field line above them. Anything else inside the span is an error,
    not a silent skip."""
    last_field = None
    first = None
    last = None
    for ln in iss["lines"]:
        k = ln["kind"]
        if k in ("severity", "finding", "todo"):
            last_field = k
        if k == field or (k == "detail" and last_field == field):
            if first is None:
                first = ln["index"]
            last = ln["index"]
    if first is None:
        return None
    for idx in range(first, last + 1):
        if board["paragraphs"][idx]["kind"] not in (field, "detail"):
            raise BoardError("the %s block of #%d is not contiguous" % (field, iss["number"]))
    return first, last


def plan_replace_field(text, number, field, lines, formats=None):
    """Replace the Finding or To do block of one issue with new lines.

    lines is a list of strings, or [line, detail, detail] groups. The title,
    severity, comments, Related line and the other field stay untouched.
    """
    field = field.strip().lower().rstrip(":")
    if field == "to do":
        field = "todo"
    if field not in ("finding", "todo"):
        raise BoardError("field must be finding or todo")
    items = lines["lines"] if isinstance(lines, dict) else lines
    if not isinstance(items, (list, tuple)) or not items:
        raise BoardError("replace needs at least one line")
    label = "Finding: " if field == "finding" else "To do: "
    new_paras = []
    for item in items:
        rows = item if isinstance(item, (list, tuple)) else [item]
        if not rows or any(not isinstance(r, str) or not r.strip() for r in rows):
            raise BoardError("each replacement line must be non-empty text")
        if any("\r" in r or "\n" in r for r in rows):
            raise BoardError("a replacement line must be one paragraph")
        new_paras.append(para(label + rows[0].strip(), field, 1))
        for d in rows[1:]:
            new_paras.append(para(d.strip(), "detail", 2))
    pl = _Planner(text, formats)
    iss = find_issue(pl.board, number)
    span = _field_block(pl.board, iss, field)
    if span is None:
        raise BoardError("issue #%d has no %s block" % (number, label.strip()))
    pl.replace_block(span[0], span[1], new_paras)
    return pl.build("replace #%d %s" % (number, field))


# ---------------------------------------------------------------- recheck

def recheck_inventory(board):
    """{issue number: [element ids]} for issues that mention element ids."""
    return dict((i["number"], list(i["element_ids"])) for i in board["issues"]
                if i["element_ids"])


def format_recheck_suggestions(checks):
    """Suggested comments from live existence checks. Never an edit.

    checks is a list of {"number", "id", "exists", "kind", "detail"}. One
    suggested comment per issue, listing each id as found or missing."""
    by_issue = {}
    for c in checks:
        by_issue.setdefault(c["number"], []).append(c)
    out = []
    for number in sorted(by_issue):
        parts = []
        for c in sorted(by_issue[number], key=lambda x: x["id"]):
            if c["exists"]:
                s = "id%d exists" % c["id"]
                if c.get("kind"):
                    s += " (%s" % c["kind"]
                    if c.get("detail"):
                        s += ", %s" % c["detail"]
                    s += ")"
            else:
                s = "id%d is missing" % c["id"]
            parts.append(s)
        out.append({"number": number, "comment": "Recheck: " + "; ".join(parts) + "."})
    return out


# ---------------------------------------------------------------- apply (Revit side)

def check_guard(current_text, plan):
    """Stop when the note text is not the text the plan was made from."""
    sha = plan.get("expected_sha1")
    if sha is None:
        return
    if text_sha1(current_text) != sha:
        raise BoardChanged("The note text changed since it was read (for example a manual edit "
                           "in Revit). Nothing was written. Read the board again.")


def apply_formats(ft, ops, make_range, list_type):
    """Apply format ops to a FormattedText. make_range(start, length) builds a
    TextRange; list_type("bullet"|"none") returns the ListType value."""
    n = len(ft.GetPlainText())
    done = 0
    for op in ops:
        start = op["start"]
        length = min(op["length"], n - start)
        if start >= n or length <= 0:
            continue
        rng = make_range(start, length)
        if op["op"] == "para":
            ft.SetListType(rng, list_type(op["list"]))
            ft.SetIndentLevel(rng, op["indent"])
            ft.SetBoldStatus(rng, op["bold"])
        else:
            ft.SetUnderlineStatus(rng, op["value"])
        done += 1
    return done


def apply_plan(ft, plan, make_range, list_type):
    """Apply an edit plan to a FormattedText in place. Raises BoardChanged (and
    writes nothing) when the guard or any anchor check fails."""
    check_guard(ft.GetPlainText(), plan)
    edits = sorted(plan["edits"], key=lambda e: -e["start"])
    prev = None
    for e in edits:
        if prev is not None and e["start"] + len(e["old"]) > prev:
            raise BoardError("plan edits overlap")
        prev = e["start"]
    # Check every anchor before the first write.
    for e in edits:
        if "\r" in e["old"] or "\n" in e["old"]:
            # A span over several paragraphs: Revit Find is a single-paragraph
            # search, so check the slice itself and use the planned range.
            plain = ft.GetPlainText()
            if plain[e["start"]:e["start"] + len(e["old"])] != e["old"]:
                raise BoardChanged("Text '%s' is not at offset %d any more. Nothing was written."
                                   % (e["old"][:40], e["start"]))
        else:
            rng = ft.Find(e["old"], e["start"], True, False)
            if rng is None or _range_start(rng) != e["start"]:
                raise BoardChanged("Text '%s' is not at offset %d any more. Nothing was written."
                                   % (e["old"][:40], e["start"]))
    for e in edits:
        if "\r" in e["old"] or "\n" in e["old"]:
            rng = make_range(e["start"], len(e["old"]))
        else:
            rng = ft.Find(e["old"], e["start"], True, False)
        ft.SetPlainText(rng, e["new"])
    if ft.GetPlainText() != plan["final_text"]:
        raise BoardChanged("The text after the edits is not the planned text.")
    return apply_formats(ft, plan["formats"], make_range, list_type)


def _range_start(rng):
    return rng.Start if hasattr(rng, "Start") else rng[0]
