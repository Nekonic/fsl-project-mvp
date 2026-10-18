import json

import pytest

import wargames
from tests.browser import open_page
from tests.test_lesson_console import GRID, OBJECTIVES, STEPS, served, to

pytestmark = pytest.mark.django_db

ROUND_5_LAYOUT = """
placeAt('pane', box(60, 56, 1040, 844));
placeAt('pane-body', box(60, 96, 1040, 804));
placeAt('lesson', box(1100, 56, 340, 844));
placeAt('lesson-body', box(1100, 111, 340, 789));
['pane-frame', 'site-frame', 'kali-frame', 'topology-frame'].forEach((id) => placeAt(id, box(60, 96, 1040, 804)));
const asBox = ([left, top, width, height]) => ({left, top, width, height});
const calloutTip = browser.element('coach-callout');
const widthOf = (text) => [...text].reduce((sum, c) => sum + (/[가-힣]/.test(c) ? 10.4 : c === ' ' ? 3.7 : 7.6), 0);
const tipSize = () => {
  const natural = widthOf(calloutTip.textContent) + 20;
  const width = Math.min(natural, parseFloat(calloutTip.style.maxWidth) || 360);
  const lines = calloutTip.style.whiteSpace === 'normal' ? Math.max(1, Math.ceil((natural - 20) / (width - 20))) : 1;
  return {width: Math.round(width), height: Math.round(12 + 17 * lines)};
};
Object.defineProperty(calloutTip, 'offsetWidth', {get: () => tipSize().width});
Object.defineProperty(calloutTip, 'offsetHeight', {get: () => tipSize().height});
const tipBox = () => (shown('coach-callout') ? {left: parseFloat(calloutTip.style.left), top: parseFloat(calloutTip.style.top), ...tipSize()} : null);
const leaderOf = () => {
  if (!shown('coach-leader')) return null;
  const style = browser.element('coach-leader').style;
  const left = parseFloat(style.left);
  const top = parseFloat(style.top);
  const length = parseFloat(style.width);
  const angle = parseFloat(/rotate\\(([-\\d.e]+)rad\\)/.exec(style.transform)[1]);
  return {length, from: {x: left, y: top}, to: {x: left + length * Math.cos(angle), y: top + length * Math.sin(angle)}};
};
const inside = (point, one) => point.x > one.left && point.x < one.left + one.width && point.y > one.top && point.y < one.top + one.height;
const crossed = (leader, boxes) => (leader ? boxes.filter((one) => Array.from({length: 61}, (_, i) => ({
  x: leader.from.x + (leader.to.x - leader.from.x) * i / 60, y: leader.from.y + (leader.to.y - leader.from.y) * i / 60,
})).some((point) => inside(point, one))) : []);
const gapBetween = (a, b) => Math.hypot(Math.max(a.left - b.left - b.width, b.left - a.left - a.width, 0),
                                        Math.max(a.top - b.top - b.height, b.top - a.top - a.height, 0));
const judged = (texts) => {
  const spot = tipBox();
  const ring = styled('coach-ring');
  const leader = leaderOf();
  return {
    spot, ring, leader,
    covers: spot ? texts.filter((one) => meets(spot, one)) : null,
    coversRing: spot ? meets(spot, ring) : null,
    crossing: crossed(leader, texts),
    gap: spot ? Math.round(gapBetween(spot, ring)) : null,
    rowCentre: spot ? spot.top + spot.height / 2 : null,
  };
};
"""

def served_with(steps, objectives=OBJECTIVES):
    return served(objectives=objectives, steps=steps) + ROUND_5_LAYOUT

def step_named(name, **point):
    return [{**step, "point": {**step["point"], **point}} if step["id"] == name else step for step in STEPS]

def test_the_f5_sort_step_points_at_the_whole_control_so_its_label_is_inside_the_ring():
    sorts = [step for lesson in wargames.foundations("board") for step in lesson["steps"] if step["id"] == "sort"]

    assert sorts and all("select[name=sort]" in step["point"]["site"] and step["point"]["site"].startswith("form")
                         for step in sorts), "the label 정렬 beside the menu is part of what is ringed"

def test_the_f3_forwarded_for_step_points_at_the_one_line_field_not_the_wrapped_header_list():
    xff = next(step for lesson in wargames.foundations("board") for step in lesson["steps"] if step["id"] == "xff")

    assert xff["point"]["kibana"] == {"doc": "request_header.x_forwarded_for"}


