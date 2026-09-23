import json
import os
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

DRIVER = Path(__file__).with_name("browser.js")
VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "source", "track", "wbr",
}

class Page(HTMLParser):

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tree = {"tag": "#document", "attrs": {}, "text": "", "children": []}
        self.open = [self.tree]
        self.scripts = []
        self.in_script = False

    def _element(self, tag, attrs):
        node = {
            "tag": tag,
            "attrs": {name: value or "" for name, value in attrs},
            "text": "",
            "children": [],
        }
        self.open[-1]["children"].append(node)
        return node

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.in_script = True
            self.scripts.append("")
            return
        node = self._element(tag, attrs)
        if tag not in VOID:
            self.open.append(node)

    def handle_startendtag(self, tag, attrs):
        self._element(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False
            return
        for depth in range(len(self.open) - 1, 0, -1):
            if self.open[depth]["tag"] == tag:
                del self.open[depth:]
                return

    def handle_data(self, data):
        if self.in_script:
            self.scripts[-1] += data
        else:
            self.open[-1]["text"] += data

def node():
    found = shutil.which(
        "node",
        path=os.pathsep.join([os.environ.get("PATH", ""), "/opt/homebrew/bin", "/usr/local/bin"]),
    )
    if found is None:
        pytest.fail("the console's behaviour tests run its script under node, and node is not installed")
    return found

def open_page(client, path, setup="", scenario=""):
    page = Page()
    page.feed(client.get(path).content.decode())
    page.close()

    done = subprocess.run(
        [node(), str(DRIVER)],
        input=json.dumps({
            "path": path,
            "tree": page.tree,
            "scripts": page.scripts,
            "setup": setup,
            "scenario": scenario,
        }),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)

def english(key, *values):
    from tests.test_strings import tables

    text = tables()["en"][key]
    for index, value in enumerate(values):
        text = text.replace("{%d}" % index, str(value))
    return text
