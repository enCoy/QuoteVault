// Quote Vault interface. Plain JavaScript, no build step.

// ------------------------------------------------------------------ helpers

const view = document.getElementById("view");

// Replace what the page shows. Empty entries (null, false) are skipped.
function mount(...kids) {
  view.replaceChildren(...kids.flat(Infinity).filter((k) => k != null && k !== false));
}

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k in el && k !== "list" && k !== "form") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

async function api(path, { method, body, form } = {}) {
  const opts = { method: method || (body || form ? "POST" : "GET") };
  if (body) { opts.headers = { "Content-Type": "application/json" }; opts.body = JSON.stringify(body); }
  if (form) opts.body = form;
  let res;
  try { res = await fetch(path, opts); }
  catch (e) { throw new Error("Quote Vault is not running on the Mac."); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Something went wrong.");
  return data;
}

function toast(message, action) {
  const el = h("div", { class: "toast" }, h("span", {}, message));
  if (action) el.append(h("button", { onclick: () => { el.remove(); action.run(); } }, action.label));
  document.getElementById("toasts").append(el);
  setTimeout(() => el.remove(), action ? 12000 : 4000);
}

const store = {
  get(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch (e) { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* private mode */ } },
};

const enc = encodeURIComponent;
const sourceHref = (kind, slug) => `#/source/${kind}/${enc(slug)}`;
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

const STATUS = {
  "yes": "Verified",
  "likely": "Likely genuine",
  "reader-posted": "Found on reader sites",
  "suggestion": "A source words it differently",
  "candidate": "Possible English original found",
  "not found": "Not found in sources",
  "unchecked": "Not checked yet",
};

// The three kinds of file a card can live in.
const KIND = {
  book: { label: "Book", plural: "Books", folder: "books", add: "＋ New book", none: "No books yet", first: "Add a book first." },
  person: { label: "Person", plural: "People", folder: "people", add: "＋ New person", none: "No people yet", first: "Add a person first." },
  topic: { label: "Topic", plural: "Topics", folder: "topics", add: "＋ New topic", none: "No topics yet", first: "Add a topic first." },
};
const KINDS = Object.keys(KIND);
// A book card has a page; person and topic cards have a free-text "where".
const whereField = (kind) => (kind === "book" ? "page" : "source");
const whereText = (kind) => (kind === "book" ? "Page" : kind === "person" ? "Where it was said" : "Where it is from");
const wherePlaceholder = (kind) => (kind === "book" ? "142" : kind === "person" ? "a speech, an interview, a year" : "a book, a site, a lecture");

const state = { overview: null, status: { llm: false, voice: false } };

async function loadOverview() {
  state.overview = await api("/api/overview");
  return state.overview;
}

// Evidence is stored as "Source: Title — https://link | optional note".
function evidenceParts(evidence) {
  const [main, note] = (evidence || "").split(" | ");
  const cut = main.lastIndexOf(" — http");
  return cut < 0 ? { label: main, url: "", note } : { label: main.slice(0, cut), url: main.slice(cut + 3), note };
}

function evidenceNode(evidence) {
  const { label, url, note } = evidenceParts(evidence);
  if (!label && !note) return null;
  return h("span", {},
    url ? h("a", { href: url, target: "_blank", rel: "noopener" }, label) : label,
    note ? ` ${label ? "· " : ""}${note}` : "");
}

// Words of `after` that differ from `before` are wrapped in <mark>.
function markChanges(before, after) {
  const a = before.split(/\s+/), out = h("span", { class: "say" });
  after.split(/(\s+)/).forEach((tok, i) => {
    if (i % 2) out.append(tok);
    else out.append(a.includes(tok) ? tok : h("mark", {}, tok));
  });
  return out;
}

// ------------------------------------------------------------------ dialogs

function openDialog(title, build) {
  const dlg = h("dialog");
  const form = h("form", { method: "dialog" }, h("h3", {}, title));
  dlg.append(form);
  const close = (value) => { dlg.close(); dlg.remove(); done(value); };
  let done;
  const result = new Promise((resolve) => { done = resolve; });
  build(form, close);
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(null); });
  dlg.addEventListener("click", (e) => { if (e.target === dlg) close(null); });
  document.body.append(dlg);
  dlg.showModal();
  return result;
}

function field(label, input) { return h("label", { class: "field" }, h("span", {}, label), input); }

// Like field(), for a control with buttons of its own. It must not sit inside a <label>:
// a label hands clicks on to the first button in it, so one click on a tag's cross
// would remove that tag and then the next one as well.
function group(label, control) { return h("div", { class: "field", role: "group", "aria-label": label }, h("span", {}, label), control); }

function confirmDialog(title, text, okLabel) {
  return openDialog(title, (form, close) => {
    form.append(h("p", { style: "margin:0" }, text), h("div", { class: "row end" },
      h("button", { class: "btn", type: "button", onclick: () => close(false) }, "Cancel"),
      h("button", { class: "btn primary", type: "button", onclick: () => close(true) }, okLabel)));
  });
}

const BOOK_FIELDS = [
  ["title", "Title"], ["author", "Author"], ["year", "Year"], ["publisher", "Publisher"],
  ["translator", "Translator"], ["original_title", "Original title"], ["isbn", "ISBN"], ["pages", "Pages"],
];
const PERSON_FIELDS = [["name", "Name"], ["description", "Who they are"], ["born", "Born"], ["died", "Died"]];
const TOPIC_FIELDS = [["name", "Topic"], ["description", "What it covers"]];
const SOURCE_FIELDS = { book: BOOK_FIELDS, person: PERSON_FIELDS, topic: TOPIC_FIELDS };