KIBANA_FRAME = """
placeAt('pane-body', box(60, 56, 1040, 844));
placeAt('pane-frame', box(60, 56, 1040, 844));
const crowdList = [];
const made = new Map();
let flyoutRegion = null;
const asElement = ([left, top, width, height, control, label]) => ({
  tagName: control ? 'BUTTON' : 'SPAN', firstElementChild: null, textContent: label === '' ? '' : 'x', matches: () => Boolean(control),
  getBoundingClientRect: () => box(left - 60, top - 56, width, height),
});
const elementOf = (entry) => { if (!made.has(entry)) made.set(entry, asElement(entry)); return made.get(entry); };
const crowdedDoc = (doc) => {
  const gridAll = doc.querySelectorAll;
  doc.querySelectorAll = (selector) => (selector === 'body *' ? crowdList.map(elementOf) : gridAll(selector));
  doc.createRange = () => ({selectNodeContents(element) { this.element = element; }, getBoundingClientRect() { return this.element.getBoundingClientRect(); }});
  doc.elementFromPoint = (x, y) => {
    const px = x + 60;
    const py = y + 56;
    const holds = (entry) => px >= entry[0] && px < entry[0] + entry[2] && py >= entry[1] && py < entry[1] + entry[3];
    const under = flyoutRegion && holds(flyoutRegion);
    const found = crowdList.find((entry) => holds(entry) && (!under || entry[6]));
    return found ? elementOf(found) : (under ? {covering: 'the flyout'} : null);
  };
};
"""

def test_the_f5_sort_callout_sits_on_the_menu_s_own_row_in_the_empty_space_beside_it_and_its_leader_crosses_no_date(client):
    seen = open_page(client, "/blue/1/", setup=served_with(step_named("sort", site="form:has(select[name=sort])")), scenario=f"""
      STRINGS.en['lesson.demo.callout.sort'] = '게시글 목록의 정렬 메뉴입니다.';
      {to("sort")}
      await browser.click('step-open');
      await frames();
      const frameAt = (x, y, w, h) => ({{x: x - 60, y: y - 96, w, h}});
      const texts = [
        [112, 112, 126, 24], [485, 105, 200, 38], [693, 105, 54, 38], [945, 109, 103, 30], [112, 178, 70, 28],
        [129, 241, 110, 20], [914, 244, 117, 16], [129, 271, 48, 16],
        [129, 306, 110, 20], [915, 309, 116, 16], [129, 336, 48, 16],
        [129, 370, 110, 20], [913, 373, 118, 16], [129, 400, 48, 16],
      ];
      answer('site-frame', frameAt(918, 177, 129, 31), texts.map((one) => frameAt(...one)));
      await frames();
      return judged(texts.map(([left, top, width, height]) => ({{left, top, width, height}})));
    """)
    placed = seen["result"]

    assert seen["errors"] == []
    assert placed["spot"] is not None
    assert placed["covers"] == [] and placed["coversRing"] is False
    assert placed["crossing"] == [], "the leader runs over no row's date"
    assert placed["gap"] <= 40, "next to the menu, not 200 px below it"
    assert placed["ring"]["top"] <= placed["rowCentre"] <= placed["ring"]["top"] + placed["ring"]["height"], (
        "on the menu's row, left of the label, in the space between the heading and the menu")

COST_ROWS = {"rows": [{"id": "board-auth-user-partial", "difficulty": 2, "lost": True, "detected": False, "points": 4},
                      {"id": "board-auth-user-admin", "difficulty": 4, "lost": True, "detected": False, "points": 8},
                      {"id": "board-auth-user-all", "difficulty": 5, "lost": True, "detected": False, "points": 10}],
             "total": 22}

