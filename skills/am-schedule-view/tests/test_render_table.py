"""render-table.ps1: the plain view (issue #296) and -RunId (issue #297)."""
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
RENDER = SKILL / "scripts" / "render-table.ps1"
TEMPLATE = SKILL / "assets" / "viewer-template.html"
FIXTURES = SKILL / "assets" / "fixtures"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")

needs_powershell = pytest.mark.skipif(POWERSHELL is None, reason="render-table.ps1 needs PowerShell.")


def render(*args):
    return subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(RENDER)]
                          + [str(a) for a in args], capture_output=True, text=True)


class PlainView(HTMLParser):
    """Collect the text and the table rows of the page as a browser with no scripts shows it."""

    def __init__(self):
        super().__init__()
        self.depth = 0          # > 0 inside <div id="static">
        self.in_script = False
        self.text = []
        self.rows = []
        self.row = None
        self.tags = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script":
            self.in_script = True
        if self.depth:
            if tag == "div":
                self.depth += 1
            self.tags.append((tag, a))
            if tag == "tr":
                self.row = {"class": a.get("class", ""), "cells": []}
            if tag in ("td", "th") and self.row is not None:
                self.row["cells"].append("")
        elif tag == "div" and a.get("id") == "static":
            self.depth = 1

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False
        if not self.depth:
            return
        if tag == "div":
            self.depth -= 1
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.depth and not self.in_script:
            self.text.append(data)
            if self.row is not None and self.row["cells"]:
                self.row["cells"][-1] += data


def plain_view(path):
    parser = PlainView()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def test_template_hides_the_plain_view_only_when_scripts_run():
    page = TEMPLATE.read_text(encoding="utf-8")
    assert page.count("__STATIC_HTML__") == 1
    assert page.index("__STATIC_HTML__") < page.index("__DATA_JSON__")
    assert 'className += " am-js"' in page
    assert "html:not(.am-js) #app" in page and ".am-js .static { display: none; }" in page
    assert 'var plain = $("static")' in page


@needs_powershell
def test_change_preview_rows_are_in_the_html_without_scripts(tmp_path):
    out = tmp_path / "preview.html"
    run = render("-Json", FIXTURES / "change-preview.sample.json", "-Out", out)
    assert run.returncode == 0, run.stdout + run.stderr
    html = out.read_text(encoding="utf-8")
    assert "__STATIC_HTML__" not in html
    view = plain_view(out)
    text = "".join(view.text)
    assert "Preview only. Nothing in Revit has changed yet." in text
    assert "Shift sheets A301+ up by one" in text
    changed = [r for r in view.rows if "d-changed" in r["class"]]
    sample = json.loads((FIXTURES / "change-preview.sample.json").read_text(encoding="utf-8"))
    expected = sum(1 for b, a in zip(sample["before"], sample["after"]) if b != a)
    assert len(changed) == expected
    i = next(i for i, (b, a) in enumerate(zip(sample["before"], sample["after"])) if b != a)
    first = changed[0]["cells"]
    assert first[1] == sample["before"][i][0]
    assert first[2] == sample["before"][i][1] + "/" + sample["after"][i][1]
    same = [r for r in view.rows if "d-same" in r["class"]]
    assert len(changed) + len(same) == len(sample["after"])
    assert re.search(r"Show \d+ unchanged", text)


@needs_powershell
def test_plain_view_escapes_model_text(tmp_path):
    hostile = '</script><img src=x onerror=alert(1)> __DATA_JSON__ & "q"'
    preview = {
        "kind": "change-preview", "title": hostile, "keyColumn": "Id",
        "columns": ["Id", "Name"], "changedColumns": ["Name"],
        "before": [["1", "Old"], ["2", "Gone"]], "after": [["1", hostile], ["3", "New"]],
        "warnings": [{"row": "1", "text": hostile}], "notes": [hostile],
        "params": {"start": hostile}, "steps": [["1", "Old", hostile]],
    }
    src = tmp_path / "p.json"
    src.write_text(json.dumps(preview), encoding="utf-8")
    out = tmp_path / "p.html"
    run = render("-Json", src, "-Out", out)
    assert run.returncode == 0, run.stdout + run.stderr
    html = out.read_text(encoding="utf-8")
    plain = html[html.index('<div class="static" id="static">'):html.index('<div class="app"')]
    assert "<img" not in plain and "</script" not in plain and "__DATA_JSON__" not in plain
    view = plain_view(out)
    assert hostile in "".join(view.text)
    kinds = sorted(r["class"].split()[0] for r in view.rows if r["class"].startswith("d-"))
    assert kinds == ["d-added", "d-changed", "d-removed"]
    # The embedded JSON is still intact for the interactive page.
    data = re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S).group(1)
    assert json.loads(data)["after"][0][1] == hostile


@needs_powershell
def test_schedules_and_compare_show_every_row(tmp_path):
    sample = json.loads((FIXTURES / "snowdon-schedules.sample.json").read_text(encoding="utf-8"))
    out = tmp_path / "s.html"
    fixture = FIXTURES / "snowdon-schedules.sample.json"
    run = render("-Json", fixture, "-Json2", fixture, "-Out", out)
    assert run.returncode == 0, run.stdout + run.stderr
    view = plain_view(out)
    text = "".join(view.text)
    total = sum(len(s["rows"]) + 1 for s in sample["schedules"])  # +1 heading row each
    assert len(view.rows) == 2 * total
    first = sample["schedules"][0]
    assert "[A] " + first["name"] in text and "[B] " + first["name"] in text


@needs_powershell
def test_schedule_list(tmp_path):
    listing = {"kind": "schedule-list", "document": "Project A",
               "schedules": [{"name": "Door Schedule", "id": 11, "category": "Doors", "kind": "regular",
                              "rows": 4, "onSheet": True, "sheets": ["A-601"]}]}
    src = tmp_path / "l.json"
    src.write_text(json.dumps(listing), encoding="utf-8")
    out = tmp_path / "l.html"
    assert render("-Json", src, "-Out", out).returncode == 0
    rows = plain_view(out).rows
    assert rows[1]["cells"] == ["Door Schedule", "Doors", "regular", "4", "Yes", "A-601", "11"]


def write_run(runs, folder, kind="schedule-list"):
    data = {"kind": kind, "document": "Project A", "schedules": []}
    run_dir = runs / folder
    run_dir.mkdir(parents=True)
    record = {"run_id": folder.split("-")[-1], "result": {"payload": json.dumps(data)}}
    (run_dir / "response.json").write_text(json.dumps(record), encoding="utf-8")


@needs_powershell
def test_run_id_finds_the_run_folder(tmp_path):
    runs = tmp_path / "runs"
    write_run(runs, "20261122-101500-abc123")
    write_run(runs, "20261122-101600-zzz999")
    out = tmp_path / "r.html"
    run = render("-RunId", "abc123", "-RunsDir", runs, "-Out", out)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "20261122-101500-abc123" in run.stdout
    assert out.exists()


@needs_powershell
@pytest.mark.parametrize("args", [
    ["-RunId", "nope"],
    ["-RunId", "..\\abc123"],
    ["-RunId", "abc123", "-Json", "x.json"],
    [],
])
def test_run_id_errors(tmp_path, args):
    runs = tmp_path / "runs"
    write_run(runs, "20261122-101500-abc123")
    run = render(*(args + ["-RunsDir", runs, "-Out", tmp_path / "r.html"]))
    assert run.returncode == 1
    assert "FAIL" in run.stdout
