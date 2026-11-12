/* T-7260, G4: изолированный harness переноса прочитанной важной записи из блока #feed-important
 * в ленту #feed-list (static/feed/feed.js, обработчик htmx:beforeSwap; FR-614, CONTRACT-007 12.3).
 *
 * Подменяет DOM минимальной заглушкой и зовёт настоящий обработчик из feed.js синтетическим
 * событием вида htmx 2.0.11 (detail: serverResponse / xhr.status / requestConfig.elt / shouldSwap).
 * Прогоняет семь случаев: карточка старше страницы, новее страницы, пустая лента, внутри диапазона,
 * ответ с кнопкой (403-путь — без перехвата), дубликат в ленте, полная страница с «Ещё записи»
 * (запись старее показанного не вставляется — придёт с «Ещё записи», иначе дубль; план 462-463).
 *
 * Запуск: node backend/tests/harness_feed_read_move.js — выход 0, если все случаи прошли.
 * Браузер/стенд/pytest не нужны; это не e2e, а статическая проверка логики переноса.
 */
"use strict";
const fs = require("fs");
const path = require("path");

const FEED_JS = path.resolve(__dirname, "..", "static", "feed", "feed.js");

/* --- Минимальный DOM: только то, что читает/пишет обработчик feed.js --------------------------------- */

class El {
  constructor(tag, attrs) {
    this.tag = String(tag).toLowerCase();
    this.attrs = Object.assign({}, attrs || {});
    this.children = [];
    this.parentNode = null;
  }
  get parentElement() { return this.parentNode; }
  get id() { return this.attrs.id || ""; }
  set id(value) { this.attrs.id = value; }
  get dataset() {
    const store = {};
    for (const key of Object.keys(this.attrs)) {
      if (key.slice(0, 5) === "data-") {
        store[key.slice(5).replace(/-([a-z])/g, (m, c) => c.toUpperCase())] = this.attrs[key];
      }
    }
    return store;
  }
  get textContent() {
    return this.children.map((c) => (c instanceof El ? c.textContent : String(c))).join("");
  }
  matches(selector) { return matchesSimple(this, selector); }
  closest(selector) {
    let node = this;
    while (node) {
      if (node instanceof El && matchesSimple(node, selector)) { return node; }
      node = node.parentNode;
    }
    return null;
  }
  appendChild(node) {
    if (node.parentNode) { removeChild(node.parentNode, node); }
    node.parentNode = this;
    this.children.push(node);
    return node;
  }
  removeChild_(node) { return removeChild(this, node); }
  before(node) { insertSibling(this, node, 0); }
  after(node) { insertSibling(this, node, 1); }
  remove() { if (this.parentNode) { removeChild(this.parentNode, this); } }
  querySelector(selector) { return queryAll(this, selector)[0] || null; }
  querySelectorAll(selector) { return queryAll(this, selector); }
  hasAttribute(name) { return name in this.attrs; }
  setAttribute(name, value) { this.attrs[name] = value; }
  getAttribute(name) { return this.attrs[name] === undefined ? null : this.attrs[name]; }
}

function removeChild(parent, node) {
  const at = parent.children.indexOf(node);
  if (at >= 0) { parent.children.splice(at, 1); }
  node.parentNode = null;
}

function insertSibling(anchor, node, offset) {
  const parent = anchor.parentNode;
  if (!parent) { throw new Error("insertSibling: нет родителя"); }
  if (node.parentNode) { removeChild(node.parentNode, node); }
  const at = parent.children.indexOf(anchor) + offset;
  parent.children.splice(at, 0, node);
  node.parentNode = parent;
}

function matchesSimple(el, simple) {
  let rest = String(simple);
  const tag = /^[a-z][a-z0-9-]*/i.exec(rest);
  if (tag && tag[0].toLowerCase() === el.tag) { rest = rest.slice(tag[0].length); }
  const id = /^#([A-Za-z0-9_-]+)/.exec(rest);
  if (id) {
    if (el.attrs.id !== id[1]) { return false; }
    rest = rest.slice(id[0].length);
  }
  const attrRe = /\[([^\]=]+)(?:="([^"]*)")?\]/g;
  let used = 0;
  let m;
  while ((m = attrRe.exec(rest)) !== null) {
    used += m[0].length;
    if (!(m[1] in el.attrs)) { return false; }
    if (m[2] !== undefined && el.attrs[m[1]] !== m[2]) { return false; }
  }
  return rest.length === used;
}