// Add or edit a book, person or topic. Resolves to the saved source summary, or null.
function sourceDialog(kind, existing) {
  const isBook = kind === "book";
  const meta = { ...(existing ? existing.meta : {}) };
  return openDialog(existing ? `Edit ${kind}` : `New ${kind}`, (form, close) => {
    const inputs = {};
    const fields = h("div", { class: "fields", style: "margin-top:0" });
    for (const [key, label] of SOURCE_FIELDS[kind]) {
      inputs[key] = h("input", { value: meta[key] ?? "", name: key, autocomplete: "off" });
      fields.append(field(label, inputs[key]));
    }
    const selects = {};
    if (isBook) {
      const opts = (sel) => [["", "Not sure"], ["tr", "Turkish"], ["en", "English"], ["other", "Other"]]
        .map(([v, t]) => h("option", { value: v, selected: (sel || "") === v }, t));
      selects.language = h("select", {}, opts(meta.language));
      selects.original_language = h("select", {}, opts(meta.original_language));
      fields.append(field("Language of this edition", selects.language),
                    field("Originally written in", selects.original_language));
    }
    const results = h("div", { class: "results" });
    const hint = h("div", { class: "hint" }, isBook
      ? "Type a title (and author), then look it up to fill in the rest."
      : kind === "person" ? "Type a name, then look it up to fill in the rest."
      : "A topic holds cards that are not from one book or person, such as facts about a subject.");
    const fill = (r) => {
      for (const [key] of SOURCE_FIELDS[kind]) if (r[key] != null && r[key] !== "") inputs[key].value = r[key];
      if (isBook) {
        if (["tr", "en"].includes(r.language)) selects.language.value = r.language;
        else if (r.language) selects.language.value = "other";
        meta.cover = r.cover || meta.cover;
      } else meta.image = r.image || meta.image;
      results.replaceChildren();
      hint.textContent = "Filled in. Change anything that is not right.";
    };
    const lookup = async () => {
      if (kind === "topic") return;
      const q = isBook ? `${inputs.title.value} ${inputs.author.value}`.trim() : inputs.name.value.trim();
      if (!q) return;
      hint.replaceChildren(h("span", { class: "spin" }), "Looking it up…");
      results.replaceChildren();
      try {
        const data = await api(`/api/lookup/${isBook ? "books" : "people"}?q=${enc(q)}`);
        if (!data.online) hint.textContent = "Could not reach the lookup services. You can fill the details in by hand.";
        else if (!data.results.length) hint.textContent = "Nothing found. You can fill the details in by hand.";
        else hint.textContent = "Pick the right one:";
        for (const r of data.results) {
          const pic = r.cover || r.image;
          results.append(h("button", { class: "result", type: "button", onclick: () => fill(r) },
            pic ? h("img", { src: pic, alt: "", loading: "lazy" }) : h("span", { class: "ph" }),
            h("div", {}, h("div", { class: "t" }, r.title || r.name),
              h("div", { class: "s" }, isBook
                ? [r.author, r.year, r.publisher].filter(Boolean).join(" · ")
                : [r.description, r.born && `${r.born}–${r.died ?? ""}`].filter(Boolean).join(" · ")))));
        }
      } catch (e) { hint.textContent = e.message; }
    };
    const first = inputs[isBook ? "title" : "name"];
    first.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); lookup(); } });
    const error = h("div", { class: "hint", style: "color:var(--red)" });
    const save = async () => {
      const out = { ...meta };
      for (const [key, input] of Object.entries(inputs)) out[key] = input.value.trim();
      for (const [key, sel] of Object.entries(selects)) out[key] = sel.value;
      try {
        const saved = existing
          ? await api(`/api/sources/${kind}/${enc(existing.slug)}`, { method: "PATCH", body: { meta: out } })
          : await api("/api/sources", { body: { kind, meta: out } });
        await loadOverview();
        close(saved);
      } catch (e) { error.textContent = e.message; }
    };
    form.append(fields, h("div", { class: "row" },
      kind === "topic" ? null : h("button", { class: "btn", type: "button", onclick: lookup }, "Look up details"), hint),
      results, error, h("div", { class: "row end" },
        h("button", { class: "btn", type: "button", onclick: () => close(null) }, "Cancel"),
        h("button", { class: "btn primary", type: "button", onclick: save }, existing ? "Save" : `Add ${kind}`)));
    setTimeout(() => first.focus(), 30);
  });
}

function tagEditor(initial, getSuggestions) {
  let tags = [...initial];
  const input = h("input", { placeholder: "add a tag", autocomplete: "off", autocapitalize: "off", "aria-label": "Add a tag" });
  const listId = `tags-${Math.random().toString(36).slice(2)}`;
  const datalist = h("datalist", { id: listId });
  input.setAttribute("list", listId);
  const box = h("div", { class: "tag-input", onclick: () => input.focus() });
  const draw = () => {
    box.replaceChildren(...tags.map((t) => h("span", { class: "chip" }, t,
      h("button", { class: "x", type: "button", "aria-label": `Remove ${t}`,
        onclick: (e) => { e.preventDefault(); e.stopPropagation(); tags = tags.filter((x) => x !== t); draw(); } }, "×"))), input, datalist);
    datalist.replaceChildren(...(getSuggestions ? getSuggestions() : []).filter((t) => !tags.includes(t))
      .map((t) => h("option", { value: t })));
  };
  const commit = () => {
    for (const t of input.value.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean)) if (!tags.includes(t)) tags.push(t);
    input.value = "";
    draw();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); commit(); }
    else if (e.key === "Backspace" && !input.value && tags.length) { tags.pop(); draw(); }
  });
  input.addEventListener("change", commit);
  input.addEventListener("blur", commit);
  draw();
  return { el: box, get: () => { commit(); return [...tags]; }, set: (t) => { tags = [...t]; draw(); },
           add: (more) => { for (const t of more) if (!tags.includes(t)) tags.push(t); draw(); } };
}

const allTags = () => (state.overview ? state.overview.tags.map((t) => t.tag) : []);

function editQuoteDialog(q) {
  return openDialog("Edit card", (form, close) => {
    const text = h("textarea", { value: q.text });
    const where = h("input", { value: q[whereField(q.kind)] });
    const type = h("select", {}, [["quote", "Quote"], ["fact", "Fact"]].map(([v, t]) => h("option", { value: v, selected: q.type === v }, t)));
    const keyword = h("input", { class: "hand", value: q.keyword });
    const note = h("input", { value: q.note });
    const original = h("input", { value: q.original });
    const lang = h("select", {}, [["tr", "Turkish"], ["en", "English"]].map(([v, t]) => h("option", { value: v, selected: q.lang === v }, t)));
    const tags = tagEditor(q.tags, allTags);
    const error = h("div", { class: "hint", style: "color:var(--red)" });
    const save = async () => {
      const fields = { text: text.value, type: type.value, keyword: keyword.value, note: note.value, tags: tags.get(), lang: lang.value, original: original.value };
      fields[whereField(q.kind)] = where.value;
      if (text.value.trim() !== q.text) Object.assign(fields, { verified: "unchecked", suggestion: "", evidence: "" });
      try { close(await api(`/api/quotes/${q.id}`, { method: "PATCH", body: { fields } })); }
      catch (e) { error.textContent = e.message; }
    };
    form.append(field("Text", text),
      h("div", { class: "fields", style: "margin-top:0" },
        field("Kind of card", type), field(whereText(q.kind), where), field("My keyword", keyword), field("Language", lang)),
      field("Note", note), group("Tags", tags.el),
      q.original || q.lang === "tr" ? field("English original", original) : null, error,
      h("div", { class: "row end" },
        h("button", { class: "btn", type: "button", onclick: () => close(null) }, "Cancel"),
        h("button", { class: "btn primary", type: "button", onclick: save }, "Save")));
  });
}

function sourceOptions(kind, selected) {
  const list = state.overview.sources.filter((s) => s.kind === kind);
  return list.map((s) => h("option", { value: s.slug, selected: s.slug === selected },
    kind === "book" && s.author ? `${s.title} — ${s.author}` : s.title));
}

