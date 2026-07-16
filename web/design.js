// Design tab: lists the design/ markdown pages served by the C2 API and
// renders them client-side. The renderer builds DOM nodes directly
// (createElement/textContent only) — same no-HTML-injection rule as app.js.
"use strict";

const designState = { pages: [], current: null, indexLoaded: false };

const viewLive = document.getElementById("view-live");
const viewDesign = document.getElementById("view-design");
const tabLive = document.getElementById("tab-live");
const tabDesign = document.getElementById("tab-design");
const designList = document.getElementById("design-list");
const designContent = document.getElementById("design-content");

// ── markdown → DOM ───────────────────────────────────────────────────────────

// inline tokens: `code`, **bold**, *em*, [label](href) — earliest match wins
const INLINE_RE = /`([^`]+)`|\*\*([^*]+)\*\*|\*([^*]+)\*|\[([^\]]+)\]\(([^)\s]+)\)/;
const PAGE_LINK_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*\.md$/;

function appendLink(label, href, parent) {
  const a = document.createElement("a");
  if (PAGE_LINK_RE.test(href)) {
    a.href = "#design/" + href;           // in-app link between design pages
  } else if (/^https?:\/\//.test(href)) {
    a.href = href;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
  } else {                                // unknown scheme: label as plain text
    renderInline(label, parent);
    return;
  }
  renderInline(label, a);
  parent.appendChild(a);
}

function renderInline(text, parent) {
  let rest = text;
  while (rest) {
    const m = INLINE_RE.exec(rest);
    if (!m) {
      parent.appendChild(document.createTextNode(rest));
      return;
    }
    if (m.index > 0) {
      parent.appendChild(document.createTextNode(rest.slice(0, m.index)));
    }
    if (m[1] !== undefined) {
      const code = document.createElement("code");
      code.textContent = m[1];
      parent.appendChild(code);
    } else if (m[2] !== undefined) {
      const strong = document.createElement("strong");
      renderInline(m[2], strong);
      parent.appendChild(strong);
    } else if (m[3] !== undefined) {
      const em = document.createElement("em");
      renderInline(m[3], em);
      parent.appendChild(em);
    } else {
      appendLink(m[4], m[5], parent);
    }
    rest = rest.slice(m.index + m[0].length);
  }
}

const LIST_ITEM_RE = /^(\s*)([-*]|\d+\.)\s+(.*)$/;

function buildList(items) {
  const base = items[0].indent;
  const list = document.createElement(items[0].ordered ? "ol" : "ul");
  let k = 0;
  while (k < items.length) {
    const li = document.createElement("li");
    renderInline(items[k].text, li);
    k++;
    const sub = [];
    while (k < items.length && items[k].indent > base) sub.push(items[k++]);
    if (sub.length) li.appendChild(buildList(sub));
    list.appendChild(li);
  }
  return list;
}

function splitTableRow(line) {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split(/(?<!\\)\|/).map(cell => cell.trim().replace(/\\\|/g, "|"));
}

function isTableSeparator(line) {
  return line !== undefined && /^\|?[\s:|-]+\|?$/.test(line.trim())
    && line.includes("-");
}

function startsBlock(line) {
  return /^(#{1,4})\s/.test(line) || line.startsWith("```")
    || line.startsWith(">") || line.startsWith("|")
    || LIST_ITEM_RE.test(line) || /^(-{3,}|\*{3,})\s*$/.test(line.trim());
}