def test_the_f6_cost_callout_sits_beside_the_ringed_row_and_its_leader_crosses_no_table_text(client):
    seen = open_page(client, "/blue/1/",
                     setup=served_with(step_named("cost", panel="#lesson-objectives [data-objective=board-auth-user-admin]"), COST_ROWS),
                     scenario=f"""
      STRINGS.en['lesson.demo.callout.cost'] = '관리자 계정 목표의 난이도와 감점입니다.';
      placeAt('lesson-objectives', box(1113, 364, 314, 194));
      const rows = document.querySelectorAll('#lesson-objectives-rows [data-objective]');
      rows.forEach((row, index) => RECTS.set(row, box(1119, 432 + 29 * index, 301, 28)));
      const heads = document.querySelectorAll('#lesson-objectives-head th');
      [[1126, 28], [1220, 31], [1272, 44], [1337, 44], [1393, 28]].forEach(([left, width], index) => RECTS.set(heads[index], box(left, 411, width, 13)));
      const foot = document.querySelectorAll('#lesson-objectives tfoot td');
      RECTS.set(foot[0], box(1126, 523, 80, 14));
      RECTS.set(foot[1], box(1385, 523, 28, 14));
      {to("cost")}
      await frames();
      const table = [[1126, 411, 28, 13], [1220, 411, 31, 13], [1272, 411, 44, 13], [1337, 411, 44, 13], [1393, 411, 28, 13],
                     [1126, 439, 60, 14], [1220, 439, 10, 14], [1280, 439, 34, 14], [1355, 439, 28, 14], [1405, 439, 10, 14],
                     [1126, 497, 60, 14], [1126, 523, 80, 14], [1385, 523, 28, 14], [1126, 378, 28, 14]].map(asBox);
      return {{...judged(table), card: asBox([1113, 364, 314, 194])}};
    """)
    placed = seen["result"]

    assert seen["errors"] == []
    assert placed["spot"] is not None
    assert placed["covers"] == [] and placed["coversRing"] is False
    assert placed["crossing"] == [], "no leader through 탈취됨 or any other cell"
    assert placed["spot"]["left"] + placed["spot"]["width"] <= placed["card"]["left"], "left of the card, level with the ringed row"
    assert placed["ring"]["top"] <= placed["rowCentre"] <= placed["ring"]["top"] + placed["ring"]["height"]
    assert placed["gap"] <= 40

FLYOUT = [
    [277, 160, 443, 40, 1], [68, 160, 112, 40, 1], [188, 160, 40, 40, 1], [230, 160, 40, 40, 1], [736, 160, 304, 40, 1], [1052, 160, 40, 40, 1],
    [76, 66, 100, 30], [397, 65, 368, 30, 1], [1020, 66, 24, 24, 1, ""], [1055, 66, 24, 24, 1, ""], [78, 118, 24, 24, 1, ""],
    [737, 120, 30, 16], [792, 120, 36, 16], [852, 120, 38, 16], [914, 120, 48, 16], [980, 112, 112, 32, 1], [156, 116, 76, 24],
    [660, 168, 24, 24, 1, "", 1], [690, 168, 24, 24, 1, "1", 1], [750, 168, 22, 24, 1, "2", 1], [808, 168, 22, 24, 1, "", 1],
    [1070, 164, 24, 24, 1, "", 1], [572, 208, 53, 17, 0, "x", 1], [657, 208, 148, 17, 0, "x", 1], [817, 208, 217, 17, 0, "x", 1],
    [576, 273, 35, 16, 0, "x", 1], [628, 273, 34, 16, 0, "x", 1], [572, 306, 512, 38, 1, "x", 1], [578, 360, 30, 14, 0, "x", 1],
    [732, 360, 40, 14, 0, "x", 1], [603, 388, 60, 14, 0, "x", 1], [732, 389, 78, 14, 0, "x", 1],
    [120, 225, 150, 16], [75, 262, 70, 14], [75, 300, 70, 14], [75, 327, 70, 14], [488, 376, 487, 16],
]

def test_the_f3_other_event_callout_keeps_off_the_query_bar_the_pager_and_the_actions_row(client):
    seen = open_page(client, "/blue/1/", setup=served_with(STEPS) + GRID, scenario=f"""
      STRINGS.en['lesson.kibana.other'] = '찾는 이벤트가 아닙니다. Document 창 위쪽의 > 버튼으로 다음 이벤트로 넘기세요.';
      {KIBANA_FRAME}
      crowdedDoc(doc);
      flyoutRegion = [555, 152, 545, 748];
      const list = {json.dumps(FLYOUT)};
      list.forEach((one) => crowdList.push(one));
      {to("source")}
      await browser.click('step-open');
      hops = [hop(0, '175.192.0.10', '10.30.0.102'), hop(1, '10.30.0.102', '10.30.0.63')];
      kibana.set('[data-test-subj="docViewerFlyout"]', box(495, 96, 545, 748));
      pageAt = 0;
      arrows.set('button[data-test-subj="pagination-button-next"]', box(718, 112, 24, 24));
      const fromPoint = doc.elementFromPoint;
      doc.elementFromPoint = (x, y) => (x >= 718 && x < 742 && y >= 112 && y < 136 ? {{contains: () => true}} : fromPoint(x, y));
      await frames();
      const visible = list.filter((one) => one[6] || !(one[0] + one[2] / 2 >= 555 && one[1] + one[3] / 2 >= 152));
      return {{...judged(visible.map(asBox)), flyout: asBox([555, 152, 545, 748])}};
    """)
    placed = seen["result"]

    assert seen["errors"] == []
    assert placed["ring"] == {"left": 772, "top": 162, "width": 36, "height": 36}
    assert placed["spot"] is not None
    assert placed["covers"] == [] and placed["coversRing"] is False, "off the KQL bar, the pager counter and the Actions links"
    assert placed["crossing"] == []
    assert placed["spot"]["left"] >= placed["flyout"]["left"], "inside the document flyout, not over the query bar"
    assert placed["gap"] <= 60

