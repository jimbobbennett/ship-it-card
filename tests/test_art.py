import copy
import re

import pytest

from shipit.art import BODY_LIMIT, art_prompt
from shipit.stats import build_stats


def _stats(pr_data, body):
    data = copy.deepcopy(pr_data)
    data.pr["body"] = body
    return build_stats(data)


def _body_clause(prompt):
    match = re.search(r'The change does: "([^"]*)"', prompt)
    return match.group(1) if match else None


def test_build_stats_maps_body(pr_data):
    assert _stats(pr_data, "Adds sparkles").pr_body == "Adds sparkles"
    assert _stats(pr_data, None).pr_body == ""
    assert build_stats(pr_data).pr_body == ""
    assert _stats(pr_data, "x").description == "Widgets."


def test_body_in_prompt(pr_data):
    prompt = art_prompt(_stats(pr_data, "Adds a **sparkle** mode, (fast)."))
    assert _body_clause(prompt) == "Adds a sparkle mode, (fast)."
    assert prompt.index("The change does") < prompt.index("Absolutely no text")
    assert "inspiration" in prompt


def test_different_bodies_differ_and_deterministic(pr_data):
    a = art_prompt(_stats(pr_data, "Adds sparkles"))
    b = art_prompt(_stats(pr_data, "Fixes a memory leak"))
    assert a != b
    assert a == art_prompt(_stats(pr_data, "Adds sparkles"))


@pytest.mark.parametrize("body", [None, "", "   \n\t ", "```\n``` <> ***"])
def test_empty_body_adds_nothing(pr_data, body):
    assert art_prompt(_stats(pr_data, body)) == art_prompt(_stats(pr_data, ""))
    assert "The change does" not in art_prompt(_stats(pr_data, body))


def test_long_body_truncated(pr_data):
    base = art_prompt(_stats(pr_data, ""))
    prompt = art_prompt(_stats(pr_data, "word " * 2000))
    assert len(_body_clause(prompt)) <= BODY_LIMIT
    assert len(prompt) - len(base) < BODY_LIMIT + 200


def test_markup_and_quotes_stripped(pr_data):
    body = 'Hi\n```py\nx = "1"\n```\n<script>alert(1)</script> [a](http://e.com/?q=1&r=2) \'"`#*_'
    clause = _body_clause(art_prompt(_stats(pr_data, body)))
    assert clause is not None
    assert re.fullmatch(r"[A-Za-z0-9 ,.'()+-]*", clause)
    assert "<" not in clause and "\n" not in clause and "  " not in clause
