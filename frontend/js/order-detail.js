/**
 * js/order-detail.js
 * ===================
 * order-confirmation.html only. Reads ?id=<order_id>, fetches the full
 * order, and renders it: header/status, line items, and financial totals.
 *
 * Also offers a small "demo controls" panel to advance the order's status
 * via PATCH /orders/{id}/status — useful for seeing the inventory-decrement
 * behavior in action without needing a separate admin tool.
 */

const STATUS_FLOW = ["pending", "confirmed", "preparing", "shipped", "delivered"];

document.addEventListener("DOMContentLoaded", loadOrder);

async function loadOrder() {
  const params = new URLSearchParams(window.location.search);
  const orderId = params.get("id");
  const container = document.getElementById("orderDetail");

  if (!orderId) {
    container.innerHTML = notFound("No order was specified.");
    return;
  }

  try {
    const order = await Api.getOrder(orderId);
    document.title = `Order #${order.order_id} — Meera Bakery Online`;
    container.innerHTML = renderOrder(order);
    wireStatusControls(order);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      container.innerHTML = notFound("We couldn't find that order.");
    } else {
      container.innerHTML = notFound(`Couldn't load this order. Is the API running at ${API_BASE_URL}?`);
    }
  }
}

function notFound(message) {
  return `
    <div class="empty-state">
      <div class="empty-state__icon">📦</div>
      <p>${message}</p>
      <a href="orders.html" class="btn btn--primary">Back to my orders</a>
    </div>`;
}

function renderOrder(order) {
  const placedDate = new Date(order.ordered_at).toLocaleString("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  });

  return `
    <div class="order-summary-card">
      <div class="order-summary-card__head">
        <div>
          <p class="eyebrow" style="margin-bottom:4px;">Order #${order.order_id}</p>
          <h1 style="font-size:1.7rem;margin-bottom:4px;">Thank you!</h1>
          <p style="margin:0;color:var(--ink-soft);font-size:0.9rem;">Placed ${placedDate}</p>
        </div>
        <span class="status-badge status-badge--${order.status}">${order.status}</span>
      </div>

      <h3>Items</h3>
      ${order.items
        .map(
          (item) => `
        <div class="summary-row">
          <span>${item.product_name} × ${item.quantity}</span>
          <span>${formatMoney(item.line_total)}</span>
        </div>`
        )
        .join("")}

      <div class="summary-row" style="border-top:1px solid var(--paper-line);margin-top:12px;padding-top:12px;">
        <span>Subtotal</span><span>${formatMoney(order.subtotal)}</span>
      </div>
      ${
        order.discount_amount > 0
          ? `<div class="summary-row"><span>Discount</span><span>−${formatMoney(order.discount_amount)}</span></div>`
          : ""
      }
      <div class="summary-row"><span>Tax (${order.tax_percent}%)</span><span>${formatMoney(order.tax_amount)}</span></div>
      <div class="summary-row summary-row--total"><span>Total</span><span>${formatMoney(order.total_amount)}</span></div>

      <h3 style="margin-top:24px;">Delivering to</h3>
      <p style="margin:0;">${order.shipping_address_snapshot}</p>
      ${order.notes ? `<h3 style="margin-top:24px;">Notes</h3><p style="margin:0;">${order.notes}</p>` : ""}
    </div>

    <div class="order-summary-card" id="statusControls">
      <h3>Order status (demo controls)</h3>
      <p style="font-size:0.85rem;">
        In a real store, the bakery's back office would update this. For this
        learning project, you can advance it here to see inventory get
        decremented on confirmation.
      </p>
      <div id="statusButtons" style="display:flex;gap:12px;flex-wrap:wrap;margin-top:12px;"></div>
    </div>`;
}

function wireStatusControls(order) {
  const buttonsContainer = document.getElementById("statusButtons");
  const currentIndex = STATUS_FLOW.indexOf(order.status);

  if (order.status === "cancelled" || currentIndex === STATUS_FLOW.length - 1) {
    buttonsContainer.innerHTML = `<p style="color:var(--ink-soft);font-size:0.85rem;">No further transitions available.</p>`;
    return;
  }

  const nextStatus = STATUS_FLOW[currentIndex + 1];
  buttonsContainer.innerHTML = `
    <button type="button" class="btn btn--primary btn--sm" id="advanceBtn">Mark as ${nextStatus}</button>
    <button type="button" class="btn btn--ghost btn--sm" id="cancelBtn">Cancel order</button>
    <span id="statusError" style="color:var(--danger);font-size:0.85rem;"></span>`;

  document.getElementById("advanceBtn").addEventListener("click", () => updateStatus(order.order_id, nextStatus));
  document.getElementById("cancelBtn").addEventListener("click", () => updateStatus(order.order_id, "cancelled"));
}

async function updateStatus(orderId, status) {
  const errorEl = document.getElementById("statusError");
  errorEl.textContent = "";

  try {
    await request(`/orders/${orderId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
    loadOrder();
  } catch (err) {
    errorEl.textContent = err instanceof ApiError ? err.message : "Could not update order status.";
  }
}