function moveDialog(q) {
  return openDialog("Move card", (form, close) => {
    let kind = "book";
    const select = h("select", { class: "plain" });
    const seg = h("div", { class: "seg" });
    const draw = () => {
      seg.replaceChildren(...KINDS.map((k) => h("button", { type: "button", "aria-pressed": String(k === kind),
        onclick: () => { kind = k; draw(); } }, KIND[k].label)));
      const options = sourceOptions(kind, null).filter((o) => !(kind === q.kind && o.value === q.slug));
      select.replaceChildren(...options);
    };
    draw();
    const go = async () => {
      if (!select.value) return;
      close(await api(`/api/quotes/${q.id}/move`, { body: { kind, slug: select.value } }));
    };
    form.append(h("p", { class: "hint", style: "margin:0" }, `Now in: ${q.title}`), h("div", { class: "row" }, seg, h("div", { class: "grow" }, select)),
      h("div", { class: "row end" },
        h("button", { class: "btn", type: "button", onclick: () => close(null) }, "Cancel"),
        h("button", { class: "btn primary", type: "button", onclick: go }, "Move here")));
  });
}

// What to store when the user says a match is wrong: the card goes back to "not found"
// and is not checked again automatically. An English original that came with the match goes too.
function wrongMatch(q) {
  const fields = { verified: "not found", evidence: "", suggestion: "" };
  if (["candidate", "likely"].includes(q.verified)) fields.original = "";
  return fields;
}

// "Did you mean" for a saved card, or confirmation of a cross-language match.
function resolveDialog(q) {
  const patch = (fields) => api(`/api/quotes/${q.id}`, { method: "PATCH", body: { fields } });
  const ev = evidenceNode(q.evidence);
  if (q.verified === "suggestion") {
    return openDialog("Did you mean…?", (form, close) => {
      form.append(
        h("div", { class: "note-box" }, h("div", { class: "title" }, "Your card"), h("span", { class: "say" }, q.text)),
        h("div", { class: "note-box warn" }, h("div", { class: "title" }, "The source has"), markChanges(q.text, q.suggestion),
          ev ? h("div", { class: "hint" }, ev) : null),
        h("div", { class: "row end" },
          h("button", { class: "btn quiet", type: "button", title: "The source is about something else", onclick: async () => close(await patch(wrongMatch(q))) }, "Wrong match"),
          h("span", { class: "grow" }),
          h("button", { class: "btn", type: "button", onclick: async () => close(await patch({ verified: "likely", suggestion: "" })) }, "Keep mine"),
          h("button", { class: "btn primary", type: "button", onclick: async () => close(await patch({ text: q.suggestion, verified: "yes", suggestion: "" })) }, "Use the source wording")));
    });
  }
  return openDialog("Is this the original passage?", (form, close) => {
    form.append(
      h("div", { class: "note-box" }, h("div", { class: "title" }, "Your card"), h("span", { class: "say" }, q.text)),
      h("div", { class: "note-box warn" }, h("div", { class: "title" }, "English passage found"), h("span", { class: "say" }, q.original),
        ev ? h("div", { class: "hint" }, ev) : null),
      h("p", { class: "hint", style: "margin:0" }, "Confirming marks the card as likely genuine and keeps the English sentence on its back. It does not check the Turkish wording."),
      h("div", { class: "row end" },
        h("button", { class: "btn", type: "button", onclick: async () => close(await patch({ verified: "not found", original: "", evidence: "" })) }, "Not the same"),
        h("button", { class: "btn primary", type: "button", onclick: async () => close(await patch({ verified: "likely" })) }, "Yes, that's it")));
  });
}

// -------------------------------------------------------------------- cards

// Checks that run after a card is saved. They update the card when they finish.
async function backgroundChecks(q, onUpdate) {
  if (q.type === "fact") return;      // the web check compares wording; it does not apply to facts
  try {
    let current = q;
    if (current.verified === "unchecked") {
      const r = await api(`/api/quotes/${q.id}/check`, { method: "POST" });
      current = r.quote;
      onUpdate?.(current);
      if (r.outcome === "suggestion") toast("A source words that quote differently.", { label: "Compare", run: async () => { const u = await resolveDialog(current); if (u) onUpdate?.(u); } });
    }
    if (current.verified === "not found" && current.lang === "tr" && state.status.crosscheck) {
      const r = await api(`/api/quotes/${q.id}/crosscheck`, { method: "POST" });
      if (r.outcome === "candidate") {
        onUpdate?.(r.quote);
        toast("Found a possible English original.", { label: "Look", run: async () => { const u = await resolveDialog(r.quote); if (u) onUpdate?.(u); } });
      }
    }
  } catch (e) { /* stays unchecked; picked up again next time */ }
}

