/**
 * js/checkout.js
 * ===============
 * checkout.html only.
 *
 * Flow:
 *   1. Requires a logged-in customer (Store.getIdentity(), set by the OTP
 *      login flow in nav.js). If not logged in, prompts them to log in.
 *   2. Fetches that customer's addresses (GET /customers/{id}/addresses)
 *      and lets them choose one — or add a new one inline via
 *      POST /customers/{id}/addresses if they have none yet (or want another).
 *   3. Shows an order review built from the cart in localStorage.
 *   4. On submit, POSTs to /orders with a 5% GST default, clears the cart,
 *      and redirects to order-confirmation.html?id=<order_id>.
 *
 * Any BusinessRuleError / NotFoundError from the API is shown in the
 * banner using its message field — order_service's error messages are
 * already written to be shopper-readable.
 */

const TAX_PERCENT = 5.0; // flat demo GST rate — a real store would vary this by product/region

let selectedAddressId = null;

document.addEventListener("DOMContentLoaded", init);

async function init() {
  const container = document.getElementById("checkoutContent");
  const cart = Store.getCart();

  if (!cart.length) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state__icon">🧺</div>
        <p>Your cart is empty — add something from the menu first.</p>
        <a href="products.html" class="btn btn--primary">Browse products</a>
      </div>`;
    return;
  }

  const identity = Store.getIdentity();
  if (!identity) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state__icon">👤</div>
        <p>Please log in before checking out.</p>
        <button type="button" class="btn btn--primary" id="pickIdentityBtn">Log in</button>
      </div>`;
    document.getElementById("pickIdentityBtn")?.addEventListener("click", () => {
      document.getElementById("identityChip")?.click();
    });
    document.addEventListener("identity:changed", () => window.location.reload());
    return;
  }

  renderLayout(identity, cart);
  await loadAddresses(identity.customerId);
}

function renderLayout(identity, cart) {
  const container = document.getElementById("checkoutContent");
  container.innerHTML = `
    <div class="cart-layout">
      <div>
        <h3>Ordering as</h3>
        <p>${identity.firstName} ${identity.lastName}</p>

        <h3 style="margin-top:32px;">Delivery address</h3>
        <div id="addressList"><div class="skeleton" style="height:80px;"></div></div>

        <h3 style="margin-top:32px;">Delivery notes <span style="font-weight:400;color:var(--ink-soft);">(optional)</span></h3>
        <div class="form-field">
          <textarea id="notesInput" rows="3" placeholder="e.g. Leave at the door, call on arrival..."></textarea>
        </div>
      </div>

      <div class="summary-card">
        <h3>Order review</h3>
        <div id="reviewLines"></div>
        <div id="reviewTotals"></div>
        <button type="button" id="placeOrderBtn" class="btn btn--primary btn--block" style="margin-top:20px;">
          Place order
        </button>
        <p class="summary-note">Tax (${TAX_PERCENT}% GST) is calculated by the server on the post-discount amount.</p>
      </div>
    </div>`;

  renderReview(cart);
  document.getElementById("placeOrderBtn").addEventListener("click", () => submitOrder(identity, cart));
}

function renderReview(cart) {
  const subtotal = cart.reduce((sum, l) => sum + l.unitPrice * l.quantity, 0);
  const tax = subtotal * (TAX_PERCENT / 100);
  const total = subtotal + tax;

  document.getElementById("reviewLines").innerHTML = cart
    .map(
      (l) => `
      <div class="summary-row">
        <span>${l.name} × ${l.quantity}</span>
        <span>${formatMoney(l.unitPrice * l.quantity)}</span>
      </div>`
    )
    .join("");

  document.getElementById("reviewTotals").innerHTML = `
    <div class="summary-row" style="border-top:1px solid var(--paper-line);margin-top:8px;padding-top:12px;">
      <span>Subtotal</span><span>${formatMoney(subtotal)}</span>
    </div>
    <div class="summary-row"><span>GST (${TAX_PERCENT}%)</span><span>${formatMoney(tax)}</span></div>
    <div class="summary-row summary-row--total"><span>Total</span><span>${formatMoney(total)}</span></div>`;
}

