function estimateStripeFeeCents(cents, currency) {
  if (currency !== "USD" || cents == null || cents <= 0) return null;
  return Math.floor((cents * 290 + 5000) / 10000) + 30;
}

function addStat(parent, label, value) {
  const box = document.createElement("div");
  box.className = "stat";
  box.appendChild(el("span", label, "muted"));
  box.appendChild(el("strong", value));
  parent.appendChild(box);
}

function countLabel(count, singular, plural) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function renderOrderStats(target) {
  clear(target);
  const totals = state.orderData.totals;
  addStat(
    target,
    "Not shipped",
    `${countLabel(totals.not_shipped_orders, "order", "orders")} · ${countLabel(totals.not_shipped_copies, "copy", "copies")}`,
  );
  addStat(
    target,
    "Shipped",
    `${countLabel(totals.shipped_orders, "order", "orders")} · ${countLabel(totals.shipped_copies, "copy", "copies")}`,
  );
  addStat(target, "Open refund requests", String(totals.open_refunds));
  if (!totals.by_currency.length) {
    addStat(target, "Sales minus Stripe fee", "—");
    return;
  }
  totals.by_currency.forEach((row) => {
    const code = row.currency;
    addStat(target, `Sales (${code})`, money(row.gross_cents, code));
    addStat(target, `Stripe fee (${code})`, money(row.stripe_fee_cents, code));
    addStat(target, `Sales minus Stripe fee (${code})`, money(row.sales_after_fee_cents, code));
    if (row.refunded_cents) addStat(target, `Refunded (${code})`, money(row.refunded_cents, code));
  });
}

function copiesOnHand(titleId, locationId) {
  const row = (state.orderData.on_hand || []).find(
    (item) => item.title_id === Number(titleId) && item.location_id === Number(locationId),
  );
  return row ? row.quantity : 0;
}

function otherWaitingCopies(titleId, exceptOrderId) {
  return state.orderData.orders
    .filter(
      (order) =>
        order.title_id === Number(titleId) &&
        order.ship_status === "not_shipped" &&
        !order.stock_taken_at &&
        String(order.id) !== String(exceptOrderId || ""),
    )
    .reduce((sum, order) => sum + Number(order.quantity), 0);
}

function updateOrderStockHint() {
  const hint = $("orderStockHint");
  if (!$("orderTitle").value || !$("orderFrom").value) {
    hint.textContent = state.orderData.titles.length ? "" : "Add a title on Inventory before saving an order.";
    return;
  }
  const location = state.orderData.locations.find((item) => String(item.id) === $("orderFrom").value);
  const onHand = copiesOnHand($("orderTitle").value, $("orderFrom").value);
  const waiting = otherWaitingCopies($("orderTitle").value, $("orderEditId").value);
  const name = location ? location.name : "that shelf";
  hint.textContent = `${onHand} on hand at ${name}. ${waiting} other ${waiting === 1 ? "copy is" : "copies are"} on orders that are not shipped yet.`;
}

function updateOrderFeeHint() {
  const hint = $("orderFeeHint");
  let cents = null;
  try {
    cents = dollarsToCents($("orderAmount").value);
  } catch {
    cents = null;
  }
  const currency = ($("orderCurrency").value || "USD").trim().toUpperCase();
  const estimate = estimateStripeFeeCents(cents, currency);
  if (estimate == null) {
    hint.textContent = currency === "USD" || !cents ? "" : "Enter the Stripe fee for this currency.";
    return;
  }
  hint.textContent = $("orderFee").value.trim() ? "" : `Blank fee estimates ${money(estimate, "USD")} kept by Stripe.`;
}

