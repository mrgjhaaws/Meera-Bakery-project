/**
 * js/ui.js
 * =========
 * Rendering helpers shared by the home page and the product catalog page.
 * Kept separate from main.js/products.js so the markup for a product card
 * only lives in one place.
 */

function stockBadge(inventory) {
  if (!inventory) return "";
  if (inventory.quantity_on_hand === 0) {
    return `<span class="product-card__tag product-card__tag--low">Sold out</span>`;
  }
  if (inventory.quantity_on_hand <= inventory.reorder_level) {
    return `<span class="product-card__tag product-card__tag--low">Low stock</span>`;
  }
  return "";
}

function renderProductCard(product) {
  return `
    <div class="product-card">
      <a href="product.html?id=${product.product_id}" class="product-card__media">
        ${iconFor(product.category_name)}
        ${stockBadge(product.inventory)}
      </a>
      <div class="product-card__body">
        <span class="product-card__category">${product.category_name}</span>
        <a href="product.html?id=${product.product_id}" class="product-card__name">${product.name}</a>
        <div class="product-card__row">
          <div class="product-card__price">${formatMoney(product.unit_price)} <span>/ unit</span></div>
          <button
            type="button"
            class="icon-btn add-to-cart-btn"
            data-product='${JSON.stringify(product).replace(/'/g, "&apos;")}'
            aria-label="Add ${product.name} to cart"
          >+</button>
        </div>
      </div>
    </div>`;
}

function attachAddToCartHandlers(scope) {
  scope.querySelectorAll(".add-to-cart-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      const product = JSON.parse(btn.getAttribute("data-product"));
      Store.addToCart(product, 1);
      showToast(`Added ${product.name} to cart`);
    });
  });
}