function queryAll(root, selector) {
  if (selector === ":scope > li > article[data-post-id]") {
    const out = [];
    for (const li of root.children) {
      if (li instanceof El && li.tag === "li") {
        for (const article of li.children) {
          if (article instanceof El && article.tag === "article" && "data-post-id" in article.attrs) {
            out.push(article);
          }
        }
      }
    }
    return out;
  }
  const parts = String(selector).trim().split(/\s+/);
  const out = [];
  (function walk(node) {
    for (const child of node.children) {
      if (child instanceof El) {
        if (chainMatches(child, parts)) { out.push(child); }
        walk(child);
      }
    }
  })(root);
  return out;
}

function chainMatches(node, parts) {
  if (!matchesSimple(node, parts[parts.length - 1])) { return false; }
  let index = parts.length - 2;
  let parent = node.parentNode;
  while (parent instanceof El && index >= 0) {
    if (matchesSimple(parent, parts[index])) { index -= 1; }
    parent = parent.parentNode;
  }
  return index < 0;
}

/* --- Окружение: document / window / DOMParser / htmx -------------------------------------------------- */

const listeners = {};
const document = {
  addEventListener(name, fn) { (listeners[name] = listeners[name] || []).push(fn); },
  removeEventListener() {},
  querySelector(selector) { return queryAll(body, selector)[0] || null; },
  querySelectorAll(selector) { return queryAll(body, selector); },
  getElementById(id) {
    return (function walk(node) {
      for (const child of node.children) {
        if (child instanceof El) {
          if (child.attrs.id === id) { return child; }
          const found = walk(child);
          if (found) { return found; }
        }
      }
      return null;
    })(body);
  },
  createElement(tag) { return new El(tag); },
};
const htmx = {
  calls: { removed: [], processed: [], triggered: [] },
  remove(el) { this.calls.removed.push(el); el.remove(); },
  process(el) { this.calls.processed.push(el); },
  trigger(el, name) { this.calls.triggered.push([el, name]); },
};
const window = { htmx: htmx, setTimeout: setTimeout };
let responseDoc = null;
class DOMParser {
  parseFromString() { return responseDoc; }
}

const body = new El("body");
document.body = body;

/* --- Загрузка настоящего feed.js ----------------------------------------------------------------------- */

new Function("window", "document", "DOMParser", "Set", "WeakMap", "navigator", "location",
  fs.readFileSync(FEED_JS, "utf8"))(window, document, DOMParser, Set, WeakMap, {}, { href: "https://harness/" });

if (!listeners["htmx:beforeSwap"]) { throw new Error("feed.js не зарегистрировал обработчик htmx:beforeSwap"); }

/* --- Сценарии ------------------------------------------------------------------------------------------ */

function articleNode(id, datetime, withReadButton) {
  const article = new El("article", { id: `feed-post-${id}`, "data-post-id": String(id) });
  const header = new El("header");
  const time = new El("time", { "data-at": "", datetime: datetime });
  header.appendChild(time);
  article.appendChild(header);
  if (withReadButton) {
    const imp = new El("div", { id: `feed-post-${id}-imp`, "data-feed-imp": "" });
    imp.appendChild(new El("button", { type: "button", "data-action": "read" }));
    article.appendChild(imp);
  }
  return article;
}

function buildPage(listCards) {
  body.children.length = 0;
  const section = new El("section", { id: "feed-important", "data-feed-important": "" });
  const list = new El("ol", { id: "feed-list", "data-feed-list-main": "" });
  body.appendChild(section);
  body.appendChild(list);
  return { section, list };
}

