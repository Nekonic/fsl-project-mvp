const fs = require("fs");
const vm = require("vm");
const nodeCrypto = require("crypto");

const input = JSON.parse(fs.readFileSync(0, "utf8"));
const errors = [];
const logged = [];

const describe = (error) =>
  error && error.name && error.message !== undefined
    ? `${error.name}: ${error.message}`
    : String(error);

process.on("unhandledRejection", (reason) => errors.push(describe(reason)));

function guard(run) {
  try {
    run();
  } catch (error) {
    errors.push(describe(error));
  }
}

const camel = (name) => name.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'", times: "×" };
const decode = (text) => text.replace(/&(amp|lt|gt|quot|#39|times);/g, (_, name) => ENTITIES[name]);
const visibleText = (html) => decode(html.replace(/<[^>]*>/g, " ")).replace(/\s+/g, " ").trim();

function splitTop(text, separator) {
  const parts = [];
  let depth = 0;
  let quote = null;
  let current = "";
  for (const character of text) {
    if (quote) {
      if (character === quote) quote = null;
    } else if (character === '"' || character === "'") {
      quote = character;
    } else if (character === "[" || character === "(") {
      depth += 1;
    } else if (character === "]" || character === ")") {
      depth -= 1;
    } else if (depth === 0 && separator.test(character)) {
      if (current) parts.push(current);
      current = "";
      continue;
    }
    current += character;
  }
  if (current) parts.push(current);
  return parts;
}

const SIMPLE = /([a-zA-Z][\w-]*)|#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\]]*)))?\]|:not\(([^)]*)\)|:(disabled|checked)/;

function compound(text) {
  const tests = [];
  const simple = new RegExp(SIMPLE.source, "y");
  while (simple.lastIndex < text.length) {
    const at = simple.lastIndex;
    const m = simple.exec(text);
    if (!m || m.index !== at) throw new Error(`the stub DOM cannot match the selector ${text}`);
    const [, tag, id, cls, attr, dq, sq, bare, not, state] = m;
    if (tag) tests.push((e) => e.tagName === tag.toUpperCase());
    else if (id) tests.push((e) => e.id === id);
    else if (cls) tests.push((e) => e.classList.contains(cls));
    else if (attr) {
      const wanted = dq ?? sq ?? bare;
      tests.push((e) => {
        const value = e.getAttribute(attr);
        return value !== null && (wanted === undefined || value === wanted);
      });
    } else if (not !== undefined) {
      const inner = compound(not);
      tests.push((e) => !inner(e));
    } else if (state) tests.push((e) => Boolean(e[state]));
  }
  return (e) => tests.every((test) => test(e));
}

function matcher(selector) {
  const alternatives = splitTop(selector, /,/).map((one) =>
    splitTop(one.trim(), /\s/).map(compound));
  return (element) => alternatives.some((chain) => {
    if (!chain[chain.length - 1](element)) return false;
    let at = element.parentNode;
    for (let i = chain.length - 2; i >= 0; i -= 1) {
      while (at && !chain[i](at)) at = at.parentNode;
      if (!at) return false;
      at = at.parentNode;
    }
    return true;
  });
}

class ClassList {
  constructor(element) { this.element = element; }
  names() { return this.element.className.split(/\s+/).filter(Boolean); }
  contains(name) { return this.names().includes(name); }
  add(...names) { this.element.className = [...new Set([...this.names(), ...names])].join(" "); }
  remove(...names) {
    this.element.className = this.names().filter((n) => !names.includes(n)).join(" ");
  }
  toggle(name, force) {
    const on = force === undefined ? !this.contains(name) : Boolean(force);
    if (on) this.add(name); else this.remove(name);
    return on;
  }
}

const REFLECTED = ["title", "href", "src", "placeholder", "type", "name", "lang", "target", "rel"];

class Element {
  constructor(tag, attrs = {}, text = "") {
    this.tagName = tag.toUpperCase();
    this.attributes = {};
    this.dataset = {};
    this.style = {};
    this.children = [];
    this.parentNode = null;
    this.listeners = {};
    this.classList = new ClassList(this);
    this.className = "";
    this.id = "";
    this.checked = "checked" in attrs;
    this.disabled = "disabled" in attrs;
    this.selected = "selected" in attrs;
    this.ownText = text;
    this.markup = null;
    this.chosen = this.tagName === "SELECT" ? null : (attrs.value ?? "");
    for (const [name, value] of Object.entries(attrs)) this.setAttribute(name, value);
  }

  setAttribute(name, value) {
    value = String(value);
    if (name === "class") this.className = value;
    else if (name === "id") this.id = value;
    else if (name.startsWith("data-")) this.dataset[camel(name.slice(5))] = value;
    else this.attributes[name] = value;
  }

  getAttribute(name) {
    if (name === "class") return this.className;
    if (name === "id") return this.id || null;
    if (name.startsWith("data-")) return this.dataset[camel(name.slice(5))] ?? null;
    return this.attributes[name] ?? null;
  }

  hasAttribute(name) { return this.getAttribute(name) !== null; }

  removeAttribute(name) {
    if (name.startsWith("data-")) delete this.dataset[camel(name.slice(5))];
    else delete this.attributes[name];
  }

  get value() {
    if (this.tagName !== "SELECT" || this.chosen !== null) return this.chosen;
    const options = this.querySelectorAll("option");
    const picked = options.find((o) => o.selected) || options[0];
    return picked ? picked.value : "";
  }

  set value(value) { this.chosen = String(value); }

  get textContent() {
    if (this.markup !== null) return visibleText(this.markup);
    return this.ownText + this.children.map((c) => c.textContent).join("");
  }

  set textContent(value) {
    this.ownText = String(value);
    this.markup = null;
    this.children = [];
  }

  get innerHTML() { return this.markup ?? ""; }

  set innerHTML(value) {
    this.markup = String(value);
    this.ownText = "";
    this.children = [];
    if (this.tagName === "SELECT") {
      const first = /<option[^>]*\bvalue="([^"]*)"/.exec(this.markup);
      this.chosen = first ? decode(first[1]) : "";
    }
  }

  append(...nodes) { nodes.forEach((node) => this.appendChild(node)); }

  appendChild(node) {
    node.parentNode = this;
    this.children.push(node);
    return node;
  }

  prepend(...nodes) {
    nodes.forEach((node) => { node.parentNode = this; });
    this.children.unshift(...nodes);
  }

  remove() {
    if (!this.parentNode) return;
    this.parentNode.children = this.parentNode.children.filter((c) => c !== this);
    this.parentNode = null;
  }

  get lastElementChild() { return this.children[this.children.length - 1] || null; }

  descendants() {
    return this.children.flatMap((c) => [c, ...c.descendants()]);
  }

  querySelectorAll(selector) { return this.descendants().filter(matcher(selector)); }

  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }

  closest(selector) {
    const matches = matcher(selector);
    let at = this;
    while (at && !matches(at)) at = at.parentNode;
    return at || null;
  }

  addEventListener(type, listener) {
    (this.listeners[type] = this.listeners[type] || []).push(listener);
  }

  removeEventListener(type, listener) {
    this.listeners[type] = (this.listeners[type] || []).filter((l) => l !== listener);
  }

  dispatchEvent(event) {
    event.target = event.target || this;
    event.currentTarget = this;
    for (const listener of [...(this.listeners[event.type] || [])]) {
      guard(() => listener.call(this, event));
    }
    return true;
  }

  click() {
    if (this.disabled) return;
    this.dispatchEvent(makeEvent("click"));
  }

  focus() {}
  blur() {}
  scrollIntoView() {}
}