function renderMarkdown(text) {
  const lines = text.split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === "") { i++; continue; }

    if (line.startsWith("```")) {                       // fenced code block
      const code = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) code.push(lines[i++]);
      i++;
      const pre = document.createElement("pre");
      const codeEl = document.createElement("code");
      codeEl.textContent = code.join("\n");
      pre.appendChild(codeEl);
      out.push(pre);
      continue;
    }

    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      const h = document.createElement("h" + heading[1].length);
      renderInline(heading[2], h);
      out.push(h);
      i++;
      continue;
    }

    if (/^(-{3,}|\*{3,})\s*$/.test(line.trim())) {      // horizontal rule
      out.push(document.createElement("hr"));
      i++;
      continue;
    }

    if (line.startsWith(">")) {                         // blockquote
      const quoted = [];
      while (i < lines.length && lines[i].startsWith(">")) {
        quoted.push(lines[i].replace(/^>\s?/, ""));
        i++;
      }
      const quote = document.createElement("blockquote");
      for (const node of renderMarkdown(quoted.join("\n"))) quote.appendChild(node);
      out.push(quote);
      continue;
    }

    if (LIST_ITEM_RE.test(line)) {                      // list (nested by indent)
      const items = [];
      while (i < lines.length) {
        const m = LIST_ITEM_RE.exec(lines[i]);
        if (m) {
          items.push({ indent: m[1].length, ordered: /\d/.test(m[2]), text: m[3] });
          i++;
        } else if (lines[i].trim() !== "" && /^\s/.test(lines[i])) {
          items[items.length - 1].text += " " + lines[i].trim();   // continuation
          i++;
        } else break;
      }
      out.push(buildList(items));
      continue;
    }

    if (line.startsWith("|") && isTableSeparator(lines[i + 1])) {   // table
      const table = document.createElement("table");
      const thead = document.createElement("thead");
      const headRow = document.createElement("tr");
      for (const cell of splitTableRow(line)) {
        const th = document.createElement("th");
        renderInline(cell, th);
        headRow.appendChild(th);
      }
      thead.appendChild(headRow);
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      i += 2;
      while (i < lines.length && lines[i].startsWith("|")) {
        const tr = document.createElement("tr");
        for (const cell of splitTableRow(lines[i])) {
          const cellEl = document.createElement("td");
          renderInline(cell, cellEl);
          tr.appendChild(cellEl);
        }
        tbody.appendChild(tr);
        i++;
      }
      table.appendChild(tbody);
      out.push(table);
      continue;
    }

    const para = [line.trim()];                          // paragraph
    i++;
    while (i < lines.length && lines[i].trim() !== "" && !startsBlock(lines[i])) {
      para.push(lines[i].trim());
      i++;
    }
    const p = document.createElement("p");
    renderInline(para.join(" "), p);
    out.push(p);
  }
  return out;
}

// ── data loading ─────────────────────────────────────────────────────────────

function renderStatus(message) {
  const p = document.createElement("p");
  p.className = "md-status";
  p.textContent = message;
  designContent.replaceChildren(p);
}

function renderPageList() {
  designList.replaceChildren();
  for (const page of designState.pages) {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.textContent = page.title;
    button.className = page.file === designState.current ? "active" : "";
    button.addEventListener("click", () => {
      location.hash = "#design/" + page.file;
    });
    li.appendChild(button);
    designList.appendChild(li);
  }
}

async function loadDesignIndex() {
  designState.indexLoaded = true;
  try {
    const body = await (await fetch("/api/design")).json();
    if (!body.ok) throw new Error(body.error);
    designState.pages = body.data.pages;
    renderPageList();
    if (!designState.current && designState.pages.length) {
      loadDesignPage(designState.pages[0].file);
    }
  } catch (err) {
    designState.indexLoaded = false;    // retry on next tab visit
    renderStatus("failed to load the page list: " + err);
  }
}

async function loadDesignPage(file) {
  designState.current = file;
  renderPageList();
  renderStatus("loading…");
  try {
    const body = await (await fetch("/api/design/" + encodeURIComponent(file))).json();
    if (!body.ok) throw new Error(body.error);
    if (designState.current !== file) return;   // superseded by a later click
    designContent.replaceChildren(...renderMarkdown(body.data.markdown));
    window.scrollTo(0, 0);
  } catch (err) {
    if (designState.current === file) {
      renderStatus(`failed to load ${file}: ` + err);
    }
  }
}

// ── tab switching (hash-routed: #design, #design/<file>) ────────────────────

function showTab(tab) {
  const design = tab === "design";
  viewLive.hidden = design;
  viewDesign.hidden = !design;
  tabLive.classList.toggle("active", !design);
  tabDesign.classList.toggle("active", design);
  if (design && !designState.indexLoaded) loadDesignIndex();
}

function applyLocationHash() {
  if (location.hash.startsWith("#design")) {
    showTab("design");
    let file = null;
    if (location.hash.startsWith("#design/")) {
      try {
        file = decodeURIComponent(location.hash.slice("#design/".length));
      } catch { file = null; }   // malformed percent-encoding
    }
    if (file && PAGE_LINK_RE.test(file) && file !== designState.current) {
      loadDesignPage(file);
    }
  } else {
    showTab("live");
  }
}

tabLive.addEventListener("click", () => { location.hash = "#live"; });
tabDesign.addEventListener("click", () => {
  location.hash = designState.current
    ? "#design/" + designState.current : "#design";
});
window.addEventListener("hashchange", applyLocationHash);
applyLocationHash();
