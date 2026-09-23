/**
 * js/cart-page.js
 * ================
 * cart.html only. Renders the cart from localStorage (via Store), lets the
 * user adjust quantities or remove lines, and shows an estimated summary.
 *
 * Note: totals shown here are a client-side ESTIMATE for the shopper's
 * convenience. The authoritative subtotal/discount/tax/total are always
 * computed server-side in order_service when the order is placed.
 */

document.addEventListener("DOMContentLoaded", renderCart);
document.addEventListener("cart:changed", renderCart);

function renderCart() {
  const container = document.getElementById("cartContent");
  const cart = Store.getCart();

  if (!cart.length) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state__icon">🧺</div>
        <p>Your cart is empty.</p>
        <a href="products.html" class="btn btn--primary">Browse products</a>
      </div>`;
    return;
  }

  const subtotal = Store.cartSubtotal();
  const estimatedTax = subtotal * 0.05; // 5% GST estimate, shown for guidance only
  const estimatedTotal = subtotal + estimatedTax;

  container.innerHTML = `
    <div class="cart-layout">
      <div>
        <div id="cartLines">
          ${cart.map(renderLine).join("")}
        </div>
        <a href="products.html" class="link-arrow" style="display:inline-block;margin-top:16px;">← Continue shopping</a>
      </div>

      <div class="summary-card">
        <h3>Order summary</h3>
        <div class="summary-row"><span>Subtotal</span><span>${formatMoney(subtotal)}</span></div>
        <div class="summary-row"><span>Estimated GST (5%)</span><span>${formatMoney(estimatedTax)}</span></div>
        <div class="summary-row summary-row--total"><span>Estimated total</span><span>${formatMoney(estimatedTotal)}</span></div>
        <a href="checkout.html" class="btn btn--primary btn--block" style="margin-top:20px;">Proceed to checkout</a>
        <p class="summary-note">Final pricing is confirmed at checkout — tax, and any discounts, are calculated by the server.</p>
      </div>
    </div>`;

  wireLineHandlers();
}

function renderLine(line) {
  const lineTotal = line.unitPrice * line.quantity;
  return `
    <div class="cart-line" data-product-id="${line.productId}">
      <div class="cart-line__thumb">${iconFor(line.categoryName)}</div>
      <div>
        <div class="cart-line__name">${line.name}</div>
        <div class="cart-line__price">${formatMoney(line.unitPrice)} each</div>
        <button type="button" class="cart-line__remove" data-remove="${line.productId}">Remove</button>
      </div>
      <div class="qty-stepper">
        <button type="button" data-minus="${line.productId}" aria-label="Decrease quantity">−</button>
        <input type="number" min="1" value="${line.quantity}" data-qty="${line.productId}" aria-label="Quantity" />
        <button type="button" data-plus="${line.productId}" aria-label="Increase quantity">+</button>
      </div>
      <div class="cart-line__total">${formatMoney(lineTotal)}</div>
    </div>`;
}

function wireLineHandlers() {
  const lines = document.getElementById("cartLines");
  if (!lines) return;

  lines.querySelectorAll("[data-remove]").forEach((btn) => {
    btn.addEventListener("click", () => {
      Store.removeFromCart(Number(btn.getAttribute("data-remove")));
    });
  });

  lines.querySelectorAll("[data-minus]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = Number(btn.getAttribute("data-minus"));
      const line = Store.getCart().find((l) => l.productId === id);
      if (line) Store.updateQuantity(id, line.quantity - 1);
    });
  });

  lines.querySelectorAll("[data-plus]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = Number(btn.getAttribute("data-plus"));
      const line = Store.getCart().find((l) => l.productId === id);
      if (line) Store.updateQuantity(id, line.quantity + 1);
    });
  });

  lines.querySelectorAll("[data-qty]").forEach((input) => {
    input.addEventListener("change", () => {
      const id = Number(input.getAttribute("data-qty"));
      const qty = Math.max(1, Number(input.value) || 1);
      Store.updateQuantity(id, qty);
    });
  });
}