for (const name of REFLECTED) {
  Object.defineProperty(Element.prototype, name, {
    get() { return this.attributes[name] ?? ""; },
    set(value) { this.attributes[name] = String(value); },
  });
}

function makeEvent(type, extra = {}) {
  return { type, preventDefault() {}, stopPropagation() {}, ...extra };
}

function build(node) {
  const element = new Element(node.tag, node.attrs, node.text || "");
  node.children.forEach((child) => element.appendChild(build(child)));
  return element;
}

const document = build(input.tree);
document.documentElement = document.querySelector("html");
document.head = document.querySelector("head");
document.body = document.querySelector("body");
document.cookie = "";
document.visibilityState = "visible";
document.getElementById = (id) => document.descendants().find((e) => e.id === id) || null;
document.createElement = (tag) => new Element(tag);

const timers = new Map();
let nextTimer = 1;
let clock = 0;
const LONGEST_POLL = 60 * 1000;
const schedule = (repeat) => (callback, delay) => {
  const wait = Number(delay) || 0;
  timers.set(nextTimer, { callback, delay: wait, repeat, due: clock + wait });
  return nextTimer++;
};
const cancel = (id) => { timers.delete(id); };

let answer = () => ({ status: 404, body: { detail: "the test served nothing here" } });
const requests = [];