function quoteCard(q, { big = false, onChange, onRemove } = {}) {
  const card = h("article", { class: `card${big ? " big" : ""}` });
  card.dataset.type = q.type;
  const update = (next) => { if (!next) return; q = next; draw(); onChange?.(q); };

  function draw() {
    const flipped = card.classList.contains("flipped");
    const star = h("button", { class: `star${q.favorite ? " on" : ""}`, type: "button", title: q.favorite ? "Remove from favorites" : "Add to favorites",
      "aria-label": "Favorite", "aria-pressed": String(q.favorite),
      onclick: async (e) => { e.stopPropagation(); update(await api(`/api/quotes/${q.id}`, { method: "PATCH", body: { fields: { favorite: !q.favorite } } })); } }, "★");
    const isFact = q.type === "fact";
    const where = q.kind === "book" ? (q.page ? `p. ${q.page}` : "") : q.source;
    // A topic card has no author; its topic is already in the card's heading, so only
    // show where the information came from, if that was filled in.
    const by = q.kind === "topic"
      ? (where ? h("div", { class: "by" }, "— ", where) : h("div", { class: "by" }, "\u00a0"))
      : h("div", { class: "by" }, "— ", q.author || "Unknown",
          q.kind === "book" ? [", ", h("cite", {}, q.title)] : null, where ? ` · ${where}` : "");
    const front = h("section", { class: "face front paper" },
      h("div", { class: "card-head" },
        isFact ? h("span", { class: "badge" }, "Fact") : h("span", { class: `dot ${q.verified.replace(" ", "-")}`, title: STATUS[q.verified] }),
        h("a", { class: "where", href: sourceHref(q.kind, q.slug), onclick: (e) => e.stopPropagation() }, q.title), star),
      h("blockquote", {}, big ? h("span", {}, q.text) : q.text), by,
      !isFact && ["suggestion", "candidate"].includes(q.verified)
        ? h("button", { class: "flag", type: "button", onclick: async (e) => { e.stopPropagation(); update(await resolveDialog(q)); } },
            q.verified === "suggestion" ? "Did you mean…? A source words this differently." : "Possible English original found. Have a look.")
        : null);

    const ev = evidenceNode(q.evidence);
    const act = (label, fn, cls = "") => h("button", { class: `btn quiet ${cls}`, type: "button", onclick: (e) => { e.stopPropagation(); fn(e.currentTarget); } }, label);
    const back = h("section", { class: "face back paper" },
      h("div", { class: "card-head" }, h("span", { class: "where" }, q.added ? `Added ${q.added}` : ""), h("span", {}, (q.lang || "").toUpperCase())),
      h("div", { class: `keyword${q.keyword ? "" : " none"}` }, q.keyword || "no keyword"),
      h("div", { class: "chips" }, q.tags.map((t) => h("a", { class: "chip", href: `#/quotes?tag=${enc(t)}`, onclick: (e) => e.stopPropagation() }, t))),
      q.note ? [h("div", { class: "label" }, "Note"), h("p", { class: "note" }, q.note)] : null,
      q.original ? [h("div", { class: "label" }, "English original"), h("p", { class: "original" }, q.original)] : null,
      h("div", { class: "spacer" }),
      isFact ? h("div", { class: "meta" }, "Fact") : h("div", { class: "meta" }, STATUS[q.verified], ev ? [" · ", ev] : null,
        q.evidence || ["yes", "likely", "reader-posted", "suggestion", "candidate"].includes(q.verified)
          ? [" · ", h("button", { class: "linkish", type: "button", title: "Remove this match from the card",
              onclick: async (e) => { e.stopPropagation(); update(await api(`/api/quotes/${q.id}`, { method: "PATCH", body: { fields: wrongMatch(q) } })); toast("Match removed."); } }, "Wrong match")]
          : null),
      h("div", { class: "card-actions" },
        act("Edit", async () => update(await editQuoteDialog(q))),
        act("Move", async () => { const moved = await moveDialog(q); if (moved) { update(moved); toast(`Moved to ${moved.title}.`); } }),
        isFact ? null : act("Check now", async (btn) => {
          btn.disabled = true; btn.textContent = "Checking…";
          try {
            const r = await api(`/api/quotes/${q.id}/check`, { method: "POST" });
            if (r.outcome === "offline") toast("The sources could not be reached. Try again later.");
            update(r.quote);
            backgroundChecks(r.quote, update);
          } catch (e) { toast(e.message); draw(); }
        }),
        act("Delete", async () => {
          if (!(await confirmDialog("Delete this card?", "It will be removed from the file. This cannot be undone.", "Delete"))) return;
          await api(`/api/quotes/${q.id}`, { method: "DELETE" });
          card.remove(); onRemove?.(q);
        }, "danger")));
    card.replaceChildren(h("div", { class: "card-inner" }, front, back));
    card.classList.toggle("flipped", flipped);
  }

  card.addEventListener("click", (e) => {
    if (e.target.closest("a, button, input, select, textarea") || window.getSelection().toString()) return;
    card.classList.toggle("flipped");
  });
  card.update = update;
  card.flip = () => card.classList.toggle("flipped");
  draw();
  return card;
}

function cardGrid(quotes, emptyText) {
  if (!quotes.length) return h("p", { class: "empty" }, emptyText);
  return h("div", { class: "cards" }, quotes.map((q) => quoteCard(q, { onRemove: () => loadOverview() })));
}

// ------------------------------------------------------------ capture view

const MIC_ICON = () => {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2"); svg.setAttribute("stroke-linecap", "round");
  svg.innerHTML = '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>';
  return svg;
};

