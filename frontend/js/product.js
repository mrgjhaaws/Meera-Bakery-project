/**
 * js/product.js
 * ==============
 * product.html only. Reads ?id=<product_id> from the URL, fetches full
 * product detail (with inventory), and renders the detail layout.
 */

document.addEventListener("DOMContentLoaded", loadProduct);

async function loadProduct() {
  const params = new URLSearchParams(window.location.search);
  const productId = params.get("id");
  const container = document.getElementById("productDetail");

  if (!productId) {
    container.innerHTML = notFoundMarkup("No product was specified.");
    return;
  }

  try {
    const product = await Api.getProduct(productId);
    document.title = `${product.name} — Meera Bakery Online`;
    container.innerHTML = renderDetail(product);
    wireInteractions(product);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      container.innerHTML = notFoundMarkup("We couldn't find that product — it may have been removed.");
    } else {
      container.innerHTML = notFoundMarkup(`Couldn't load this product. Is the API running at ${API_BASE_URL}?`);
    }
  }
}

function notFoundMarkup(message) {
  return `
    <div class="empty-state">
      <div class="empty-state__icon">🥐</div>
      <p>${message}</p>
      <a href="products.html" class="btn btn--primary">Back to products</a>
    </div>`;
}

function stockLine(inventory) {
  if (!inventory) return "";
  const { quantity_on_hand } = inventory;
  if (quantity_on_hand === 0) {
    return `<div class="stock-line"><span class="dot dot--out"></span> Currently sold out</div>`;
  }
  if (quantity_on_hand <= inventory.reorder_level) {
    return `<div class="stock-line"><span class="dot dot--low"></span> Only ${quantity_on_hand} left — order soon</div>`;
  }
  return `<div class="stock-line"><span class="dot"></span> In stock</div>`;
}

function renderDetail(product) {
  const maxQty = product.inventory ? Math.max(product.inventory.quantity_on_hand, 0) : 99;
  const soldOut = product.inventory && product.inventory.quantity_on_hand === 0;

  return `
    <div class="detail-grid">
      <div class="detail-media">${iconFor(product.category_name)}</div>
      <div>
        <div class="detail-category">${product.category_name}</div>
        <h1>${product.name}</h1>
        <div class="detail-price">${formatMoney(product.unit_price)} <span style="font-size:0.9rem;color:var(--ink-soft);font-family:var(--font-body);">/ unit</span></div>
        ${stockLine(product.inventory)}
        <p>${product.description || "A bakery favorite, made fresh daily."}</p>

        <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin-top:24px;">
          <div class="qty-stepper">
            <button type="button" id="qtyMinus" aria-label="Decrease quantity">−</button>
            <input type="number" id="qtyInput" value="1" min="1" max="${maxQty || 1}" aria-label="Quantity" />
            <button type="button" id="qtyPlus" aria-label="Increase quantity">+</button>
          </div>
          <button type="button" id="addToCartBtn" class="btn btn--primary" ${soldOut ? "disabled" : ""}>
            ${soldOut ? "Sold out" : "Add to cart"}
          </button>
        </div>
      </div>
    </div>`;
}

function wireInteractions(product) {
  const qtyInput = document.getElementById("qtyInput");
  const minus = document.getElementById("qtyMinus");
  const plus = document.getElementById("qtyPlus");
  const addBtn = document.getElementById("addToCartBtn");
  const maxQty = product.inventory ? product.inventory.quantity_on_hand : 99;

  minus.addEventListener("click", () => {
    qtyInput.value = Math.max(1, Number(qtyInput.value) - 1);
  });
  plus.addEventListener("click", () => {
    qtyInput.value = Math.min(maxQty || 99, Number(qtyInput.value) + 1);
  });
  qtyInput.addEventListener("change", () => {
    let v = Number(qtyInput.value) || 1;
    v = Math.max(1, Math.min(maxQty || 99, v));
    qtyInput.value = v;
  });

  addBtn?.addEventListener("click", () => {
    const quantity = Number(qtyInput.value) || 1;
    Store.addToCart(product, quantity);
    showToast(`Added ${quantity} × ${product.name} to cart`);
  });
}
