# -*- coding: utf-8 -*-
"""Fixture text for am-shared-text-check tests.

The sample mirrors archi-magic issue #101: a short firm abbreviation
that also sits inside a common word, two personal cloud-sync folder
paths, one drive path, one UNC path, one email address, board @ names
and a first name that also exists as a common lowercase word.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))

SAMPLE = (
    "PROPOSED JOINT PROJECT RULES - for review\r\n"
    "Use project line styles, not office line styles.\r\n"
    "EASE of use matters. The AB team owns the link model.\r\n"
    "Link path: C:\\Users\\jdoe\\OneDrive\\Project\\link.rvt\r\n"
    "Old path: D:\\Users\\asmith\\docs\\notes.txt\r\n"
    "Base file: C:\\Project\\shared\\base.dwg\r\n"
    "Server file: \\\\fileserver\\shared\\cad\\base.dwg\r\n"
    "Contact jdoe@example.com for the link file.\r\n"
    "AUDIT - 2026-11-03 (by @user1)\r\n"
    "#1 [OPEN] Link path is personal - @user2\r\n"
    "   * To do: ask Will to repath. will do it next week.\r\n"
)
