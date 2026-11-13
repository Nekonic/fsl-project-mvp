import pytest

from tests.browser import open_page
from tests.test_lesson_console import STEPS, served, to

pytestmark = pytest.mark.django_db

def test_a_step_that_asks_for_a_query_rings_only_the_query_bar_until_the_learner_s_own_query_matches(client):
    gated = [dict(step, point={"opens": "elk", "kibana": {"hits": True, "kql": r"event_type\s*:\s*\"?alert"}})
             if step["id"] == "logged" else step for step in STEPS]
    seen = open_page(client, "/blue/1/", setup=served(steps=gated), scenario=f"""
      STRINGS['lesson.kibana.write'] = 'Write the KQL here.';
      STRINGS['lesson.demo.callout.logged'] = 'The count.';
      const doc = browser.element('pane-frame').contentDocument;
      const plain = doc.querySelector;
      const input = {{value: 'status : 500', getBoundingClientRect: () => box(300, 100, 400, 36)}};
      doc.querySelector = (selector) => (selector === '[data-test-subj="queryInput"]' ? input : plain(selector));
      {to("logged")}
      await browser.click('step-open');
      kibana.set('[data-test-subj="discoverQueryHits"]', box(400, 150, 80, 20));
      await frames();
      const other = {{text: browser.text('coach-callout'), ring: styled('coach-ring').top}};
      input.value = 'EVENT_TYPE : alert';
      await frames();
      return {{other, written: browser.text('coach-callout')}};
    """)
    result = seen["result"]

    assert seen["errors"] == []
    assert result["other"] == {"text": "Write the KQL here.", "ring": 190}, "a count from someone else's query is not shown"
    assert result["written"] == "The count."