function run(label, listTimes, cardTime, options) {
  const opts = options || {};
  const page = buildPage();
  const original = articleNode(60, "2026-11-10T10:00:00+03:00", true);
  page.section.appendChild(original);
  const readButton = original.querySelector('button[data-action="read"]');
  listTimes.forEach((pair) => {
    const row = new El("li");
    row.appendChild(articleNode(pair[0], pair[1]));
    page.list.appendChild(row);
  });
  if (opts.moreButton) {
    const row = new El("li", { "class": "feed-more" });
    row.appendChild(new El("a", { "data-feed-more": "", "hx-get": "/feed/more/?before=cursor" }));
    page.list.appendChild(row);
  }
  const card = articleNode(60, cardTime, opts.cardHasReadButton);
  responseDoc = new El("div");
  responseDoc.appendChild(card);
  const detail = {
    shouldSwap: true,
    serverResponse: `<article id="feed-post-60" data-post-id="60">…</article>`,
    xhr: { status: opts.status == null ? 200 : opts.status },
    requestConfig: { elt: readButton },
    target: original,
  };
  for (const fn of listeners["htmx:beforeSwap"]) {
    fn({ detail: detail, target: readButton });
  }
  const inList = queryAll(page.list, ":scope > li > article[data-post-id]").map((a) => a.dataset.postId);
  const inListDuplicates = inList.length !== new Set(inList).size;
  return {
    label,
    intercepted: detail.shouldSwap === false,
    removedFromBlock: !page.section.children.some((c) => c instanceof El && c.attrs.id === "feed-post-60"),
    list: inList,
    duplicates: inListDuplicates,
  };
}

const T = "2026-11-10T12:00:00+03:00";
const EARLIER = "2026-11-10T08:00:00+03:00";
const LATER = "2026-11-10T16:00:00+03:00";

const cases = [
  Object.assign(run("карточка старше страницы: встаёт в конец ленты", [["59", T]], EARLIER),
    { expect: { intercepted: true, removedFromBlock: true, list: ["59", "60"] } }),
  Object.assign(run("пустая лента: карточка — единственная строка", [], T),
    { expect: { intercepted: true, removedFromBlock: true, list: ["60"] } }),
  Object.assign(run("карточка новее страницы: встаёт наверх ленты", [["59", EARLIER]], LATER),
    { expect: { intercepted: true, removedFromBlock: true, list: ["60", "59"] } }),
  Object.assign(run("внутри диапазона: между соседями по времени", [["59", LATER], ["58", EARLIER]], T),
    { expect: { intercepted: true, removedFromBlock: true, list: ["59", "60", "58"] } }),
  Object.assign(run("ответ с кнопкой: перехвата нет, карточка на месте",
    [["59", T]], T, { cardHasReadButton: true }),
    { expect: { intercepted: false, removedFromBlock: false, list: ["59"] } }),
  Object.assign(run("уже в ленте: из блока убрана, дубль не создан",
    [["59", LATER], ["60", T]], EARLIER),
    { expect: { intercepted: true, removedFromBlock: true, list: ["59", "60"] } }),
];

/* Полная страница (20 строк + li.feed-more > a[data-feed-more]) и читаемая запись старше всех:
   карточку из блока убираем, в #feed-list НЕ вставляем (придёт с «Ещё записи», иначе дубль). */
const fullPage = [];
for (let i = 0; i < 20; i++) {
  fullPage.push([String(200 - i), `2026-11-10T12:${String(30 - i).padStart(2, "0")}:00+03:00`]);
}
const fullExpect = fullPage.map((pair) => pair[0]);
cases.push(Object.assign(
  run("полная страница с «Ещё записи»: запись старее показанного не вставляется",
    fullPage, EARLIER, { moreButton: true }),
  { expect: { intercepted: true, removedFromBlock: true, list: fullExpect } }));

let failed = 0;
for (const c of cases) {
  const e = c.expect;
  const bad = [];
  if (c.intercepted !== e.intercepted) { bad.push(`перехват ${c.intercepted}, ждали ${e.intercepted}`); }
  if (c.removedFromBlock !== e.removedFromBlock) { bad.push(`блок ${c.removedFromBlock}, ждали ${e.removedFromBlock}`); }
  if (JSON.stringify(c.list) !== JSON.stringify(e.list)) { bad.push(`лента ${JSON.stringify(c.list)}, ждали ${JSON.stringify(e.list)}`); }
  if (c.duplicates) { bad.push("дубль карточки в ленте"); }
  if (bad.length) {
    failed += 1;
    console.error(`FAIL  ${c.label}: ${bad.join("; ")}`);
  } else {
    console.log(`ok    ${c.label}`);
  }
}
if (failed) {
  console.error(`\nharness: ${failed} из ${cases.length} случаев провалены (G4: перенос прочитанной записи).`);
  process.exit(1);
}
console.log("\nharness: все случаи прошли.");