function fetch(path, options = {}) {
  const url = new URL(String(path), "http://console.test");
  const request = {
    method: (options.method || "GET").toUpperCase(),
    path: String(path),
    route: url.pathname,
    query: Object.fromEntries(url.searchParams),
    body: options.body === undefined ? null : JSON.parse(options.body),
  };
  requests.push(request);
  const signal = options.signal;
  const answered = new Promise((resolve) => resolve(answer(request))).then((served) => {
    const status = served.status ?? 200;
    const payload = JSON.stringify(served.body ?? {});
    return {
      ok: status >= 200 && status < 300,
      status,
      json: () => served.bodyNeverArrives
        ? new Promise((resolve, reject) => {
          if (signal) signal.addEventListener("abort", () => reject(signal.reason), { once: true });
        })
        : Promise.resolve(JSON.parse(payload)),
    };
  });
  if (!signal) return answered;
  return new Promise((resolve, reject) => {
    const abandoned = () => reject(signal.reason);
    if (signal.aborted) {
      abandoned();
      return;
    }
    signal.addEventListener("abort", abandoned, { once: true });
    answered.then(resolve, reject);
  });
}

const storage = () => {
  const kept = new Map();
  return {
    getItem: (key) => (kept.has(key) ? kept.get(key) : null),
    setItem: (key, value) => { kept.set(key, String(value)); },
    removeItem: (key) => { kept.delete(key); },
    clear: () => { kept.clear(); },
  };
};

const settle = async () => {
  for (let i = 0; i < 5; i += 1) await new Promise((resolve) => setImmediate(resolve));
};

function element(reference) {
  const found = document.getElementById(reference) || document.querySelector(reference);
  if (!found) throw new Error(`the page has no element ${reference}`);
  return found;
}

async function runTimers(due) {
  for (const [id, timer] of [...timers]) {
    if (!due(timer)) continue;
    if (timer.repeat) timer.due = clock + timer.delay;
    else timers.delete(id);
    guard(() => timer.callback());
  }
  await settle();
}

function change(target, value) {
  target.value = value;
  target.dispatchEvent(makeEvent("input"));
  target.dispatchEvent(makeEvent("change"));
}

const browser = {
  requests,
  errors,
  logged,
  settle,
  element,
  offline() { throw new TypeError("Failed to fetch"); },
  serve(handler) { answer = handler; },
  text: (reference) => element(reference).textContent,
  async click(reference) {
    element(reference).click();
    await settle();
  },
  async choose(reference, value) {
    const target = element(reference);
    if (target.disabled) return false;
    change(target, value);
    await settle();
    return true;
  },
  async force(reference, value) {
    change(element(reference), value);
    await settle();
  },
  poll: () => runTimers((timer) => timer.delay <= LONGEST_POLL),
  wait(ms) {
    clock += ms;
    return runTimers((timer) => timer.due <= clock);
  },
};

const record = (level) => (...parts) => logged.push(`${level}: ${parts.map(String).join(" ")}`);
const windowEvents = new Element("#window");

const sandbox = {
  document,
  browser,
  fetch,
  location: {
    pathname: input.path,
    href: `http://console.test${input.path}`,
    origin: "http://console.test",
    search: "",
    reload() {},
  },
  navigator: { language: "en-US", languages: ["en-US", "en"] },
  localStorage: storage(),
  sessionStorage: storage(),
  console: { log: record("log"), info: record("info"), warn: record("warn"), error: record("error") },
  crypto: { randomUUID: () => nodeCrypto.randomUUID() },
  AbortController,
  URL,
  URLSearchParams,
  setInterval: schedule(true),
  setTimeout: schedule(false),
  clearInterval: cancel,
  clearTimeout: cancel,
  requestAnimationFrame: schedule(false),
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  addEventListener: (type, listener) => windowEvents.addEventListener(type, listener),
  removeEventListener: (type, listener) => windowEvents.removeEventListener(type, listener),
  dispatchEvent: (event) => windowEvents.dispatchEvent(event),
};
sandbox.window = sandbox;
sandbox.self = sandbox;
vm.createContext(sandbox);

(async () => {
  vm.runInContext(input.setup || "", sandbox, { filename: "setup.js" });
  input.scripts.forEach((source, index) => {
    guard(() => vm.runInContext(source, sandbox, { filename: `page-script-${index}.js` }));
  });
  await settle();
  const result = await vm.runInContext(
    `(async () => {\n${input.scenario || ""}\n})()`, sandbox, { filename: "scenario.js" });
  await settle();
  process.stdout.write(JSON.stringify({ result: result ?? null, errors, logged }));
})().catch((error) => {
  process.stderr.write(`${error && error.stack ? error.stack : error}\n`);
  process.exit(1);
});
