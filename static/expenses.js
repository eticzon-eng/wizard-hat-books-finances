let expenseYearTouched = false;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function moneyFromCents(cents) {
  const number = Number(cents) || 0;
  const sign = number < 0 ? "-" : "";
  const abs = Math.abs(Math.round(number));
  return `${sign}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, "0")}`;
}

function expenseWriteOffCents(row) {
  if (row.write_off_cents != null && row.write_off_cents !== "") return Number(row.write_off_cents);
  const percent = Number(row.write_off_percent);
  const shown = Number.isFinite(percent) ? percent : 100;
  return Math.round(((Number(row.amount_cents) || 0) * shown) / 100);
}

function writeOffPercentValue() {
  const amount = Math.round(Number($("expenseWriteOffPercent")?.value));
  if (!Number.isFinite(amount)) return 100;
  return Math.min(100, Math.max(0, amount));
}

function updateWriteOffHint() {
  const hint = $("expenseWriteOffHint");
  if (!hint) return;
  const percent = writeOffPercentValue();
  let cents = 0;
  try {
    cents = dollarsToCents($("expenseAmount")?.value) || 0;
  } catch {
    cents = 0;
  }
  const deducted = Math.round((cents * percent) / 100);
  hint.textContent = `Deductible $${moneyFromCents(deducted)} of $${moneyFromCents(cents)}`;
}

function selectedChoiceId(selectId) {
  const option = $(selectId)?.selectedOptions?.[0];
  return option?.dataset?.id || "";
}

function fillExpenseYearSelect(expenses) {
  const el = $("expenseYearFilter");
  if (!el) return;
  const thisYear = String(new Date().getFullYear());
  const years = new Set(expenses.map((row) => String(row.spent_on || "").slice(0, 4)).filter(Boolean));
  years.add(thisYear);
  const current = el.value;
  const list = [...years].sort((a, b) => b.localeCompare(a));
  el.innerHTML = `<option value="all">All years</option>${list
    .map((year) => `<option value="${escapeHtml(year)}">${escapeHtml(year)}</option>`)
    .join("")}`;
  if (!expenseYearTouched) el.value = years.has(thisYear) ? thisYear : "all";
  else if ([...el.options].some((option) => option.value === current)) el.value = current;
  else el.value = thisYear;
}

function fillExpenseFilters() {
  const books = $("expenseBookFilter");
  const vendors = $("expenseVendorFilter");
  const categories = $("expenseCategoryFilter");
  const bookValue = books?.value || "";
  const vendorValue = vendors?.value || "";
  const categoryValue = categories?.value || "";
  const bookNames = state.expenseChoices.books.map((book) => book.name);
  if (books) {
    books.innerHTML =
      `<option value="">All books</option><option value="general">General</option>` +
      bookNames.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("");
    if ([...books.options].some((option) => option.value === bookValue)) books.value = bookValue;
  }
  if (vendors) {
    vendors.innerHTML =
      `<option value="">All vendors</option>` +
      state.expenseChoices.vendors
        .map((vendor) => `<option value="${escapeHtml(vendor.name)}">${escapeHtml(vendor.name)}</option>`)
        .join("");
    if ([...vendors.options].some((option) => option.value === vendorValue)) vendors.value = vendorValue;
  }
  if (categories) {
    categories.innerHTML =
      `<option value="">All categories</option>` +
      state.expenseChoices.categories
        .map((category) => `<option value="${escapeHtml(category.label)}">${escapeHtml(category.label)}</option>`)
        .join("");
    if ([...categories.options].some((option) => option.value === categoryValue)) categories.value = categoryValue;
  }
}

