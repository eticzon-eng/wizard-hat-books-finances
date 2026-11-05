const state = {
  expenses: [],
  expenseChoices: { vendors: [], categories: [], books: [] },
  expenseUi: { pendingFiles: [], pendingPreviewUrls: [], currentAttachments: [] },
  royaltySource: "kdp",
  royalties: null,
  inventory: null,
};

function $(id) {
  return document.getElementById(id);
}

function today() {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

function thisMonth() {
  return today().slice(0, 7);
}

function setMessage(text, isError = false) {
  const el = $("message");
  el.textContent = text || "";
  el.classList.toggle("error", Boolean(isError));
}

async function api(path, options = {}) {
  const opts = { ...options };
  const headers = { ...(opts.headers || {}) };
  if (opts.body && !(opts.body instanceof FormData) && typeof opts.body !== "string") {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, { ...opts, headers });
  if (!res.ok) {
    let message = res.statusText;
    const text = await res.text();
    try {
      const data = JSON.parse(text);
      message = typeof data.detail === "string" ? data.detail : text;
    } catch {
      if (text) message = text;
    }
    throw new Error(message);
  }
  if (res.status === 204) return null;
  return res.json();
}

function money(cents, currency = "USD") {
  if (cents === null || cents === undefined) return "—";
  const amount = (Number(cents) / 100).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${amount} ${currency || ""}`.trim();
}

function dollarsToCents(value) {
  const text = String(value ?? "").trim().replace(/[$,]/g, "");
  if (!text) return null;
  const wrapped = /^\(.*\)$/.test(text);
  const number = Number(wrapped ? text.slice(1, -1) : text);
  if (!Number.isFinite(number)) throw new Error("Enter an amount like 12.50");
  const cents = Math.round(Math.abs(number) * 100);
  return number < 0 || wrapped ? -cents : cents;
}

function optionalInt(value) {
  const text = String(value ?? "").trim();
  if (!text) return null;
  const number = Number(text);
  if (!Number.isInteger(number)) throw new Error("Units must be a whole number.");
  return number;
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function setActiveView(name) {
  document.querySelectorAll(".tabs .tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.view === name);
  });
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("active", view.id === `view-${name}`);
  });
}

function sourceLabel(source) {
  return source === "ingramspark" ? "IngramSpark" : "Amazon KDP";
}

function renderSimpleTable(target, columns, rows, emptyText) {
  clear(target);
  if (!rows.length) {
    target.appendChild(el("p", emptyText, "muted"));
    return;
  }
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  columns.forEach((column) => headRow.appendChild(el("th", column.label, column.num ? "num" : "")));
  thead.appendChild(headRow);
  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((column) => {
      tr.appendChild(el("td", column.value(row), column.num ? "num" : ""));
    });
    tbody.appendChild(tr);
  });
  table.appendChild(thead);
  table.appendChild(tbody);
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  wrap.appendChild(table);
  target.appendChild(wrap);
}

function applyRoyaltySource() {
  const source = state.royaltySource;
  const kdp = source === "kdp";
  document.querySelectorAll(".source-switch .tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.source === source);
  });
  document.querySelectorAll(".kdp-only").forEach((node) => node.classList.toggle("hidden", !kdp));
  $("royaltyFormTitle").textContent = kdp ? "Add KDP royalty" : "Add IngramSpark royalty";
  $("productIdLabel").textContent = kdp ? "ASIN / ISBN" : "ISBN";
  $("marketLabel").textContent = kdp ? "Marketplace" : "Country";
  $("amountLabel").textContent = kdp ? "Royalty" : "Compensation";
  $("refundLabel").textContent = kdp ? "Units refunded" : "Returns";
  $("importHelp").textContent = kdp
    ? "Royalties Estimator CSV or xlsx (the Combined Sales sheet: Royalty Date, Title, ASIN/ISBN, Net Units Sold, Royalty) or a Prior Month’s Royalties CSV (Total Earnings)."
    : "Compensation CSV (Title, ISBN, Quantity Shipped, Net Compensation) or sales by region (Title, ISBN, Format, Country, Units Sold). UTF-16 files and Excel ISBN formulas are fine.";
  renderRoyaltyRows();
}

async function loadRoyalties() {
  state.royalties = await api("/api/royalties");
  renderRoyaltyTotals();
  renderRoyaltyRows();
}

function amountCell(row) {
  const moneyText = money(row.amount_cents, row.currency);
  if (row.missing_amount) return `${moneyText} · ${row.missing_amount} without an amount`;
  return moneyText;
}

function renderRoyaltyTotals() {
  const totals = state.royalties.totals;
  renderSimpleTable(
    $("totalsBySource"),
    [
      { label: "Source", value: (row) => sourceLabel(row.source) },
      { label: "Net units", value: (row) => row.net_units ?? "—", num: true },
      { label: "Royalty", value: (row) => amountCell(row), num: true },
    ],
    totals.by_source,
    "No royalty totals yet.",
  );
  renderSimpleTable(
    $("totalsByTitle"),
    [
      { label: "Source", value: (row) => sourceLabel(row.source) },
      { label: "Title", value: (row) => row.title },
      { label: "Net units", value: (row) => row.net_units ?? "—", num: true },
      { label: "Royalty", value: (row) => money(row.amount_cents, row.currency), num: true },
    ],
    totals.by_title,
    "No titles yet.",
  );
  renderSimpleTable(
    $("totalsByPeriod"),
    [
      { label: "Source", value: (row) => sourceLabel(row.source) },
      { label: "Period", value: (row) => row.period },
      { label: "Net units", value: (row) => row.net_units ?? "—", num: true },
      { label: "Royalty", value: (row) => money(row.amount_cents, row.currency), num: true },
    ],
    totals.by_period,
    "No periods yet.",
  );
}

function renderRoyaltyRows() {
  if (!state.royalties) return;
  const kdp = state.royaltySource === "kdp";
  const head = $("royaltyHead");
  clear(head);
  const labels = kdp
    ? ["Period", "Date", "Title", "ASIN / ISBN", "Marketplace", "Format", "Net units", "KENP", "Royalty", ""]
    : ["Period", "Title", "ISBN", "Country", "Format", "Net units", "Compensation", ""];
  labels.forEach((label) => head.appendChild(el("th", label, label.includes("unit") || label === "Royalty" || label === "Compensation" || label === "KENP" ? "num" : "")));
  const entries = state.royalties.entries.filter((entry) => entry.source === state.royaltySource);
  const body = $("royaltyRows");
  clear(body);
  $("royaltyEmpty").classList.toggle("hidden", entries.length > 0);
  entries.forEach((entry) => {
    const tr = document.createElement("tr");
    const cells = kdp
      ? [
          entry.period,
          entry.royalty_date || "—",
          entry.title,
          entry.product_id || "—",
          entry.marketplace || "—",
          entry.format || "—",
        ]
      : [entry.period, entry.title, entry.product_id || "—", entry.marketplace || "—", entry.format || "—"];
    cells.forEach((value) => tr.appendChild(el("td", value)));
    tr.appendChild(el("td", entry.net_units ?? "—", "num"));
    if (kdp) tr.appendChild(el("td", entry.kenp ?? "—", "num"));
    tr.appendChild(el("td", money(entry.amount_cents, entry.currency), "num"));
    const actions = document.createElement("td");
    const remove = el("button", "Delete", "btn small danger");
    remove.type = "button";
    remove.addEventListener("click", async () => {
      if (!confirm(`Delete this ${sourceLabel(entry.source)} row for ${entry.title}?`)) return;
      await api(`/api/royalties/${entry.id}`, { method: "DELETE" });
      setMessage("Royalty row deleted.");
      await loadRoyalties();
    });
    actions.appendChild(remove);
    tr.appendChild(actions);
    body.appendChild(tr);
  });
}

function fillSelect(select, locations, preferredName) {
  const current = select.value;
  clear(select);
  locations.forEach((location) => {
    const option = document.createElement("option");
    option.value = String(location.id);
    option.textContent = location.name;
    option.dataset.name = location.name;
    select.appendChild(option);
  });
  const preferred = locations.find((location) => location.name === preferredName);
  if (current && locations.some((location) => String(location.id) === current)) {
    select.value = current;
  } else if (preferred) {
    select.value = String(preferred.id);
  }
}

function fillTitles(select, titles) {
  const current = select.value;
  clear(select);
  titles.forEach((title) => {
    const option = document.createElement("option");
    option.value = String(title.id);
    option.textContent = title.name;
    select.appendChild(option);
  });
  if (current && titles.some((title) => String(title.id) === current)) select.value = current;
}

async function loadInventory() {
  state.inventory = await api("/api/inventory");
  renderInventory();
}

function renderInventory() {
  const { titles, locations, on_hand: onHand, events, sales } = state.inventory;
  ["receiveTitle", "moveTitle", "saleTitle"].forEach((id) => fillTitles($(id), titles));
  fillSelect($("receiveLocation"), locations, "Home");
  fillSelect($("moveFrom"), locations, "Home");
  fillSelect($("moveTo"), locations, "InkFish Books");
  fillSelect($("saleFrom"), locations, "Home");
  fillSelect($("saleChannel"), locations, "TikTok Shop");

  const head = $("stockHead");
  clear(head);
  head.appendChild(el("th", "Title"));
  locations.forEach((location) => head.appendChild(el("th", location.name, "num")));
  const body = $("stockRows");
  clear(body);
  $("stockEmpty").classList.toggle("hidden", titles.length > 0);
  titles.forEach((title) => {
    const tr = document.createElement("tr");
    tr.appendChild(el("td", title.name));
    locations.forEach((location) => {
      const cell = onHand.find((row) => row.title_id === title.id && row.location_id === location.id);
      tr.appendChild(el("td", cell ? cell.quantity : 0, "num"));
    });
    body.appendChild(tr);
  });

  renderSimpleTable(
    $("salesTotals"),
    [
      { label: "Sold through", value: (row) => row.channel },
      { label: "Copies", value: (row) => row.quantity, num: true },
      {
        label: "Amount",
        value: (row) => (row.missing_price ? `${money(row.amount_cents, row.currency)} (some prices blank)` : money(row.amount_cents, row.currency)),
        num: true,
      },
    ],
    sales,
    "No sales yet.",
  );

  const eventBody = $("eventRows");
  clear(eventBody);
  events.forEach((event) => {
    const tr = document.createElement("tr");
    tr.appendChild(el("td", event.happened_on));
    tr.appendChild(el("td", event.title));
    tr.appendChild(el("td", describeEvent(event)));
    tr.appendChild(el("td", event.quantity, "num"));
    const actions = document.createElement("td");
    const remove = el("button", "Delete", "btn small danger");
    remove.type = "button";
    remove.addEventListener("click", async () => {
      if (!confirm("Delete this inventory activity? Later moves still have to leave every location at zero or more.")) return;
      try {
        await api(`/api/inventory/events/${event.id}`, { method: "DELETE" });
        setMessage("Activity deleted.");
        await loadInventory();
      } catch (error) {
        setMessage(error.message, true);
      }
    });
    actions.appendChild(remove);
    tr.appendChild(actions);
    eventBody.appendChild(tr);
  });
}

function describeEvent(event) {
  if (event.kind === "receive") return `Received at ${event.to_location}`;
  if (event.kind === "move") return `Moved from ${event.from_location} to ${event.to_location}`;
  const price = event.unit_price_cents == null ? "" : ` at ${money(event.unit_price_cents, event.currency)} each`;
  if (event.from_location === event.channel) return `Sold from ${event.channel}${price}`;
  return `Sold through ${event.channel}; copies left ${event.from_location}${price}`;
}

function requireTitleId(select) {
  if (!select.value) throw new Error("Add a title first.");
  return Number(select.value);
}

document.querySelectorAll(".tabs .tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    setActiveView(tab.dataset.view);
    setMessage("");
  });
});

document.querySelectorAll(".source-switch .tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    state.royaltySource = tab.dataset.source;
    applyRoyaltySource();
  });
});

$("royaltyForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const net = optionalInt($("royaltyNet").value);
    const sold = optionalInt($("royaltySold").value);
    const refunded = optionalInt($("royaltyRefunded").value);
    const amount = dollarsToCents($("royaltyAmount").value);
    const kenp = state.royaltySource === "kdp" ? optionalInt($("royaltyKenp").value) : null;
    const payload = {
      source: state.royaltySource,
      period: $("royaltyPeriod").value,
      royalty_date: $("royaltyDate").value || null,
      title: $("royaltyTitle").value.trim(),
      author: $("royaltyAuthor").value.trim(),
      product_id: $("royaltyProductId").value.trim(),
      marketplace: $("royaltyMarket").value.trim(),
      format: $("royaltyFormat").value.trim(),
      royalty_type: state.royaltySource === "kdp" ? $("royaltyType").value.trim() : "",
      transaction_type: state.royaltySource === "kdp" ? $("royaltyTxn").value.trim() : "",
      units_sold: sold,
      units_refunded: refunded,
      net_units: net === null && sold !== null ? sold - (refunded || 0) : net,
      kenp,
      amount_cents: amount,
      currency: $("royaltyCurrency").value.trim().toUpperCase() || "USD",
      notes: $("royaltyNotes").value.trim(),
    };
    await api("/api/royalties", { method: "POST", body: payload });
    $("royaltyForm").reset();
    $("royaltyPeriod").value = thisMonth();
    $("royaltyCurrency").value = "USD";
    setMessage(`${sourceLabel(state.royaltySource)} royalty saved.`);
    await loadRoyalties();
  } catch (error) {
    setMessage(error.message, true);
  }
});

$("importForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = $("importFile").files[0];
  if (!file) {
    setMessage("Choose a CSV or xlsx file.", true);
    return;
  }
  const body = new FormData();
  body.append("source", state.royaltySource);
  body.append("period", $("importPeriod").value);
  body.append("file", file);
  try {
    const result = await api("/api/royalties/import", { method: "POST", body });
    const skipped = result.skipped ? ` ${result.skipped} duplicate row${result.skipped === 1 ? "" : "s"} skipped.` : "";
    setMessage(`Imported ${result.imported} ${sourceLabel(result.source)} row${result.imported === 1 ? "" : "s"}.${skipped}`);
    $("importForm").reset();
    $("importPeriod").value = thisMonth();
    await loadRoyalties();
  } catch (error) {
    setMessage(error.message, true);
  }
});

$("titleForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/titles", { method: "POST", body: { name: $("titleName").value } });
    $("titleName").value = "";
    setMessage("Title added.");
    await loadInventory();
  } catch (error) {
    setMessage(error.message, true);
  }
});

$("receiveForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/inventory/receive", {
      method: "POST",
      body: {
        title_id: requireTitleId($("receiveTitle")),
        location_id: Number($("receiveLocation").value),
        quantity: Number($("receiveQty").value),
        happened_on: $("receiveDate").value,
        notes: $("receiveNotes").value.trim(),
      },
    });
    $("receiveNotes").value = "";
    setMessage("Copies received.");
    await loadInventory();
  } catch (error) {
    setMessage(error.message, true);
  }
});

$("moveForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/inventory/move", {
      method: "POST",
      body: {
        title_id: requireTitleId($("moveTitle")),
        from_location_id: Number($("moveFrom").value),
        to_location_id: Number($("moveTo").value),
        quantity: Number($("moveQty").value),
        happened_on: $("moveDate").value,
        notes: $("moveNotes").value.trim(),
      },
    });
    $("moveNotes").value = "";
    setMessage("Copies moved.");
    await loadInventory();
  } catch (error) {
    setMessage(error.message, true);
  }
});

$("saleForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const price = dollarsToCents($("salePrice").value);
    await api("/api/inventory/sale", {
      method: "POST",
      body: {
        title_id: requireTitleId($("saleTitle")),
        from_location_id: Number($("saleFrom").value),
        channel_location_id: Number($("saleChannel").value),
        quantity: Number($("saleQty").value),
        happened_on: $("saleDate").value,
        unit_price_cents: price,
        notes: $("saleNotes").value.trim(),
      },
    });
    $("saleNotes").value = "";
    $("salePrice").value = "";
    setMessage("Sale recorded.");
    await loadInventory();
  } catch (error) {
    setMessage(error.message, true);
  }
});

function boot() {
  $("royaltyPeriod").value = thisMonth();
  $("importPeriod").value = thisMonth();
  ["receiveDate", "moveDate", "saleDate"].forEach((id) => {
    $(id).value = today();
  });
  applyRoyaltySource();
  Promise.all([loadRoyalties(), loadInventory()]).catch((error) => {
    setMessage(error.message, true);
  });
}

boot();
