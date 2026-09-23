/**
 * js/orders.js
 * =============
 * orders.html only. Requires an identity (see Store.getIdentity()) and
 * lists that customer's order history via GET /customers/{id}/orders.
 */

document.addEventListener("DOMContentLoaded", init);
document.addEventListener("identity:changed", init);

async function init() {
  const container = document.getElementById("ordersContent");
  const identity = Store.getIdentity();

  if (!identity) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state__icon">👤</div>
        <p>Choose who you are to see order history.</p>
        <button type="button" class="btn btn--primary" id="pickIdentityBtn">Choose your name</button>
      </div>`;
    document.getElementById("pickIdentityBtn")?.addEventListener("click", () => {
      document.getElementById("identityChip")?.click();
    });
    return;
  }

  container.innerHTML = `<div class="skeleton" style="height:64px;margin-bottom:12px;"></div>`.repeat(3);

  try {
    const res = await Api.getCustomerOrders(identity.customerId, { pageSize: 50 });
    if (!res.items.length) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state__icon">📦</div>
          <p>No orders yet, ${identity.firstName}.</p>
          <a href="products.html" class="btn btn--primary">Start an order</a>
        </div>`;
      return;
    }
    container.innerHTML = res.items.map(renderOrderRow).join("");
    container.querySelectorAll(".order-row").forEach((row) => {
      row.addEventListener("click", () => {
        window.location.href = `order-confirmation.html?id=${row.getAttribute("data-order-id")}`;
      });
    });
  } catch (err) {
    container.innerHTML = `<p style="color:var(--danger);">Couldn't load orders. Is the API running at ${API_BASE_URL}?</p>`;
  }
}

function renderOrderRow(order) {
  const placedDate = new Date(order.ordered_at).toLocaleDateString("en-IN", {
    day: "numeric", month: "short", year: "numeric",
  });
  return `
    <div class="order-row" data-order-id="${order.order_id}">
      <div>
        <div class="order-row__id">Order #${order.order_id}</div>
        <div class="order-row__date">${placedDate} · ${order.item_count} item${order.item_count === 1 ? "" : "s"}</div>
      </div>
      <span class="status-badge status-badge--${order.status}">${order.status}</span>
      <div class="order-row__total">${formatMoney(order.total_amount)}</div>
    </div>`;
}