async function viewCapture() {
  const ov = await loadOverview();
  const saved = store.get("qv-capture", {});
  let kind = KINDS.includes(saved.kind) ? saved.kind : "book";
  let cardType = saved.type === "fact" ? "fact" : "quote";
  let lang = ["tr", "en"].includes(saved.lang) ? saved.lang : "auto";
  let check = null;          // result of the web check for `checkedText`
  let checkedText = "";
  let choice = "";           // "accepted" or "kept" once a did-you-mean was answered
  let detected = "";
  let favorite = false;
  let runId = 0;

  const remember = () => store.set("qv-capture", { kind, lang, type: cardType, slug: { ...saved.slug, [kind]: select.value } });
  saved.slug = saved.slug || {};

  const select = h("select", { class: "plain", "aria-label": "Book, person or topic", onchange: () => { remember(); drawWhere(); } });
  const seg = h("div", { class: "seg" });
  const addBtn = h("button", { class: "btn", type: "button", onclick: async () => {
    const made = await sourceDialog(kind);
    if (made) { saved.slug[kind] = made.slug; drawSource(); remember(); text.focus(); }
  } });
  const where = h("input", {});
  const whereLabel = h("span", {});
  function drawWhere() { whereLabel.textContent = whereText(kind); where.placeholder = wherePlaceholder(kind); }
  function drawSource() {
    seg.replaceChildren(...KINDS.map((k) => h("button", { type: "button", "aria-pressed": String(k === kind),
      onclick: () => { kind = k; drawSource(); remember(); } }, KIND[k].label)));
    const options = sourceOptions(kind, saved.slug[kind]);
    select.replaceChildren(...(options.length ? options : [h("option", { value: "" }, KIND[kind].none)]));
    addBtn.textContent = KIND[kind].add;
    drawWhere();
  }

  // Quote (someone's words) or fact (a piece of information to remember).
  const typeSeg = h("div", { class: "seg", role: "group", "aria-label": "Kind of card" });
  const tidyBtn = h("button", { class: "btn", type: "button", title: "⌘ Enter", onclick: () => tidy() });
  const tidyHint = h("span", { class: "hint grow" });
  function drawType() {
    typeSeg.replaceChildren(...[["quote", "Quote"], ["fact", "Fact"]].map(([v, t]) => h("button", { type: "button", "aria-pressed": String(v === cardType),
      onclick: () => { cardType = v; check = null; choice = ""; drawType(); drawReview(); remember(); } }, t)));
    const fact = cardType === "fact";
    text.placeholder = fact ? "Type the fact you want to remember…" : "Type the sentence you highlighted…";
    text.setAttribute("aria-label", fact ? "Fact" : "Quote");
    tidyBtn.textContent = fact ? "Tidy" : state.status.llm ? "Tidy & check" : "Check";
    tidyHint.textContent = fact
      ? (state.status.llm ? "Tidy fixes Turkish letters and typos and suggests tags. Facts are not looked up online." : "Tidy puts Turkish letters back. Facts are not looked up online.")
      : (state.status.llm ? "Tidy fixes Turkish letters and typos, suggests tags, and checks the quote online." : "Check looks the quote up online.");
  }

  const text = h("textarea", { class: "quote", rows: 5, placeholder: "Type the sentence you highlighted…", "aria-label": "Quote" });
  text.setAttribute("spellcheck", "false");     // the app does its own tidy-up; red underlines on Turkish are noise
  const grow = () => { text.style.height = "auto"; text.style.height = `${text.scrollHeight + 2}px`; };
  text.addEventListener("input", () => { grow(); if (text.value.trim() !== checkedText) { check = null; choice = ""; drawReview(); } });
  text.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); tidy(); } });

  const langSeg = h("div", { class: "seg", role: "group", "aria-label": "Language" });
  const drawLang = () => langSeg.replaceChildren(...[["auto", "Auto"], ["tr", "TR"], ["en", "EN"]].map(([v, t]) =>
    h("button", { type: "button", "aria-pressed": String(v === lang), onclick: () => { lang = v; drawLang(); remember(); } }, t)));

  const keyword = h("input", { class: "hand", placeholder: "one word for the back" });
  const note = h("input", { placeholder: "your own thought" });
  const tags = tagEditor([], allTags);
  const star = h("button", { class: "star", type: "button", title: "Favorite", "aria-label": "Favorite", style: "font-size:1.5rem",
    onclick: () => { favorite = !favorite; star.classList.toggle("on", favorite); star.setAttribute("aria-pressed", String(favorite)); } }, "★");

  // --- voice
  const micHint = h("span", { class: "hint" });
  const mic = h("button", { class: "mic", type: "button", title: "Dictate", "aria-label": "Dictate" }, MIC_ICON());
  setupMic(mic, micHint, () => lang, (result) => {
    text.value = (text.value.trim() ? `${text.value.trim()} ` : "") + result.text;
    if (["tr", "en"].includes(result.lang)) detected = result.lang;
    grow(); check = null; drawReview(); tidy();
  });

  // --- tidy + web check
  const review = h("div", { class: "review" });
  let tidied = null;        // {original, corrected} when the model changed something
  let busy = "";
  function drawReview() {
    const boxes = [];
    if (busy) boxes.push(h("div", { class: "note-box" }, h("span", { class: "spin" }), busy));
    if (tidied) {
      boxes.push(h("div", { class: "note-box" }, h("div", { class: "row" },
        h("span", { class: "grow" }, h("span", { class: "title" }, "Tidied. "), "You typed: ", h("del", {}, tidied.original)),
        h("button", { class: "btn quiet", type: "button", onclick: () => { text.value = tidied.original; tidied = null; grow(); check = null; drawReview(); runCheck(); } }, "Undo"))));
    }
    if (check && check.status !== "pending") {
      const ev = evidenceNode([check.evidence, check.note].filter(Boolean).join(" | "));
      const wrong = h("button", { class: "linkish", type: "button", title: "Remove this match",
        onclick: () => { check = { status: "not found", removed: true }; choice = ""; drawReview(); } }, "Wrong match");
      if (check.removed) boxes.push(h("div", { class: "note-box" }, h("span", { class: "title" }, "Match removed. "), "The card will be saved without it."));
      else if (check.status === "yes") boxes.push(h("div", { class: "note-box good" }, h("span", { class: "title" }, "✓ Verified. "), ev, " · ", wrong));
      else if (check.status === "reader-posted") boxes.push(h("div", { class: "note-box" }, h("span", { class: "title" }, "Found on reader sites. "), ev, " · ", wrong));
      else if (check.status === "not found") boxes.push(h("div", { class: "note-box" }, h("span", { class: "title" }, "Not found in the sources. "),
        "That is common, especially for Turkish books. The card can still be saved."));
      else if (check.status === "offline") boxes.push(h("div", { class: "note-box" }, h("span", { class: "title" }, "Sources not reachable. "), "The card will be checked later."));
      else if (check.status === "suggestion" && !choice) boxes.push(h("div", { class: "note-box warn" },
        h("div", { class: "title" }, "Did you mean…?"), markChanges(checkedText, check.suggestion), ev ? h("div", { class: "hint", style: "margin-bottom:8px" }, ev) : null,
        h("div", { class: "row" },
          h("button", { class: "btn primary", type: "button", onclick: () => { text.value = check.suggestion; checkedText = check.suggestion; choice = "accepted"; grow(); drawReview(); } }, "Use this"),
          h("button", { class: "btn", type: "button", onclick: () => { choice = "kept"; drawReview(); } }, "Keep mine"),
          h("span", { class: "grow" }), wrong)));
      else if (check.status === "suggestion") boxes.push(h("div", { class: "note-box good" },
        h("span", { class: "title" }, choice === "accepted" ? "✓ Using the source wording. " : "Keeping your wording. "), ev));
    }
    review.replaceChildren(...boxes);
  }

  async function runCheck() {
    const mine = ++runId;
    const body = text.value.trim();
    if (!body || cardType === "fact") return;
    const src = ov.sources.find((s) => s.kind === kind && s.slug === select.value);
    busy = "Checking the sources…"; drawReview();
    try {
      const r = await api("/api/verify", { body: { text: body, lang: detected || lang, author: src ? src.author : "", title: src && kind === "book" ? src.title : "" } });
      if (mine !== runId || text.value.trim() !== body) return;
      check = r; checkedText = body; choice = "";
    } catch (e) { if (mine === runId) check = { status: "offline" }; checkedText = body; }
    if (mine === runId) { busy = ""; drawReview(); }
  }

  async function tidy() {
    const body = text.value.trim();
    if (!body) { text.focus(); return; }
    const mine = ++runId;
    tidied = null; check = null;
    busy = state.status.llm ? "Tidying the text and choosing tags…" : "Working out the language…"; drawReview();
    try {
      const p = await api("/api/process", { body: { text: body, lang } });
      if (mine !== runId) return;
      detected = p.lang;
      if (p.changed) { tidied = { original: body, corrected: p.corrected }; text.value = p.corrected; grow(); }
      if (p.tags.length) tags.add(p.tags);
    } catch (e) { /* the web check still runs on what was typed */ }
    if (mine === runId) { busy = ""; drawReview(); await runCheck(); }
  }

  async function save() {
    const body = text.value.trim();
    if (!select.value) { toast(KIND[kind].first); addBtn.focus(); return; }
    if (!body) { text.focus(); return; }
    const fields = { text: body, type: cardType, keyword: keyword.value, note: note.value, tags: tags.get(), favorite, lang: detected || (lang === "auto" ? "" : lang) };
    fields[whereField(kind)] = where.value;
    const fresh = cardType === "quote" && check && checkedText === body;
    const evidence = fresh ? [check.evidence, check.note].filter(Boolean).join(" | ") : "";
    if (fresh && check.status === "suggestion") {
      if (choice === "accepted") Object.assign(fields, { verified: "yes", evidence });
      else if (choice === "kept") Object.assign(fields, { verified: "likely", evidence });
      else Object.assign(fields, { verified: "suggestion", suggestion: check.suggestion, evidence });
    } else if (fresh && ["yes", "reader-posted", "not found"].includes(check.status)) {
      Object.assign(fields, { verified: check.status, evidence });
    }
    try {
      const q = await api("/api/quotes", { body: { kind, slug: select.value, fields } });
      runId++;
      text.value = ""; keyword.value = ""; note.value = ""; where.value = ""; tags.set([]);
      favorite = false; star.classList.remove("on");
      check = null; tidied = null; checkedText = ""; choice = ""; detected = ""; busy = "";
      grow(); drawReview();
      const card = quoteCard(q);
      recent.prepend(card);
      recentTitle.hidden = false;
      toast(`Saved to ${q.title}.`);
      loadOverview();
      backgroundChecks(q, (u) => card.update(u));
      text.focus();
    } catch (e) { toast(e.message); }
  }

  const recentTitle = h("h2", { hidden: true }, "Just added");
  const recent = h("div", { class: "cards" });

  drawSource(); drawLang(); drawType();
  mount(h("div", { class: "capture" },
    h("div", { class: "paper" },
      h("div", { class: "top" }, seg, select, addBtn),
      text,
      h("div", { class: "row", style: "margin-top:12px" }, typeSeg, mic, langSeg, micHint, h("span", { class: "grow" }), star),
      review,
      h("div", { class: "fields" }, h("label", { class: "field" }, whereLabel, where), field("My keyword", keyword)),
      h("div", { class: "fields" }, field("Note", note)),
      h("div", { class: "fields" }, group("Tags", tags.el)),
      h("div", { class: "row end", style: "margin-top:18px" },
        tidyHint, tidyBtn,
        h("button", { class: "btn primary", type: "button", onclick: save }, "Save card"))),
    recentTitle, recent));
  grow();
  if (!ov.sources.length) toast("Start by adding a book, a person or a topic.");
  else text.focus();
}