function visibleOrders() {
  const shipFilter = $("orderShipFilter").value;
  const query = $("orderSearch").value.trim().toLowerCase();
  return state.orderData.orders.filter((order) => {
    if (shipFilter === "not_shipped" && order.ship_status !== "not_shipped") return false;
    if (shipFilter === "shipped" && order.ship_status !== "shipped") return false;
    if (shipFilter === "refund_open" && !order.open_refunds) return false;
    if (!query) return true;
    const haystack = [
      order.buyer_name,
      order.email,
      order.title,
      order.tracking_number,
      order.carrier,
      order.ship_to,
      order.notes,
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(query);
  });
}

function shipmentBadges(order) {
  const wrap = document.createElement("div");
  wrap.className = "cell-stack";
  if (order.ship_status === "shipped") wrap.appendChild(el("span", "Shipped", "badge shipped"));
  else wrap.appendChild(el("span", "Not shipped", "badge waiting"));
  if (order.stock_taken_at === "payment" && order.ship_status !== "shipped") {
    wrap.appendChild(el("span", "Off the shelf", "badge shipped"));
  }
  if (order.open_refunds) wrap.appendChild(el("span", "Refund open", "badge open"));
  else if (order.refunded_cents) wrap.appendChild(el("span", "Refunded", "badge refunded"));
  return wrap;
}

function renderOrders() {
  if (!state.orderData || !$("orderRows")) return;
  renderOrderStats($("orderStats"));
  const rows = visibleOrders();
  const body = $("orderRows");
  clear(body);
  $("orderCount").textContent = `${rows.length} order${rows.length === 1 ? "" : "s"}`;
  $("orderEmpty").classList.toggle("hidden", state.orderData.orders.length > 0);
  rows.forEach((order) => {
    const tr = document.createElement("tr");
    tr.appendChild(el("td", order.ordered_on));
    const buyer = document.createElement("td");
    const stack = document.createElement("div");
    stack.className = "cell-stack";
    stack.appendChild(el("span", order.buyer_name));
    if (order.email) stack.appendChild(el("span", order.email, "muted"));
    buyer.appendChild(stack);
    tr.appendChild(buyer);
    tr.appendChild(el("td", order.title));
    tr.appendChild(el("td", order.quantity, "num"));
    tr.appendChild(el("td", order.from_location || "—"));
    const shipment = document.createElement("td");
    shipment.appendChild(shipmentBadges(order));
    tr.appendChild(shipment);
    const tracking = document.createElement("td");
    const trackingStack = document.createElement("div");
    trackingStack.className = "cell-stack";
    trackingStack.appendChild(el("span", order.tracking_number || "—"));
    if (order.carrier) trackingStack.appendChild(el("span", order.carrier, "muted"));
    tracking.appendChild(trackingStack);
    tr.appendChild(tracking);
    tr.appendChild(el("td", money(order.amount_cents, order.currency), "num"));
    tr.appendChild(el("td", money(order.stripe_fee_cents, order.currency), "num"));
    const afterFee = document.createElement("td");
    afterFee.className = "num";
    const afterStack = document.createElement("div");
    afterStack.className = "cell-stack";
    afterStack.appendChild(el("span", money(order.amount_cents - order.stripe_fee_cents, order.currency)));
    if (order.refunded_cents) {
      afterStack.appendChild(el("span", `refunded ${money(order.refunded_cents, order.currency)}`, "muted"));
    }
    afterFee.appendChild(afterStack);
    tr.appendChild(afterFee);
    tr.addEventListener("click", () => openOrder(order));
    body.appendChild(tr);
  });
}

function refundRoom(order) {
  const used = order.refunds
    .filter((refund) => refund.status !== "declined")
    .reduce((sum, refund) => sum + Number(refund.amount_cents), 0);
  return Math.max(0, Number(order.amount_cents) - used);
}

function fillRefundOrders() {
  const select = $("refundOrder");
  const current = state.pendingRefundOrderId ? String(state.pendingRefundOrderId) : select.value;
  clear(select);
  state.orderData.orders.forEach((order) => {
    const option = document.createElement("option");
    option.value = String(order.id);
    option.textContent = `${order.ordered_on} · ${order.buyer_name} · ${order.title} · ${money(order.amount_cents, order.currency)}`;
    select.appendChild(option);
  });
  if (current && [...select.options].some((option) => option.value === current)) select.value = current;
  state.pendingRefundOrderId = null;
  updateRefundRoom();
}

function updateRefundRoom() {
  const hint = $("refundRoomHint");
  const order = state.orderData.orders.find((item) => String(item.id) === $("refundOrder").value);
  if (!order) {
    hint.textContent = "Add an order first.";
    return;
  }
  const room = refundRoom(order);
  hint.textContent = `${money(room, order.currency)} still available on this sale.`;
  if (!$("refundAmount").dataset.touched) $("refundAmount").value = (room / 100).toFixed(2);
}

function refundStatusLabel(status) {
  if (status === "refunded") return "Refunded";
  if (status === "declined") return "Declined";
  return "Open";
}

function visibleRefunds() {
  const status = $("refundStatusFilter").value;
  if (!status) return state.orderData.refunds;
  return state.orderData.refunds.filter((refund) => refund.status === status);
}

function renderRefunds() {
  if (!state.orderData || !$("refundRows")) return;
  renderOrderStats($("refundStats"));
  const body = $("refundRows");
  clear(body);
  const rows = visibleRefunds();
  $("refundEmpty").classList.toggle("hidden", state.orderData.refunds.length > 0);
  rows.forEach((refund) => {
    const tr = document.createElement("tr");
    tr.appendChild(el("td", refund.requested_on));
    tr.appendChild(el("td", `${refund.ordered_on} · ${refund.buyer_name}`));
    tr.appendChild(el("td", refund.title));
    const status = document.createElement("td");
    status.appendChild(el("span", refundStatusLabel(refund.status), `badge ${refund.status === "open" ? "open" : refund.status}`));
    tr.appendChild(status);
    tr.appendChild(el("td", money(refund.amount_cents, refund.currency), "num"));
    tr.appendChild(el("td", refund.reason || "—"));
    const actions = document.createElement("td");
    actions.className = "button-row";
    if (refund.status !== "refunded") {
      actions.appendChild(refundAction(refund, "Mark refunded", "refunded"));
    }
    if (refund.status !== "declined") {
      actions.appendChild(refundAction(refund, "Decline", "declined"));
    }
    if (refund.status !== "open") {
      actions.appendChild(refundAction(refund, "Reopen", "open"));
    }
    const remove = el("button", "Delete", "btn small danger");
    remove.type = "button";
    remove.addEventListener("click", async () => {
      if (!confirm("Delete this refund request?")) return;
      try {
        await api(`/api/refunds/${refund.id}`, { method: "DELETE" });
        setMessage("Refund request deleted.");
        await loadOrders();
      } catch (error) {
        setMessage(error.message, true);
      }
    });
    actions.appendChild(remove);
    tr.appendChild(actions);
    body.appendChild(tr);
  });
}

function refundAction(refund, label, status) {
  const button = el("button", label, "btn small");
  button.type = "button";
  button.addEventListener("click", async () => {
    try {
      await api(`/api/refunds/${refund.id}`, { method: "PATCH", body: { status } });
      setMessage(
        status === "refunded"
          ? "Refund marked refunded. It now comes out of sales."
          : "Refund request updated.",
      );
      await loadOrders();
    } catch (error) {
      setMessage(error.message, true);
    }
  });
  return button;
}

function fillOrderSelects(order) {
  fillTitles($("orderTitle"), state.orderData.titles);
  fillSelect($("orderFrom"), state.orderData.locations, "Home");
  if (!order) return;
  $("orderTitle").value = String(order.title_id);
  if (order.from_location_id) $("orderFrom").value = String(order.from_location_id);
}

function openOrder(order) {
  if (!state.orderData.titles.length) {
    setMessage("Add a title on Inventory first.", true);
    return;
  }
  const editing = Boolean(order);
  $("orderDialogTitle").textContent = editing ? `Order ${order.id}` : "Add order";
  $("orderEditId").value = editing ? String(order.id) : "";
  $("deleteOrderBtn").classList.toggle("hidden", !editing);
  $("orderRefundBtn").classList.toggle("hidden", !editing);
  $("orderDate").value = editing ? order.ordered_on : today();
  $("orderBuyer").value = editing ? order.buyer_name : "";
  $("orderEmail").value = editing ? order.email || "" : "";
  $("orderShipTo").value = editing ? order.ship_to || "" : "";
  $("orderCurrency").value = editing ? order.currency : "USD";
  $("orderQty").value = editing ? String(order.quantity) : "1";
  $("orderAmount").value = editing ? (order.amount_cents / 100).toFixed(2) : "";
  $("orderFee").value = editing ? (order.stripe_fee_cents / 100).toFixed(2) : "";
  $("orderNotes").value = editing ? order.notes || "" : "";
  $("orderShipped").checked = editing && order.ship_status === "shipped";
  $("orderShippedOn").value = editing && order.shipped_on ? order.shipped_on : today();
  $("orderCarrier").value = editing ? order.carrier || "" : "";
  $("orderTracking").value = editing ? order.tracking_number || "" : "";
  fillOrderSelects(order);
  const stockLocked = Boolean(order && order.stock_taken_at === "payment");
  $("orderTitle").disabled = stockLocked;
  $("orderQty").disabled = stockLocked;
  $("orderFrom").disabled = stockLocked;
  updateOrderFeeHint();
  updateOrderStockHint();
  $("orderDialog").showModal();
}

function orderPayload() {
  const feeText = $("orderFee").value.trim();
  const amount = dollarsToCents($("orderAmount").value);
  if (amount == null) throw new Error("Enter the sale total.");
  const fee = feeText ? dollarsToCents(feeText) : null;
  if (feeText && fee == null) throw new Error("Enter the Stripe fee like 1.37, or leave it blank.");
  return {
    ordered_on: $("orderDate").value,
    buyer_name: $("orderBuyer").value.trim(),
    email: $("orderEmail").value.trim(),
    ship_to: $("orderShipTo").value.trim(),
    title_id: requireTitleId($("orderTitle")),
    quantity: Number($("orderQty").value),
    from_location_id: Number($("orderFrom").value),
    amount_cents: amount,
    stripe_fee_cents: fee,
    currency: $("orderCurrency").value.trim().toUpperCase() || "USD",
    notes: $("orderNotes").value.trim(),
    tracking_number: $("orderTracking").value.trim(),
    carrier: $("orderCarrier").value.trim(),
  };
}

async function saveOrder() {
  if (!$("orderForm").reportValidity()) return;
  const payload = orderPayload();
  const wantShipped = $("orderShipped").checked;
  if (wantShipped && !$("orderShippedOn").value) throw new Error("Enter the ship date.");
  const id = $("orderEditId").value;
  const existing = id ? state.orderData.orders.find((order) => String(order.id) === id) : null;
  const wasShipped = Boolean(existing && existing.ship_status === "shipped");
  const identityChanged = Boolean(
    existing &&
      (existing.title_id !== payload.title_id ||
        existing.quantity !== payload.quantity ||
        existing.from_location_id !== payload.from_location_id),
  );
  if (wasShipped && (identityChanged || !wantShipped)) {
    await api(`/api/orders/${id}/unship`, { method: "POST" });
  }
  let orderId = id;
  if (!id) {
    const created = await api("/api/orders", { method: "POST", body: payload });
    orderId = created.id;
  } else {
    await api(`/api/orders/${id}`, { method: "PATCH", body: payload });
  }
  if (wantShipped) {
    try {
      await api(`/api/orders/${orderId}/ship`, {
        method: "POST",
        body: {
          shipped_on: $("orderShippedOn").value,
          from_location_id: payload.from_location_id,
          tracking_number: payload.tracking_number,
          carrier: payload.carrier,
        },
      });
    } catch (error) {
      $("orderEditId").value = String(orderId);
      $("orderDialogTitle").textContent = `Order ${orderId}`;
      $("deleteOrderBtn").classList.remove("hidden");
      $("orderRefundBtn").classList.remove("hidden");
      $("orderShipped").checked = false;
      await loadOrders();
      throw new Error(`${error.message} The order is saved and still not shipped.`);
    }
  }
  $("orderDialog").close();
  setMessage(wantShipped ? "Order shipped." : "Order saved.");
  await loadOrders();
}

async function loadOrders() {
  state.orderData = await api("/api/orders");
  renderOrders();
  if ($("refundOrder")) fillRefundOrders();
  renderRefunds();
}

if ($("newOrderBtn")) $("newOrderBtn").addEventListener("click", () => {
  if (!state.orderData || !state.orderData.titles.length) {
    setMessage("Add a title on Inventory first.", true);
    return;
  }
  openOrder(null);
});

if ($("saveOrderBtn")) $("saveOrderBtn").addEventListener("click", async () => {
  try {
    await saveOrder();
  } catch (error) {
    setMessage(error.message, true);
  }
});

if ($("deleteOrderBtn")) $("deleteOrderBtn").addEventListener("click", async () => {
  const id = $("orderEditId").value;
  if (!id || !confirm("Delete this order? A shipped order puts the copies back on the shelf.")) return;
  try {
    await api(`/api/orders/${id}`, { method: "DELETE" });
    $("orderDialog").close();
    setMessage("Order deleted.");
    await loadOrders();
  } catch (error) {
    setMessage(error.message, true);
  }
});

if ($("orderRefundBtn")) $("orderRefundBtn").addEventListener("click", () => {
  const id = $("orderEditId").value;
  if (!id) return;
  $("orderDialog").close();
  location.assign(`/refunds?order=${encodeURIComponent(id)}`);
});

["orderAmount", "orderFee", "orderCurrency"].forEach((id) => {
  $(id)?.addEventListener("input", updateOrderFeeHint);
});
["orderTitle", "orderFrom", "orderQty"].forEach((id) => {
  $(id)?.addEventListener("change", updateOrderStockHint);
});
$("orderShipFilter")?.addEventListener("change", renderOrders);
$("orderSearch")?.addEventListener("input", renderOrders);
$("refundStatusFilter")?.addEventListener("change", renderRefunds);

$("refundOrder")?.addEventListener("change", () => {
  delete $("refundAmount").dataset.touched;
  updateRefundRoom();
});
$("refundAmount")?.addEventListener("input", () => {
  $("refundAmount").dataset.touched = "1";
});

$("refundForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const amount = dollarsToCents($("refundAmount").value);
    if (amount == null) throw new Error("Enter the refund amount.");
    await api(`/api/orders/${$("refundOrder").value}/refunds`, {
      method: "POST",
      body: {
        requested_on: $("refundDate").value,
        amount_cents: amount,
        reason: $("refundReason").value.trim(),
        notes: $("refundNotes").value.trim(),
      },
    });
    $("refundReason").value = "";
    $("refundNotes").value = "";
    delete $("refundAmount").dataset.touched;
    setMessage("Refund request saved.");
    await loadOrders();
  } catch (error) {
    setMessage(error.message, true);
  }
});

if ($("refundDate")) $("refundDate").value = today();
const requestedOrder = new URLSearchParams(location.search).get("order");
if (requestedOrder) state.pendingRefundOrderId = requestedOrder;
if ($("orderRows") || $("refundRows")) {
  loadOrders().catch((error) => setMessage(error.message, true));
}