async function loadAddresses(customerId, preferredAddressId = null) {
  const list = document.getElementById("addressList");
  try {
    const res = await Api.getCustomerAddresses(customerId);
    const items = res.items;
    const showFormByDefault = items.length === 0;

    const listHtml = items.length
      ? items
          .map(
            (a) => `
        <label class="address-option">
          <input type="radio" name="address" value="${a.address_id}"
            ${a.address_id === preferredAddressId || (!preferredAddressId && a.is_default) ? "checked" : ""} />
          <div>
            <div class="address-option__label">${a.label}${a.is_default ? " · Default" : ""}</div>
            <div class="address-option__body">${a.address_line1}${a.address_line2 ? ", " + a.address_line2 : ""}, ${a.city}, ${a.state} ${a.postal_code}, ${a.country}</div>
          </div>
        </label>`
          )
          .join("")
      : `<p style="color:var(--ink-soft);margin-bottom:16px;">No saved addresses yet — add one below to continue.</p>`;

    list.innerHTML = `
      ${listHtml}
      <button type="button" id="toggleAddressFormBtn" class="link-arrow"
        style="margin:8px 0 16px;display:${showFormByDefault ? "none" : "inline-block"};">
        + Add a new address
      </button>
      <div id="newAddressForm" ${showFormByDefault ? "" : "hidden"}>
        <div id="addressFormBanner" class="banner banner--error" hidden></div>
        <div class="form-field">
          <label for="addrLabel">Label</label>
          <input type="text" id="addrLabel" placeholder="Home" value="Home" />
        </div>
        <div class="form-field">
          <label for="addrLine1">Address line 1</label>
          <input type="text" id="addrLine1" required placeholder="House / flat, street" />
        </div>
        <div class="form-field">
          <label for="addrLine2">Address line 2 <span style="font-weight:400;color:var(--ink-soft);">(optional)</span></label>
          <input type="text" id="addrLine2" placeholder="Landmark, area" />
        </div>
        <div class="form-field">
          <label for="addrCity">City</label>
          <input type="text" id="addrCity" required />
        </div>
        <div class="form-field">
          <label for="addrState">State</label>
          <input type="text" id="addrState" required />
        </div>
        <div class="form-field">
          <label for="addrPostal">Postal code</label>
          <input type="text" id="addrPostal" required />
        </div>
        <button type="button" id="saveAddressBtn" class="btn btn--outline btn--block">Save address</button>
      </div>`;

    const checked = list.querySelector("input[name=address]:checked");
    selectedAddressId = checked ? Number(checked.value) : null;

    list.querySelectorAll("input[name=address]").forEach((input) => {
      input.addEventListener("change", () => {
        selectedAddressId = Number(input.value);
      });
    });

    document.getElementById("toggleAddressFormBtn")?.addEventListener("click", (e) => {
      e.currentTarget.style.display = "none";
      document.getElementById("newAddressForm").hidden = false;
    });

    document.getElementById("saveAddressBtn")?.addEventListener("click", async () => {
      const banner = document.getElementById("addressFormBanner");
      banner.hidden = true;

      const payload = {
        label: document.getElementById("addrLabel").value.trim() || "Home",
        address_line1: document.getElementById("addrLine1").value.trim(),
        address_line2: document.getElementById("addrLine2").value.trim() || null,
        city: document.getElementById("addrCity").value.trim(),
        state: document.getElementById("addrState").value.trim(),
        postal_code: document.getElementById("addrPostal").value.trim(),
        country: "India",
      };

      if (!payload.address_line1 || !payload.city || !payload.state || !payload.postal_code) {
        banner.textContent = "Please fill in address line 1, city, state, and postal code.";
        banner.hidden = false;
        return;
      }

      const saveBtn = document.getElementById("saveAddressBtn");
      saveBtn.disabled = true;
      saveBtn.innerHTML = `<span class="spinner"></span> Saving...`;
      try {
        const newAddress = await Api.createAddress(customerId, payload);
        await loadAddresses(customerId, newAddress.address_id);
        showToast("Address saved");
      } catch (err) {
        banner.textContent =
          err instanceof ApiError ? err.message : "Couldn't save this address. Please try again.";
        banner.hidden = false;
        saveBtn.disabled = false;
        saveBtn.textContent = "Save address";
      }
    });
  } catch (err) {
    list.innerHTML = `<p style="color:var(--danger);">Couldn't load addresses. Is the API running at ${API_BASE_URL}?</p>`;
  }
}

async function submitOrder(identity, cart) {
  const banner = document.getElementById("checkoutBanner");
  const btn = document.getElementById("placeOrderBtn");
  banner.hidden = true;

  if (!selectedAddressId) {
    banner.textContent = "Please select a delivery address.";
    banner.hidden = false;
    return;
  }

  const payload = {
    customer_id: identity.customerId,
    address_id: selectedAddressId,
    items: cart.map((l) => ({
      product_id: l.productId,
      quantity: l.quantity,
      item_discount_amount: 0,
      item_discount_percent: 0,
    })),
    discount_amount: 0,
    discount_percent: 0,
    tax_percent: TAX_PERCENT,
    notes: document.getElementById("notesInput").value.trim() || null,
  };

  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span> Placing order...`;

  try {
    const order = await Api.createOrder(payload);
    Store.clearCart();
    window.location.href = `order-confirmation.html?id=${order.order_id}`;
  } catch (err) {
    banner.textContent =
      err instanceof ApiError
        ? err.message
        : "Something went wrong placing your order. Please try again.";
    banner.hidden = false;
    btn.disabled = false;
    btn.textContent = "Place order";
  }
}