LIST = [
    [277, 160, 443, 40, 1], [68, 160, 112, 40, 1], [188, 160, 40, 40, 1], [230, 160, 40, 40, 1], [736, 160, 304, 40, 1], [1052, 160, 40, 40, 1],
    [737, 120, 30, 16], [792, 120, 36, 16], [852, 120, 38, 16], [914, 120, 48, 16], [980, 112, 112, 32, 1], [156, 116, 76, 24],
    [110, 217, 245, 33, 1], [120, 225, 150, 16], [75, 262, 70, 14], [75, 300, 70, 14], [75, 327, 70, 14], [75, 354, 70, 14],
    [414, 217, 126, 31, 1], [557, 217, 146, 31, 1], [376, 418, 79, 16], [531, 418, 100, 16], [739, 410, 117, 31, 1], [864, 410, 124, 31, 1],
    [996, 410, 31, 31, 1, ""], [1036, 410, 31, 31, 1, ""], [1067, 410, 31, 31, 1, ""], [488, 376, 487, 16], [407, 343, 83, 20],
    [422, 455, 75, 14], [548, 455, 14, 14], [607, 455, 70, 14], [727, 455, 63, 14], [872, 455, 76, 14], [1007, 455, 20, 14],
    [422, 490, 120, 30], [601, 497, 10, 14], [712, 490, 78, 14], [872, 490, 78, 14], [1005, 490, 80, 40],
]

def test_the_f6_seen_callout_keeps_off_the_tab_label_next_to_the_count_and_the_text_around_it(client):
    seen = open_page(client, "/blue/1/", setup=served_with(STEPS), scenario=f"""
      STRINGS.en['lesson.demo.callout.logged'] = '조회된 이벤트 건수입니다.';
      {KIBANA_FRAME}
      const doc = browser.element('pane-frame').contentDocument;
      crowdedDoc(doc);
      const list = {json.dumps(LIST)};
      list.forEach((one) => crowdList.push(one));
      {to("logged")}
      await browser.click('step-open');
      kibana.set('[data-test-subj="discoverQueryHits"]', box(404, 361, 37, 17));
      await frames();
      return judged(list.map(asBox));
    """)
    placed = seen["result"]

    assert seen["errors"] == []
    assert placed["ring"] == {"left": 458, "top": 411, "width": 49, "height": 29}
    assert placed["spot"] is not None
    assert placed["covers"] == [], "not over 'Documents', the tab beside it or the table header below"
    assert placed["coversRing"] is False
    assert placed["crossing"] == []
    assert placed["gap"] <= 120

def test_the_f6_query_prompt_keeps_off_the_data_view_picker_the_filter_buttons_and_the_time_range(client):
    seen = open_page(client, "/blue/1/", setup=served_with(STEPS), scenario=f"""
      STRINGS.en['lesson.kibana.query'] = '여기에 KQL을 입력하세요.';
      {KIBANA_FRAME}
      const doc = browser.element('pane-frame').contentDocument;
      crowdedDoc(doc);
      const list = {json.dumps(LIST)};
      list.forEach((one) => crowdList.push(one));
      {to("logged")}
      await browser.click('step-open');
      kibana.set('[data-test-subj="queryInput"]', box(217, 104, 431, 40));
      kibana.set('[data-test-subj="discoverQueryHits"]', box(404, 361, 37, 17));
      kibana.set('[data-test-subj="superDatePickerToggleQuickMenuButton"]', box(676, 104, 36, 40));
      const fromPoint = doc.elementFromPoint;
      doc.elementFromPoint = (x, y) => (x >= 217 && x < 648 && y >= 104 && y < 144 ? {{contains: () => true}} : fromPoint(x, y));
      await frames();
      return judged(list.map(asBox));
    """)
    placed = seen["result"]

    assert seen["errors"] == []
    assert placed["ring"] == {"left": 271, "top": 154, "width": 443, "height": 52}
    assert placed["spot"] is not None
    assert placed["covers"] == [] and placed["coversRing"] is False
    assert placed["crossing"] == []
    assert placed["gap"] <= 60
