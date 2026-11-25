import pytest

from domain.bots import draw_card, play_from


class Cycling:
    def __init__(self):
        self.offered = []
        self.turn = 0

    def choice(self, seq):
        self.offered.append(list(seq))
        picked = seq[self.turn % len(seq)]
        self.turn += 1
        return picked


def test_draw_card_takes_each_allowed_card_with_equal_chance():
    rng = Cycling()

    drawn = [draw_card(["A3", "A1", "A2", "A1"], rng) for _ in range(6)]

    assert rng.offered == [["A1", "A2", "A3"]] * 6
    assert sorted(drawn) == ["A1", "A1", "A2", "A2", "A3", "A3"]


def defence_play(**extra):
    return {"model": "claude-haiku-5-5", "budget_usd": 2, "max_turns": 200,
            "pace": {"per_window": 4, "window_s": 300, "min_gap_s": 45},
            "allowance": {"operations": ["defence_state"]}, **extra}


def test_a_play_carries_its_watch_interval_when_the_step_names_one_and_refuses_one_under_a_second():
    assert play_from(defence_play(watch_s=75)).shown()["watch_s"] == 75
    assert play_from(defence_play()).watch_s is None
    with pytest.raises(ValueError):
        play_from(defence_play(watch_s=0))
