import copy
import re

import pytest

from shipit.art import BODY_LIMIT, LANGUAGE_MOTIFS, STYLES, TYPE_SCENES, art_prompt
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


def test_styles_keys():
    assert list(STYLES) == ["pixel", "anime", "watercolour", "painterly"]


def test_default_prompt_unchanged(pr_data):
    stats = build_stats(pr_data)
    assert art_prompt(stats, None) == art_prompt(stats)
    # Exact pre-styles prompt template (single space after "Painterly"), so the
    # Gemini cache hash for unstyled cards stays unchanged.
    scene = TYPE_SCENES.get(stats.card_type, TYPE_SCENES["Feature"])
    motif = LANGUAGE_MOTIFS.get(stats.language, "")
    team = (
        " A small friendly robot works alongside the human, as an equal partner."
        if stats.has_agents
        else ""
    )
    expected = (
        f"Full-bleed fantasy illustration: {scene} {motif}. "
        f'The scene is loosely inspired by a software change called "{stats.title}".{team} '
        f"{stats.rarity} card energy. Vibrant, optimistic, celebratory mood. Painterly "
        "digital fantasy art, dramatic lighting, rich saturated colours, centred subject, "
        "4:3 landscape composition that fills the entire canvas edge to edge. No border, "
        "no frame, no card outline, no panels. Absolutely no text, letters, numbers, logos "
        "or watermarks anywhere in the image."
    )
    assert art_prompt(stats) == expected
    assert "Painterly  digital" not in art_prompt(stats)


@pytest.mark.parametrize("style", list(STYLES))
def test_style_prompt(pr_data, style):
    stats = build_stats(pr_data)
    prompt = art_prompt(stats, style)
    assert STYLES[style] in prompt
    assert "Painterly digital fantasy art" not in prompt
    assert "steampunk workshop" not in prompt
    assert "No border, no frame" in prompt
    assert "Absolutely no text" in prompt


def test_gemini_cache_files_differ_per_style(pr_data, monkeypatch, tmp_path):
    from PIL import Image

    from shipit import art

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(art, "CACHE_DIR", tmp_path)
    prompts = []

    def fake(prompt, model, key):
        prompts.append(prompt)
        return Image.new("RGB", (40, 30))

    monkeypatch.setattr(art, "generate_with_gemini", fake)
    stats = build_stats(pr_data)
    assert art.get_art(stats)[1] == "gemini"
    assert len(list(tmp_path.glob("*.png"))) == 1
    assert art.get_art(stats, style="pixel")[1] == "gemini"
    assert art.get_art(stats, style="anime")[1] == "gemini"
    assert len(list(tmp_path.glob("*.png"))) == 3
    assert art.get_art(stats, style="pixel")[1] == "cache"
    assert art.get_art(stats)[1] == "cache"
    assert len(prompts) == 3


def test_styled_art_errors_without_gemini(pr_data, monkeypatch):
    from shipit import art

    stats = build_stats(pr_data)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(art.StyledArtUnavailable):
        art.get_art(stats, style="pixel")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    with pytest.raises(art.StyledArtUnavailable):
        art.get_art(stats, use_gemini=False, style="pixel")
    assert art.get_art(stats, use_gemini=False)[1] == "procedural"


def test_styled_art_errors_when_gemini_fails(pr_data, monkeypatch, tmp_path):
    from shipit import art

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(art, "CACHE_DIR", tmp_path)

    def boom(prompt, model, key):
        raise RuntimeError("down")

    monkeypatch.setattr(art, "generate_with_gemini", boom)
    stats = build_stats(pr_data)
    with pytest.raises(art.StyledArtUnavailable):
        art.get_art(stats, style="anime")
    assert art.get_art(stats)[1] == "procedural"


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
