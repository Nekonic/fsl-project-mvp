from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db

DOM_XSS = (
    'Perform a <i>DOM</i> XSS attack with '
    '<code>&lt;iframe src="javascript:alert(`xss`)"&gt;</code>.'
)

def described(client, description):
    challenge = {"key": "localXssChallenge", "name": "DOM XSS", "category": "XSS",
                 "difficulty": 1, "description": description, "solved": False}
    with patch("objectives._fetch", return_value=[challenge]):
        board = client.get("/api/wargames/juice-shop/objectives/").json()
    return next(o["description"] for o in board if o["key"] == "localXssChallenge")

def test_a_description_reads_as_a_browser_would_show_it(client):
    assert described(client, DOM_XSS) == (
        'Perform a DOM XSS attack with <iframe src="javascript:alert(`xss`)">.'
    ), (
        "Juice Shop sends its descriptions as HTML and the console escapes "
        "everything it renders, so the red team read the tags as text"
    )

def test_searching_the_words_on_screen_finds_the_objective(client):
    assert "dom xss attack" in described(client, DOM_XSS).lower(), (
        "the red console searches name and description for what the reader "
        "typed, and a tag between two visible words hid the objective"
    )

def test_a_link_keeps_its_text_and_loses_its_address(client):
    description = described(
        client,
        '<a href="/#/contact">Inform the shop</a> about a <i>typosquatting</i> imposter.',
    )

    assert description == "Inform the shop about a typosquatting imposter."

def test_markup_in_a_description_is_left_as_inert_text(client):
    description = described(
        client, 'Win <script>alert(1)</script><img src=x onerror="alert(2)"> now',
    )

    assert description.startswith("Win ") and description.endswith(" now")
    for markup in ("<", ">", "script", "onerror", "src="):
        assert markup not in description, (
            f"{markup!r} survived into {description!r}; nothing the target sends "
            f"may reach the console as markup"
        )

def test_entities_are_decoded_exactly_once(client):
    description = described(client, "Type <code>&amp;lt;b&amp;gt;</code> literally.")

    assert description == "Type &lt;b&gt; literally.", (
        "the page shows &lt;b&gt; for &amp;lt;b&amp;gt;; decoding twice would "
        "turn the target's escaped text into a tag"
    )

def test_whitespace_collapses_as_a_browser_collapses_it(client):
    description = described(client, "  Find\n   the <i>hidden</i>\t egg. ")

    assert description == "Find the hidden egg."

def test_a_comment_in_a_description_is_not_shown(client):
    description = described(
        client,
        'Pay<!--IvLuRfBJYlmStf9XfL6ck==--> <a href="https://blockchain.info/address/1Ab" '
        'target="_blank">Unlock Premium Challenge</a> first.',
    )

    assert description == "Pay Unlock Premium Challenge first."

def test_a_description_ending_in_a_bare_ampersand_is_shown_to_the_end(client):
    description = described(client, "Ask the <i>research</i> team at R&D")

    assert description == "Ask the research team at R&D", (
        "the parser holds back text after an ampersand that might begin an "
        "entity until it is told the input has ended"
    )