function setupMic(button, hint, getLang, onText) {
  if (!state.status.voice) { button.hidden = true; return; }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    button.disabled = true;
    hint.textContent = "The microphone needs a secure (https) address on this device.";
    return;
  }
  let recorder = null, chunks = [], startedAt = 0, timer = 0, pressing = false;
  const stop = () => { if (recorder && recorder.state === "recording") recorder.stop(); };
  const start = async () => {
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch (e) { hint.textContent = "Microphone access was not allowed."; return; }
    const type = ["audio/webm;codecs=opus", "audio/mp4", "audio/webm"].find((t) => MediaRecorder.isTypeSupported(t)) || "";
    recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    chunks = [];
    recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    recorder.onstop = async () => {
      clearInterval(timer);
      stream.getTracks().forEach((t) => t.stop());
      button.classList.remove("rec");
      const blob = new Blob(chunks, { type: recorder.mimeType });
      recorder = null;
      if (Date.now() - startedAt < 600 || blob.size < 1000) { hint.textContent = "Too short. Hold the button while you speak, or click to start and stop."; return; }
      button.classList.add("busy"); button.disabled = true;
      hint.replaceChildren(h("span", { class: "spin" }), "Writing down what you said…");
      const form = new FormData();
      form.append("audio", blob, `speech.${blob.type.includes("mp4") ? "mp4" : "webm"}`);
      form.append("lang", getLang());
      try {
        const r = await api("/api/transcribe", { form });
        hint.textContent = "";
        if (r.text) onText(r); else hint.textContent = "Nothing was heard.";
      } catch (e) { hint.textContent = e.message; }
      button.classList.remove("busy"); button.disabled = false;
    };
    recorder.start();
    startedAt = Date.now();
    button.classList.add("rec");
    timer = setInterval(() => { hint.textContent = `Listening… ${Math.round((Date.now() - startedAt) / 1000)}s`; }, 250);
    if (!pressing && Date.now() - pressStart > 500) stop();   // released while the permission prompt was open
  };
  let pressStart = 0;
  // Hold to talk, or click once to start and once more to stop.
  button.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    if (recorder) { stop(); return; }
    pressing = true; pressStart = Date.now(); start();
  });
  const release = () => {
    if (!pressing) return;
    pressing = false;
    if (recorder && Date.now() - pressStart > 500) stop();
  };
  button.addEventListener("pointerup", release);
  button.addEventListener("pointercancel", release);
  button.addEventListener("keydown", (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); if (recorder) stop(); else { pressing = false; pressStart = Date.now(); start(); } } });
}

// ------------------------------------------------------------ library views

function tile(s) {
  const pic = s.meta.cover || s.meta.image;
  const sub = s.kind === "book" ? [s.author, s.meta.year].filter(Boolean).join(" · ") : (s.meta.description || "");
  // (people and topics show their one-line description)
  return h("a", { class: `tile ${s.kind}`, href: sourceHref(s.kind, s.slug) },
    pic ? h("img", { src: pic, alt: "", loading: "lazy" }) : h("span", { class: "ph" }, s.title.slice(0, 1).toUpperCase()),
    h("div", {}, h("div", { class: "t" }, s.title), h("div", { class: "s" }, sub), h("div", { class: "n" }, plural(s.count, "card"))));
}

async function viewLibrary() {
  const ov = await loadOverview();
  const books = ov.sources.filter((s) => s.kind === "book");
  const people = ov.sources.filter((s) => s.kind === "person");
  const topics = ov.sources.filter((s) => s.kind === "topic");
  const add = (kind) => h("button", { class: "btn", type: "button", onclick: async () => { const made = await sourceDialog(kind); if (made) location.hash = sourceHref(kind, made.slug); } },
    KIND[kind].add);
  mount(
    h("div", { class: "row" }, h("div", { class: "grow" }, h("h1", {}, "Library"),
      h("p", { class: "lede" }, `${plural(ov.total, "card")} (${plural(ov.facts, "fact")}) in ${plural(books.length, "book")}, ${plural(people.length, "person").replace("persons", "people")} and ${plural(topics.length, "topic")}. Each has its own file.`)),
      add("book"), add("person"), add("topic")),
    h("h2", {}, "Books"), books.length ? h("div", { class: "shelf" }, books.map(tile)) : h("p", { class: "empty" }, "No books yet."),
    h("h2", {}, "People"), people.length ? h("div", { class: "shelf" }, people.map(tile)) : h("p", { class: "empty" }, "No people yet. Use these for quotes that are not from a book."),
    h("h2", {}, "Topics"), topics.length ? h("div", { class: "shelf" }, topics.map(tile)) : h("p", { class: "empty" }, "No topics yet. Use these for facts that are not from one book or person."),
    (state.status.phone || []).length ? [h("h2", {}, "On your phone"),
      h("p", { class: "hint" }, "While Quote Vault is open on the Mac, open this address on a phone that is on the same Wi-Fi: ",
        h("strong", {}, state.status.phone[0]),
        state.status.phone[0].startsWith("https") ? "" : ". Typing works; the phone's microphone needs the one-time setup in scripts/setup-phone-https.sh.")] : null);
}