function fillExpenseFormSelects({ vendor, category, book } = {}) {
  const vendorEl = $("expenseVendor");
  const categoryEl = $("expenseCategory");
  const bookEl = $("expenseBook");
  if (vendorEl) {
    const current = vendor ?? vendorEl.value;
    vendorEl.innerHTML = state.expenseChoices.vendors
      .map(
        (item) =>
          `<option value="${escapeHtml(item.name)}" data-id="${escapeHtml(String(item.id))}">${escapeHtml(item.name)}</option>`,
      )
      .join("");
    if (current) vendorEl.value = current;
  }
  if (categoryEl) {
    const current = category ?? categoryEl.value;
    categoryEl.innerHTML = state.expenseChoices.categories
      .map(
        (item) =>
          `<option value="${escapeHtml(item.label)}" data-id="${escapeHtml(String(item.id))}">${escapeHtml(item.label)}</option>`,
      )
      .join("");
    if (current) categoryEl.value = current;
  }
  if (bookEl) {
    const current = book ?? bookEl.value;
    bookEl.innerHTML =
      `<option value="">General</option>` +
      state.expenseChoices.books
        .map((item) => `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)}</option>`)
        .join("");
    if (current) bookEl.value = current;
  }
}

function rememberChoices(data) {
  if (!data) return;
  if (data.vendors) state.expenseChoices.vendors = data.vendors;
  if (data.categories) state.expenseChoices.categories = data.categories;
  if (data.books) state.expenseChoices.books = data.books;
}

