/**
 * js/products.js
 * ===============
 * products.html only. Loads category tabs, then products (optionally
 * filtered by category), and wires up "Add to cart" on each card.
 *
 * Honors a ?category=<name> query param (used by the home page's category
 * strip links) by pre-selecting that tab on load.
 */

let allCategories = [];

document.addEventListener("DOMContentLoaded", async () => {
  await loadCategoryTabs();
  const params = new URLSearchParams(window.location.search);
  const requestedCategory = params.get("category");

  if (requestedCategory) {
    const match = allCategories.find(
      (c) => c.name.toLowerCase() === requestedCategory.toLowerCase()
    );
    if (match) {
      selectTab(match.category_id);
      return;
    }
  }
  loadProducts(); // no filter
});

async function loadCategoryTabs() {
  const tabsContainer = document.getElementById("filterTabs");
  try {
    const res = await Api.getCategories();
    allCategories = res.items;
    const tabsHtml = res.items
      .map(
        (c) =>
          `<button type="button" class="filter-tab" data-category-id="${c.category_id}">
            ${iconFor(c.name)} ${c.name}
          </button>`
      )
      .join("");
    tabsContainer.insertAdjacentHTML("beforeend", tabsHtml);
  } catch (err) {
    console.warn("Could not load categories for filter tabs.", err);
  }

  tabsContainer.addEventListener("click", (e) => {
    const btn = e.target.closest(".filter-tab");
    if (!btn) return;
    const categoryId = btn.getAttribute("data-category-id");
    selectTab(categoryId || null);
  });
}

function selectTab(categoryId) {
  document.querySelectorAll(".filter-tab").forEach((tab) => {
    const isMatch = categoryId
      ? tab.getAttribute("data-category-id") === String(categoryId)
      : tab.getAttribute("data-category-id") === "";
    tab.classList.toggle("is-active", isMatch);
  });
  loadProducts(categoryId || null);
}

async function loadProducts(categoryId = null) {
  const grid = document.getElementById("productGrid");
  grid.innerHTML = `
    <div class="skeleton" style="height:280px;"></div>
    <div class="skeleton" style="height:280px;"></div>
    <div class="skeleton" style="height:280px;"></div>`;

  try {
    const res = await Api.getProducts({ categoryId, pageSize: 100 });
    if (!res.items.length) {
      grid.innerHTML = `
        <div class="empty-state" style="grid-column:1/-1;">
          <div class="empty-state__icon">🍞</div>
          <p>No products found in this category yet.</p>
        </div>`;
      return;
    }
    grid.innerHTML = res.items.map(renderProductCard).join("");
    attachAddToCartHandlers(grid);
  } catch (err) {
    grid.innerHTML = `
      <div class="empty-state" style="grid-column:1/-1;">
        <p style="color:var(--danger);">Couldn't load products. Is the API running at ${API_BASE_URL}?</p>
      </div>`;
  }
}