async function viewSource(parts) {
  const [kind, slug] = [parts[0], decodeURIComponent(parts[1] || "")];
  await loadOverview();
  let src;
  try { src = await api(`/api/sources/${kind}/${enc(slug)}`); }
  catch (e) { mount(h("p", { class: "empty" }, e.message)); return; }
  const m = src.meta;
  const facts = kind === "book"
    ? [m.author, m.year, m.publisher, m.translator && `translated by ${m.translator}`, m.original_title && `original title: ${m.original_title}`, m.pages && `${m.pages} pages`, m.isbn && `ISBN ${m.isbn}`]
    : kind === "person" ? [m.description, (m.born || m.died) && `${m.born ?? "?"}–${m.died ?? ""}`] : [m.description];
  const pic = m.cover || m.image;
  const others = kind === "person" ? state.overview.sources.filter((s) => s.kind === "book" && s.author.toLowerCase() === src.title.toLowerCase()) : [];
  mount(
    h("div", { class: "source-head" },
      pic ? h("img", { src: pic, alt: "" }) : null,
      h("div", { class: "grow" }, h("h1", {}, src.title), h("p", { class: "facts" }, facts.filter(Boolean).join(" · ")),
        h("div", { class: "row" },
          h("a", { class: "btn", href: `#/shuffle?from=${enc(`${kind}:${src.slug}`)}` }, "Shuffle these"),
          h("button", { class: "btn", type: "button", onclick: async () => { const saved = await sourceDialog(kind, src); if (saved) { if (saved.slug !== src.slug) location.hash = sourceHref(kind, saved.slug); else viewSource(parts); } } }, "Edit details"),
          h("button", { class: "btn danger", type: "button", onclick: async () => {
            const ok = await confirmDialog(`Delete ${src.title}?`, src.count ? `This deletes the file and its ${plural(src.count, "card")}. This cannot be undone.` : "This deletes the empty file.", "Delete");
            if (ok) { await api(`/api/sources/${kind}/${enc(src.slug)}`, { method: "DELETE" }); location.hash = "#/library"; }
          } }, "Delete"),
          h("span", { class: "hint" }, `File: ${KIND[kind].folder}/${src.slug}.md`)))),
    cardGrid(src.quotes, "No cards here yet."),
    others.length ? [h("h2", {}, `Books by ${src.title}`), h("div", { class: "shelf" }, others.map(tile))] : null);
}

async function viewQuotes(_parts, params) {
  await loadOverview();
  const query = new URLSearchParams();
  const bits = [];
  for (const key of ["tag", "name", "q", "favorite", "verified", "type"]) if (params.get(key)) query.set(key, params.get(key));
  const only = params.get("type");
  if (params.get("tag")) bits.push(`tagged “${params.get("tag")}”`);
  if (params.get("name")) bits.push(`by ${params.get("name")}`);
  if (params.get("q")) bits.push(`matching “${params.get("q")}”`);
  if (params.get("favorite")) bits.push("favorites");
  const quotes = await api(`/api/quotes?${query}`);
  mount(
    h("div", { class: "row" }, h("div", { class: "grow" }, h("h1", {}, `${only === "fact" ? "Facts" : only === "quote" ? "Quotes" : "Cards"} ${bits.join(", ")}`), h("p", { class: "lede" }, plural(quotes.length, "card"))),
      only && !params.get("tag") && !params.get("name") ? h("a", { class: "btn", href: `#/shuffle?type=${only}` }, "Shuffle these") : null,
      params.get("tag") ? h("a", { class: "btn", href: `#/shuffle?from=${enc(`tag:${params.get("tag")}`)}` }, "Shuffle these") : null,
      params.get("name") ? h("a", { class: "btn", href: `#/shuffle?from=${enc(`name:${params.get("name")}`)}` }, "Shuffle these") : null),
    cardGrid(quotes, "Nothing matches."));
}

async function viewTags() {
  const ov = await loadOverview();
  const fav = await api("/api/quotes?favorite=true");
  mount(
    h("h1", {}, "Tags"), h("p", { class: "lede" }, "What your cards are about. Tags are suggested automatically and are always in English."),
    ov.tags.length ? h("div", { class: "cloud" }, ov.tags.map((t) => h("a", { class: "chip", href: `#/quotes?tag=${enc(t.tag)}` }, t.tag, h("small", {}, t.count))))
      : h("p", { class: "empty" }, "No tags yet."),
    h("h2", {}, "Authors and people"),
    ov.names.length ? h("div", { class: "cloud" }, ov.names.map((n) => h("a", { class: "chip", href: `#/quotes?name=${enc(n.name)}` }, n.name, h("small", {}, n.count))))
      : h("p", { class: "empty" }, "Nobody yet."),
    h("h2", {}, "Collections"),
    h("div", { class: "cloud" },
      h("a", { class: "chip", href: "#/quotes?favorite=true" }, "★ Favorites", h("small", {}, fav.length)),
      h("a", { class: "chip", href: "#/quotes?type=fact" }, "Facts", h("small", {}, ov.facts)),
      h("a", { class: "chip", href: "#/quotes?type=quote" }, "Quotes", h("small", {}, ov.total - ov.facts))));
}

// ------------------------------------------------------------- shuffle view

let shuffleCleanup = null;

