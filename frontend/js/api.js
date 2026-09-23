/**
 * js/api.js
 * ==========
 * Thin fetch wrapper around the Meera Bakery FastAPI backend.
 *
 * IMPORTANT: this frontend must be served over HTTP (not opened as a
 * file:// URL) for CORS to work — e.g. from the frontend/ folder run:
 *     python -m http.server 3000
 * then visit http://localhost:3000. The backend's allowed_origins
 * (see app/config.py / .env) must include that origin.
 */

const API_BASE_URL = "http://localhost:8000/api/v1";

class ApiError extends Error {
  constructor(status, body) {
    super(body?.message || `Request failed with status ${status}`);
    this.status = status;
    this.errorCode = body?.error || null;
    this.detail = body?.detail || null;
  }
}

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  let body = null;
  try {
    body = await res.json();
  } catch (_) {
    /* no JSON body (e.g. 204) */
  }

  if (!res.ok) {
    throw new ApiError(res.status, body);
  }
  return body;
}

const Api = {
  // ---- Categories ----
  getCategories() {
    return request(`/categories?page_size=50`);
  },

  // ---- Products ----
  getProducts({ categoryId, page = 1, pageSize = 50 } = {}) {
    const params = new URLSearchParams({ page, page_size: pageSize });
    const path = categoryId
      ? `/categories/${categoryId}/products?${params}`
      : `/products?${params}`;
    return request(path);
  },
  getProduct(productId) {
    return request(`/products/${productId}?include_inventory=true`);
  },

  // ---- Customers ----
  getCustomers({ page = 1, pageSize = 50 } = {}) {
    const params = new URLSearchParams({ page, page_size: pageSize });
    return request(`/customers?${params}`);
  },
  getCustomer(customerId) {
    return request(`/customers/${customerId}`);
  },

  // ---- Addresses ----
  getCustomerAddresses(customerId) {
    return request(`/customers/${customerId}/addresses?page_size=50`);
  },

  // ---- Orders ----
  createOrder(payload) {
    return request(`/orders`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  getOrder(orderId) {
    return request(`/orders/${orderId}`);
  },
  getCustomerOrders(customerId, { page = 1, pageSize = 20 } = {}) {
    const params = new URLSearchParams({ page, page_size: pageSize });
    return request(`/customers/${customerId}/orders?${params}`);
  },
};

// Emoji fallback per category name — used everywhere a product image would
// normally go, since this learning project has no product photography.
const CATEGORY_ICONS = {
  Bread: "🍞",
  Cake: "🎂",
  Pastry: "🥐",
  Cookie: "🍪",
  Beverage: "☕",
  Other: "🧁",
};

function iconFor(categoryName) {
  return CATEGORY_ICONS[categoryName] || "🧁";
}

function formatMoney(value) {
  return `₹${Number(value).toFixed(2)}`;
}
