/**
 * js/main.js
 * ===========
 * Home page (index.html) only. Populates the category strip and the
 * "Popular products" grid from the live API. Falls back to the static
 * markup already in the HTML if the API is unreachable.
 *
 * Depends on: api.js, state.js, ui.js (renderProductCard / attachAddToCartHandlers)
 */

document.addEventListener("DOMContentLoaded", () => {
  loadCategories();
  loadPopularProducts();
});

async function loadCategories() {
  const strip = document.getElementById("categoryStrip");
  if (!strip) return;

  try {
    const res = await Api.getCategories();
    if (!res.items.length) return; // keep static fallback
    strip.innerHTML = res.items
      .map(
        (c) => `
        <a href="products.html?category=${encodeURIComponent(c.name)}" class="category-tag">
          <div class="category-tag__icon">${iconFor(c.name)}</div>
          <div class="category-tag__name">${c.name}</div>
        </a>`
      )
      .join("");
  } catch (err) {
    console.warn("Could not load categories, showing fallback.", err);
  }
}

async function loadPopularProducts() {
  const grid = document.getElementById("popularProducts");
  if (!grid) return;

  try {
    const res = await Api.getProducts({ pageSize: 8 });
    if (!res.items.length) {
      grid.innerHTML = `<p>No products available yet — check back soon.</p>`;
      return;
    }
    grid.innerHTML = res.items.map(renderProductCard).join("");
    attachAddToCartHandlers(grid);
  } catch (err) {
    grid.innerHTML = `<p style="color:var(--danger);">
      Couldn't load products. Is the API running at ${API_BASE_URL}?
    </p>`;
  }
}