async function viewShuffle(_parts, params) {
  const ov = await loadOverview();
  let from = params.get("from") || store.get("qv-shuffle-from", "all");
  let seconds = store.get("qv-shuffle-seconds", 12);
  let only = ["quote", "fact"].includes(params.get("type")) ? params.get("type") : store.get("qv-shuffle-type", "");
  if (params.get("type") && !params.get("from")) from = "all";
  let deck = [], index = 0, playing = false, timer = 0;

  const onlySeg = h("div", { class: "seg", role: "group", "aria-label": "Quotes or facts" });
  const drawOnly = () => onlySeg.replaceChildren(...[["", "All"], ["quote", "Quotes"], ["fact", "Facts"]].map(([v, t]) =>
    h("button", { type: "button", "aria-pressed": String(v === only), onclick: () => { only = v; store.set("qv-shuffle-type", only); drawOnly(); load(); } }, t)));
  drawOnly();

  const select = h("select", { class: "plain", "aria-label": "Which cards" },
    h("option", { value: "all" }, "All cards"), h("option", { value: "fav" }, "★ Favorites"),
    h("optgroup", { label: "Books" }, ov.sources.filter((s) => s.kind === "book").map((s) => h("option", { value: `book:${s.slug}` }, s.title))),
    h("optgroup", { label: "Authors and people" }, ov.names.map((n) => h("option", { value: `name:${n.name}` }, n.name))),
    h("optgroup", { label: "Topics" }, ov.sources.filter((s) => s.kind === "topic").map((s) => h("option", { value: `topic:${s.slug}` }, s.title))),
    h("optgroup", { label: "Tags" }, ov.tags.map((t) => h("option", { value: `tag:${t.tag}` }, t.tag))));
  select.value = from;
  if (select.value !== from) { from = "all"; select.value = "all"; }
  select.addEventListener("change", () => { from = select.value; store.set("qv-shuffle-from", from); load(); });

  const stageCard = h("div", {});
  const counter = h("div", { class: "counter" });
  const bar = h("i");
  const progress = h("div", { class: "progress" }, bar);
  const playBtn = h("button", { class: "btn", type: "button", onclick: () => setPlaying(!playing) });
  const speed = h("select", { class: "plain", "aria-label": "Seconds per card", onchange: () => { seconds = Number(speed.value); store.set("qv-shuffle-seconds", seconds); if (playing) schedule(); } },
    [6, 12, 20, 30, 60].map((s) => h("option", { value: s, selected: s === seconds }, `${s} s`)));
  let current = null;

  function show() {
    if (!deck.length) { stageCard.replaceChildren(h("p", { class: "empty" }, only === "fact" ? "No facts here yet." : only === "quote" ? "No quotes here yet." : "No cards here yet.")); counter.textContent = ""; current = null; return; }
    current = quoteCard(deck[index], { big: true, onChange: (q) => { deck[index] = q; }, onRemove: () => { deck.splice(index, 1); index = Math.min(index, deck.length - 1); show(); } });
    stageCard.replaceChildren(current);
    counter.textContent = `${index + 1} of ${deck.length}`;
    if (playing) schedule();
  }
  function step(by) {
    if (!deck.length) return;
    index += by;
    if (index >= deck.length) { mix(); index = 0; }
    if (index < 0) index = deck.length - 1;
    show();
  }
  function mix() { for (let i = deck.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [deck[i], deck[j]] = [deck[j], deck[i]]; } }
  function schedule() {
    clearTimeout(timer);
    progress.classList.remove("run"); bar.style.transitionDuration = "0s";
    void bar.offsetWidth;
    bar.style.transitionDuration = `${seconds}s`; progress.classList.add("run");
    timer = setTimeout(() => step(1), seconds * 1000);
  }
  function setPlaying(on) {
    playing = on && deck.length > 1;
    playBtn.textContent = playing ? "❚❚ Pause" : "▶ Play";
    clearTimeout(timer);
    progress.classList.remove("run"); bar.style.transitionDuration = "0s";
    progress.style.visibility = playing ? "visible" : "hidden";
    if (playing) schedule();
  }
  async function load() {
    const q = new URLSearchParams();
    const [scope, ...rest] = from.split(":");
    const value = rest.join(":");
    if (scope === "fav") q.set("favorite", "true");
    else if (KINDS.includes(scope)) { q.set("kind", scope); q.set("slug", value); }
    else if (scope === "name") q.set("name", value);
    else if (scope === "tag") q.set("tag", value);
    if (only) q.set("type", only);          // quotes only, or facts only
    deck = await api(`/api/quotes?${q}`);
    mix(); index = 0;
    setPlaying(playing);
    show();
  }

  const onKey = (e) => {
    if (e.target.closest("input, textarea, select, dialog") || e.metaKey || e.ctrlKey) return;
    if (e.key === "ArrowRight" || e.key === " ") { e.preventDefault(); step(1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); step(-1); }
    else if (e.key === "f" || e.key === "ArrowUp" || e.key === "ArrowDown") { e.preventDefault(); current?.flip(); }
    else if (e.key === "p") setPlaying(!playing);
    else if (e.key === "Escape") document.body.classList.remove("focus");
  };
  let touchX = null;
  const onTouchStart = (e) => { touchX = e.touches[0].clientX; };
  const onTouchEnd = (e) => {
    if (touchX == null) return;
    const dx = e.changedTouches[0].clientX - touchX; touchX = null;
    if (Math.abs(dx) > 60) step(dx < 0 ? 1 : -1);
  };
  document.addEventListener("keydown", onKey);
  stageCard.addEventListener("touchstart", onTouchStart, { passive: true });
  stageCard.addEventListener("touchend", onTouchEnd);
  shuffleCleanup = () => { clearTimeout(timer); document.removeEventListener("keydown", onKey); document.body.classList.remove("focus"); };

  mount(
    h("div", { class: "shuffle-bar" }, onlySeg, select, playBtn, speed,
      h("button", { class: "btn", type: "button", title: "Hide everything but the card (Esc to leave)", onclick: () => {
        const on = document.body.classList.toggle("focus");
        if (on) document.documentElement.requestFullscreen?.().catch(() => {}); else if (document.fullscreenElement) document.exitFullscreen();
      } }, "Full screen")),
    h("div", { class: "stage" },
      h("button", { class: "nav-arrow", type: "button", "aria-label": "Previous card", onclick: () => step(-1) }, "‹"),
      stageCard,
      h("button", { class: "nav-arrow", type: "button", "aria-label": "Next card", onclick: () => step(1) }, "›")),
    progress, counter,
    h("p", { class: "hint", style: "text-align:center;margin-top:14px" }, "Click a card to turn it over. Arrow keys or swipe to move, P to play."));
  setPlaying(false);
  await load();
}

// ------------------------------------------------------------------ routing

const routes = { new: viewCapture, library: viewLibrary, source: viewSource, quotes: viewQuotes, tags: viewTags, shuffle: viewShuffle };

async function route() {
  shuffleCleanup?.(); shuffleCleanup = null;
  const [path, queryString] = (location.hash.replace(/^#\/?/, "") || "new").split("?");
  const [name, ...parts] = path.split("/");
  const handler = routes[name] || viewCapture;
  for (const a of document.querySelectorAll("[data-nav]")) {
    const on = a.dataset.nav === name || (a.dataset.nav === "library" && name === "source") || (a.dataset.nav === "tags" && name === "quotes");
    a.classList.toggle("on", on);
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  try { await handler(parts, new URLSearchParams(queryString || "")); }
  catch (e) { mount(h("p", { class: "empty" }, e.message)); }
  window.scrollTo(0, 0);
}

document.getElementById("search").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = new FormData(e.currentTarget).get("q").trim();
  if (q) location.hash = `#/quotes?q=${enc(q)}`;
});

document.getElementById("theme").addEventListener("click", () => {
  const root = document.documentElement;
  const dark = root.dataset.theme === "dark";
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("qv-theme", root.dataset.theme); } catch (e) { /* private mode */ }
});

document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement) document.body.classList.remove("focus"); });
window.addEventListener("hashchange", route);

(async () => {
  try { state.status = await api("/api/status"); } catch (e) { /* shown by the first view */ }
  await route();
  // Cards saved while offline get their web check now.
  api("/api/recheck", { body: { limit: 8 } }).catch(() => {});
})();