function filteredExpenses() {
  const year = $("expenseYearFilter")?.value || String(new Date().getFullYear());
  const book = $("expenseBookFilter")?.value || "";
  const vendor = ($("expenseVendorFilter")?.value || "").toLowerCase();
  const category = $("expenseCategoryFilter")?.value || "";
  const writeOff = $("expenseWriteOffFilter")?.value || "";
  const query = ($("expenseSearch")?.value || "").trim().toLowerCase();
  return state.expenses.filter((row) => {
    if (year !== "all" && !String(row.spent_on || "").startsWith(year)) return false;
    if (book === "general" && row.title) return false;
    if (book && book !== "general" && row.title !== book) return false;
    if (vendor && String(row.payee || "").toLowerCase() !== vendor) return false;
    if (category && row.category !== category) return false;
    const percent = Number(row.write_off_percent);
    const shown = Number.isFinite(percent) ? percent : 100;
    if (writeOff === "yes" && shown <= 0) return false;
    if (writeOff === "no" && shown > 0) return false;
    if (query) {
      const haystack = [row.payee, row.category, row.description, row.title, row.notes, row.payment_method]
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  });
}

function sortExpenseRows(rows) {
  return rows.slice().sort((a, b) => String(a.spent_on || "").localeCompare(String(b.spent_on || "")) || a.id - b.id);
}

function expenseLineTable(rows) {
  const body = sortExpenseRows(rows)
    .map((row) => {
      const percent = Number.isFinite(Number(row.write_off_percent)) ? Number(row.write_off_percent) : 100;
      return `
        <tr data-expense-id="${row.id}">
          <td>${escapeHtml(row.spent_on || "")}</td>
          <td>${escapeHtml(row.payee || "—")}</td>
          <td>${escapeHtml(row.category || "")}</td>
          <td class="amount">$${escapeHtml(row.write_off_amount || moneyFromCents(expenseWriteOffCents(row)))}<div class="muted">${percent}%</div></td>
          <td>${escapeHtml(row.description || "")}</td>
          <td class="amount">$${escapeHtml(row.amount || moneyFromCents(row.amount_cents))}</td>
        </tr>`;
    })
    .join("");
  const total = rows.reduce((sum, row) => sum + (Number(row.amount_cents) || 0), 0);
  const deducted = rows.reduce((sum, row) => sum + expenseWriteOffCents(row), 0);
  return `
    <div class="expense-table-scroll">
      <table class="expense-table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Vendor</th>
            <th>Category</th>
            <th class="amount">Tax write-off</th>
            <th>Description</th>
            <th class="amount">Amount</th>
          </tr>
        </thead>
        <tbody>${body}</tbody>
        <tfoot>
          <tr>
            <td colspan="3">${rows.length} transaction${rows.length === 1 ? "" : "s"}</td>
            <td class="amount">$${escapeHtml(moneyFromCents(deducted))}</td>
            <td></td>
            <td class="amount">$${escapeHtml(moneyFromCents(total))}</td>
          </tr>
        </tfoot>
      </table>
    </div>`;
}

function totalRows(pairs) {
  return pairs
    .map(
      ([label, amount, deducted]) =>
        `<tr><th>${escapeHtml(label)}</th><td class="amount">$${escapeHtml(moneyFromCents(deducted))}</td><td class="amount">$${escapeHtml(moneyFromCents(amount))}</td></tr>`,
    )
    .join("");
}

function renderExpenseReport() {
  const report = $("expenseReport");
  if (!report) return;
  fillExpenseYearSelect(state.expenses);
  fillExpenseFilters();
  const rows = filteredExpenses();
  const count = $("expenseCount");
  if (count) count.textContent = rows.length ? `${rows.length} transaction${rows.length === 1 ? "" : "s"}` : "No transactions";
  const book = $("expenseBookFilter")?.value || "";
  const vendor = $("expenseVendorFilter")?.value || "";
  const year = $("expenseYearFilter")?.value || "all";
  const bookLabel = book === "general" ? "General" : book || "All books";
  const vendorLabel = vendor || "All vendors";
  const period = year === "all" ? "All years" : `Year ${year}`;
  const groups = new Map();
  for (const row of sortExpenseRows(rows)) {
    const key = row.title || "";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  const orderedKeys = [...groups.keys()].sort((a, b) => {
    if (!a) return -1;
    if (!b) return 1;
    return a.localeCompare(b);
  });
  const sections = orderedKeys
    .map((key) => {
      const heading = book ? "" : `<h3>${escapeHtml(key || "General")}</h3>`;
      return `<section class="expense-report-section">${heading}${expenseLineTable(groups.get(key))}</section>`;
    })
    .join("");
  const byBook = new Map();
  const byVendor = new Map();
  const byCategory = new Map();
  for (const row of rows) {
    const bookName = row.title || "General";
    const vendorName = row.payee || "—";
    const categoryName = row.category || "Other";
    const amount = Number(row.amount_cents) || 0;
    const deducted = expenseWriteOffCents(row);
    for (const [map, name] of [
      [byBook, bookName],
      [byVendor, vendorName],
      [byCategory, categoryName],
    ]) {
      const current = map.get(name) || { amount: 0, deducted: 0 };
      current.amount += amount;
      current.deducted += deducted;
      map.set(name, current);
    }
  }
  const head = `<tr><th></th><th class="amount">Tax write-off</th><th class="amount">Amount</th></tr>`;
  const grand = rows.reduce((sum, row) => sum + (Number(row.amount_cents) || 0), 0);
  const writeOff = rows.reduce((sum, row) => sum + expenseWriteOffCents(row), 0);
  const notDeducted = grand - writeOff;
  const currencyNote = [...new Set(rows.map((row) => row.currency || "USD"))].join(", ") || "USD";
  report.innerHTML = `
    <header class="expense-report-head">
      <div>
        <h2>Expense report</h2>
        <p class="muted">${escapeHtml(bookLabel)} · ${escapeHtml(vendorLabel)} · ${escapeHtml(period)}</p>
      </div>
      <div class="expense-report-amount">
        <div>$${escapeHtml(moneyFromCents(grand))} <span class="muted">${escapeHtml(currencyNote)}</span></div>
        <p class="muted">Tax write-off $${escapeHtml(moneyFromCents(writeOff))}</p>
      </div>
    </header>
    ${sections || `<p class="empty">No transactions in this report.</p>`}
    <section class="expense-report-section">
      <h3>By book</h3>
      <table class="expense-report-totals"><thead>${head}</thead><tbody>
        ${totalRows([...byBook.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([name, item]) => [name, item.amount, item.deducted]))}
        <tr class="expense-report-grand"><th>Total</th><td class="amount">$${escapeHtml(moneyFromCents(writeOff))}</td><td class="amount">$${escapeHtml(moneyFromCents(grand))}</td></tr>
      </tbody></table>
    </section>
    <section class="expense-report-section">
      <h3>By vendor</h3>
      <table class="expense-report-totals"><thead>${head}</thead><tbody>
        ${totalRows([...byVendor.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([name, item]) => [name, item.amount, item.deducted]))}
      </tbody></table>
    </section>
    <section class="expense-report-section">
      <h3>By category</h3>
      <table class="expense-report-totals"><thead>${head}</thead><tbody>
        ${totalRows([...byCategory.entries()].sort((a, b) => b[1].amount - a[1].amount).map(([name, item]) => [name, item.amount, item.deducted]))}
      </tbody></table>
    </section>
    <section class="expense-report-section">
      <h3>Tax write-offs</h3>
      <table class="expense-report-totals"><tbody>
        <tr><th>Deductible</th><td class="amount">$${escapeHtml(moneyFromCents(writeOff))}</td></tr>
        <tr><th>Not deductible</th><td class="amount">$${escapeHtml(moneyFromCents(notDeducted))}</td></tr>
        <tr class="expense-report-grand"><th>Total</th><td class="amount">$${escapeHtml(moneyFromCents(grand))}</td></tr>
      </tbody></table>
    </section>`;
}

async function loadExpenses() {
  const data = await api("/api/expenses");
  state.expenses = data.expenses || [];
  rememberChoices(data);
  renderExpenseReport();
}

function receiptKind(name, mime) {
  const type = String(mime || "").toLowerCase();
  const lower = String(name || "").toLowerCase();
  if (type === "image/heic" || type === "image/heif" || lower.endsWith(".heic") || lower.endsWith(".heif")) return "file";
  if (type.startsWith("image/") || /\.(png|jpe?g|gif|webp|tiff?)$/.test(lower)) return "image";
  if (type === "application/pdf" || lower.endsWith(".pdf")) return "pdf";
  return "file";
}

function receiptThumb(src, name, kind) {
  const safe = escapeHtml(name || "Receipt");
  if (kind === "image") return `<a class="receipt-thumb" href="${src}" target="_blank" rel="noopener"><img src="${src}" alt="${safe}"></a>`;
  if (kind === "pdf") {
    return `<a class="receipt-thumb" href="${src}" target="_blank" rel="noopener"><object data="${src}#toolbar=0&navpanes=0&scrollbar=0&view=FitH" type="application/pdf"></object><span>PDF</span></a>`;
  }
  return "";
}

function formatReceiptSize(bytes) {
  const n = Number(bytes) || 0;
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function revokePendingPreviews() {
  for (const url of state.expenseUi.pendingPreviewUrls || []) URL.revokeObjectURL(url);
  state.expenseUi.pendingPreviewUrls = [];
}

function setExpenseDropHint() {
  const hint = $("expenseDrop")?.querySelector("p");
  if (!hint) return;
  const pending = state.expenseUi.pendingFiles || [];
  hint.textContent = pending.length
    ? `${pending.length} file${pending.length === 1 ? "" : "s"} ready to attach on save.`
    : "Drop, paste, or click to attach PDF, JPG, or PNG receipts.";
}

function renderExpenseReceipts(attachments) {
  const wrap = $("expenseReceipts");
  if (!wrap) return;
  revokePendingPreviews();
  state.expenseUi.currentAttachments = attachments || [];
  const saved = state.expenseUi.currentAttachments
    .map((att) => {
      const src = `/api/expense-receipts/${att.id}`;
      const kind = receiptKind(att.original_name, att.mime_type);
      return `
        <div class="receipt-row">
          ${receiptThumb(src, att.original_name, kind)}
          <a href="${src}" target="_blank" rel="noopener">${escapeHtml(att.original_name)}</a>
          <span class="muted">${escapeHtml(formatReceiptSize(att.byte_size))}</span>
          <button type="button" class="btn" data-reveal-receipt="${att.id}">Finder</button>
          <button type="button" class="btn danger" data-delete-receipt="${att.id}">Remove</button>
        </div>`;
    })
    .join("");
  const pending = (state.expenseUi.pendingFiles || [])
    .map((file, index) => {
      const kind = receiptKind(file.name, file.type);
      let thumb = "";
      if (kind !== "file") {
        const url = URL.createObjectURL(file);
        state.expenseUi.pendingPreviewUrls.push(url);
        thumb = receiptThumb(url, file.name, kind);
      }
      return `
        <div class="receipt-row">
          ${thumb}
          <span>${escapeHtml(file.name)}</span>
          <span class="muted">pending · ${escapeHtml(formatReceiptSize(file.size))}</span>
          <button type="button" class="btn" data-remove-pending="${index}">Remove</button>
        </div>`;
    })
    .join("");
  wrap.innerHTML = saved + pending;
}

function resetExpenseForm() {
  $("expenseEditId").value = "";
  $("expenseDialogTitle").textContent = "Add expense";
  $("expenseDate").value = today();
  $("expenseAmount").value = "";
  $("expenseCurrency").value = "USD";
  $("expenseDescription").value = "";
  $("expensePayment").value = "";
  $("expenseNotes").value = "";
  $("expenseWriteOffPercent").value = "100";
  fillExpenseFormSelects({
    book: $("expenseBookFilter")?.value === "general" ? "" : $("expenseBookFilter")?.value || "",
  });
  $("deleteExpenseBtn").classList.add("hidden");
  $("saveAndAddExpenseBtn").classList.remove("hidden");
  $("expenseSavedHint").textContent = "";
  $("expenseSavedHint").classList.add("hidden");
  state.expenseUi.pendingFiles = [];
  state.expenseUi.currentAttachments = [];
  if ($("expenseFiles")) $("expenseFiles").value = "";
  setExpenseDropHint();
  renderExpenseReceipts([]);
  updateWriteOffHint();
}

function openExpense(expense) {
  fillExpenseFormSelects({
    vendor: expense.payee,
    category: expense.category,
    book: expense.title || "",
  });
  if (expense.payee && $("expenseVendor").value !== expense.payee) {
    $("expenseVendor").insertAdjacentHTML(
      "afterbegin",
      `<option value="${escapeHtml(expense.payee)}">${escapeHtml(expense.payee)}</option>`,
    );
    $("expenseVendor").value = expense.payee;
  }
  if (expense.category && $("expenseCategory").value !== expense.category) {
    $("expenseCategory").insertAdjacentHTML(
      "afterbegin",
      `<option value="${escapeHtml(expense.category)}">${escapeHtml(expense.category)}</option>`,
    );
    $("expenseCategory").value = expense.category;
  }
  if (expense.title && $("expenseBook").value !== expense.title) {
    $("expenseBook").insertAdjacentHTML(
      "beforeend",
      `<option value="${escapeHtml(expense.title)}">${escapeHtml(expense.title)}</option>`,
    );
    $("expenseBook").value = expense.title;
  }
  $("expenseEditId").value = String(expense.id);
  $("expenseDialogTitle").textContent = "Edit expense";
  $("expenseDate").value = expense.spent_on || "";
  $("expenseAmount").value = expense.amount || moneyFromCents(expense.amount_cents);
  $("expenseCurrency").value = expense.currency || "USD";
  $("expenseDescription").value = expense.description || "";
  $("expensePayment").value = expense.payment_method || "";
  $("expenseNotes").value = expense.notes || "";
  $("expenseWriteOffPercent").value = String(
    Number.isFinite(Number(expense.write_off_percent)) ? expense.write_off_percent : 100,
  );
  $("deleteExpenseBtn").classList.remove("hidden");
  $("saveAndAddExpenseBtn").classList.add("hidden");
  $("expenseSavedHint").textContent = "";
  $("expenseSavedHint").classList.add("hidden");
  state.expenseUi.pendingFiles = [];
  if ($("expenseFiles")) $("expenseFiles").value = "";
  setExpenseDropHint();
  renderExpenseReceipts(expense.attachments || []);
  updateWriteOffHint();
  $("expenseDialog").showModal();
}

function queuePendingReceipts(fileList) {
  const picked = [...fileList].filter(Boolean);
  if (!picked.length) return;
  state.expenseUi.pendingFiles = [...(state.expenseUi.pendingFiles || []), ...picked];
  setExpenseDropHint();
  renderExpenseReceipts(state.expenseUi.currentAttachments);
}

async function uploadPendingReceipts(expenseId) {
  const files = state.expenseUi.pendingFiles || [];
  if (!files.length) return null;
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  const saved = await api(`/api/expenses/${expenseId}/attachments`, { method: "POST", body: form });
  state.expenseUi.pendingFiles = [];
  return saved;
}

function expensePayload() {
  const amount = dollarsToCents($("expenseAmount").value);
  if (amount === null) throw new Error("Amount is required.");
  const payee = $("expenseVendor").value.trim();
  const category = $("expenseCategory").value.trim();
  if (!payee) throw new Error("Vendor is required.");
  if (!category) throw new Error("Category is required.");
  return {
    spent_on: $("expenseDate").value,
    payee,
    category,
    description: $("expenseDescription").value.trim(),
    amount_cents: amount,
    currency: $("expenseCurrency").value.trim().toUpperCase() || "USD",
    title: $("expenseBook").value.trim(),
    notes: $("expenseNotes").value.trim(),
    payment_method: $("expensePayment").value.trim(),
    write_off_percent: writeOffPercentValue(),
  };
}

async function saveCurrentExpense() {
  const payload = expensePayload();
  const existingId = $("expenseEditId").value;
  const saved = existingId
    ? await api(`/api/expenses/${existingId}`, { method: "PATCH", body: payload })
    : await api("/api/expenses", { method: "POST", body: payload });
  const withReceipts = (await uploadPendingReceipts(saved.id)) || saved;
  return withReceipts;
}

$("expenseYearFilter")?.addEventListener("change", () => {
  expenseYearTouched = true;
  renderExpenseReport();
});
["expenseBookFilter", "expenseVendorFilter", "expenseCategoryFilter", "expenseWriteOffFilter"].forEach((id) => {
  $(id)?.addEventListener("change", renderExpenseReport);
});
$("expenseSearch")?.addEventListener("input", renderExpenseReport);
$("printExpenseReportBtn")?.addEventListener("click", () => window.print());

$("newExpenseBtn")?.addEventListener("click", () => {
  resetExpenseForm();
  $("expenseDialog").showModal();
});

$("expenseReport")?.addEventListener("click", (event) => {
  if (event.target.closest("a, button")) return;
  const row = event.target.closest("[data-expense-id]");
  if (!row) return;
  const expense = state.expenses.find((item) => String(item.id) === row.dataset.expenseId);
  if (expense) openExpense(expense);
});

$("addVendorBtn")?.addEventListener("click", async () => {
  const name = (window.prompt("New vendor name") || "").trim();
  if (!name) return;
  try {
    const data = await api("/api/expense-vendors", { method: "POST", body: { name } });
    rememberChoices(data);
    fillExpenseFilters();
    fillExpenseFormSelects({ vendor: data.vendor?.name || name });
  } catch (error) {
    alert(error.message);
  }
});

$("removeVendorBtn")?.addEventListener("click", async () => {
  const id = selectedChoiceId("expenseVendor");
  const name = $("expenseVendor")?.value || "";
  if (!id) {
    alert("Choose a vendor to remove.");
    return;
  }
  if (!confirm(`Remove ${name} from the vendor list? Existing expenses keep this name.`)) return;
  try {
    const data = await api(`/api/expense-vendors/${id}`, { method: "DELETE" });
    rememberChoices(data);
    fillExpenseFilters();
    fillExpenseFormSelects();
  } catch (error) {
    alert(error.message);
  }
});

$("addCategoryBtn")?.addEventListener("click", async () => {
  const label = (window.prompt("New category name") || "").trim();
  if (!label) return;
  try {
    const data = await api("/api/expense-categories", { method: "POST", body: { label } });
    rememberChoices(data);
    fillExpenseFilters();
    fillExpenseFormSelects({ category: data.category?.label || label });
  } catch (error) {
    alert(error.message);
  }
});

$("removeCategoryBtn")?.addEventListener("click", async () => {
  const id = selectedChoiceId("expenseCategory");
  const label = $("expenseCategory")?.selectedOptions?.[0]?.textContent || "";
  if (!id) {
    alert("Choose a category to remove.");
    return;
  }
  if (!confirm(`Remove ${label} from the category list? Existing expenses keep this category.`)) return;
  try {
    const data = await api(`/api/expense-categories/${id}`, { method: "DELETE" });
    rememberChoices(data);
    fillExpenseFilters();
    fillExpenseFormSelects();
  } catch (error) {
    alert(error.message);
  }
});

$("addBookBtn")?.addEventListener("click", async () => {
  const name = (window.prompt("Book title") || "").trim();
  if (!name) return;
  try {
    const data = await api("/api/expense-books", { method: "POST", body: { name } });
    rememberChoices(data);
    fillExpenseFilters();
    fillExpenseFormSelects({ book: data.book?.name || name });
  } catch (error) {
    alert(error.message);
  }
});

$("expenseFiles")?.addEventListener("change", (event) => {
  queuePendingReceipts(event.target.files || []);
  event.target.value = "";
});

const expenseDrop = $("expenseDrop");
if (expenseDrop) {
  ["dragenter", "dragover"].forEach((type) => {
    expenseDrop.addEventListener(type, (event) => {
      event.preventDefault();
      expenseDrop.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach((type) => {
    expenseDrop.addEventListener(type, (event) => {
      event.preventDefault();
      expenseDrop.classList.remove("dragover");
    });
  });
  expenseDrop.addEventListener("drop", (event) => {
    queuePendingReceipts(event.dataTransfer?.files || []);
  });
}

$("expenseDialog")?.addEventListener("paste", (event) => {
  const files = [...(event.clipboardData?.files || [])];
  if (!files.length) return;
  event.preventDefault();
  queuePendingReceipts(files);
});

$("expenseReceipts")?.addEventListener("click", async (event) => {
  const reveal = event.target.closest("[data-reveal-receipt]");
  if (reveal) {
    try {
      await api(`/api/expense-receipts/${reveal.dataset.revealReceipt}/reveal`, { method: "POST" });
    } catch (error) {
      alert(error.message);
    }
    return;
  }
  const removePending = event.target.closest("[data-remove-pending]");
  if (removePending) {
    state.expenseUi.pendingFiles.splice(Number(removePending.dataset.removePending), 1);
    setExpenseDropHint();
    renderExpenseReceipts(state.expenseUi.currentAttachments);
    return;
  }
  const remove = event.target.closest("[data-delete-receipt]");
  if (!remove) return;
  if (!confirm("Remove this receipt from the expense?")) return;
  try {
    const expense = await api(`/api/expense-receipts/${remove.dataset.deleteReceipt}`, { method: "DELETE" });
    renderExpenseReceipts(expense.attachments || []);
    await loadExpenses();
  } catch (error) {
    alert(error.message);
  }
});

$("expenseWriteOffPercent")?.addEventListener("input", updateWriteOffHint);
$("expenseAmount")?.addEventListener("input", updateWriteOffHint);

$("saveExpenseBtn")?.addEventListener("click", async () => {
  try {
    await saveCurrentExpense();
    $("expenseDialog").close();
    setMessage("Expense saved.");
    await loadExpenses();
  } catch (error) {
    setMessage(error.message, true);
  }
});

$("saveAndAddExpenseBtn")?.addEventListener("click", async () => {
  try {
    await saveCurrentExpense();
    $("expenseEditId").value = "";
    $("expenseDialogTitle").textContent = "Add expense";
    $("deleteExpenseBtn").classList.add("hidden");
    $("saveAndAddExpenseBtn").classList.remove("hidden");
    state.expenseUi.pendingFiles = [];
    state.expenseUi.currentAttachments = [];
    if ($("expenseFiles")) $("expenseFiles").value = "";
    setExpenseDropHint();
    renderExpenseReceipts([]);
    $("expenseSavedHint").textContent = "Saved. These details carry over. Attach the next receipt.";
    $("expenseSavedHint").classList.remove("hidden");
    setMessage("Expense saved.");
    await loadExpenses();
  } catch (error) {
    setMessage(error.message, true);
  }
});

$("deleteExpenseBtn")?.addEventListener("click", async () => {
  const id = $("expenseEditId").value;
  if (!id) return;
  if (!confirm("Delete this expense and its receipts?")) return;
  try {
    await api(`/api/expenses/${id}`, { method: "DELETE" });
    $("expenseDialog").close();
    setMessage("Expense deleted.");
    await loadExpenses();
  } catch (error) {
    setMessage(error.message, true);
  }
});

loadExpenses().catch((error) => setMessage(error.message, true));
