/**
 * js/state.js
 * ============
 * localStorage-backed state: the shopping cart and the "ordering as"
 * identity (this demo has no auth — see nav.js for the picker UI).
 *
 * Cart shape: array of { productId, name, categoryName, unitPrice, quantity }
 * Identity shape: { customerId, firstName, lastName }
 */

const CART_KEY = "meera_cart_v1";
const IDENTITY_KEY = "meera_identity_v1";

const Store = {
  // ---- Cart ----
  getCart() {
    try {
      return JSON.parse(localStorage.getItem(CART_KEY)) || [];
    } catch (_) {
      return [];
    }
  },

  saveCart(cart) {
    localStorage.setItem(CART_KEY, JSON.stringify(cart));
    document.dispatchEvent(new CustomEvent("cart:changed", { detail: cart }));
  },

  addToCart(product, quantity = 1) {
    const cart = Store.getCart();
    const existing = cart.find((line) => line.productId === product.product_id);
    if (existing) {
      existing.quantity += quantity;
    } else {
      cart.push({
        productId: product.product_id,
        name: product.name,
        categoryName: product.category_name,
        unitPrice: product.unit_price,
        quantity,
      });
    }
    Store.saveCart(cart);
  },

  updateQuantity(productId, quantity) {
    let cart = Store.getCart();
    if (quantity <= 0) {
      cart = cart.filter((line) => line.productId !== productId);
    } else {
      const line = cart.find((l) => l.productId === productId);
      if (line) line.quantity = quantity;
    }
    Store.saveCart(cart);
  },

  removeFromCart(productId) {
    const cart = Store.getCart().filter((l) => l.productId !== productId);
    Store.saveCart(cart);
  },

  clearCart() {
    Store.saveCart([]);
  },

  cartCount() {
    return Store.getCart().reduce((sum, l) => sum + l.quantity, 0);
  },

  cartSubtotal() {
    return Store.getCart().reduce((sum, l) => sum + l.unitPrice * l.quantity, 0);
  },

  // ---- Identity ("ordering as") ----
  getIdentity() {
    try {
      return JSON.parse(localStorage.getItem(IDENTITY_KEY));
    } catch (_) {
      return null;
    }
  },

  setIdentity(customer) {
    const identity = {
      customerId: customer.customer_id,
      firstName: customer.first_name,
      lastName: customer.last_name,
    };
    localStorage.setItem(IDENTITY_KEY, JSON.stringify(identity));
    document.dispatchEvent(new CustomEvent("identity:changed", { detail: identity }));
    return identity;
  },

  clearIdentity() {
    localStorage.removeItem(IDENTITY_KEY);
    document.dispatchEvent(new CustomEvent("identity:changed", { detail: null }));
  },
};
