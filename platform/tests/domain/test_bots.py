from domain.bots import draw_card


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
