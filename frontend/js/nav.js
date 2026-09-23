/**
 * js/nav.js
 * ==========
 * Behavior shared by every page's header and footer:
 *   - mobile nav toggle
 *   - cart badge count (kept in sync with Store)
 *   - "Ordering as" identity chip + picker modal (no auth in this demo —
 *     picking a customer simulates being logged in as them)
 *   - a small toast helper used for "Added to cart" feedback
 *
 * Expects this markup to exist on the page (see partials in each HTML file):
 *   #navToggle, #mainNav, #cartCount, #identityChip, #identityLabel,
 *   #identityModal, #identityList, #identityClose, #toast
 */

document.addEventListener("DOMContentLoaded", () => {
  initMobileNav();
  initCartBadge();
  initIdentityWidget();
});

function initMobileNav() {
  const toggle = document.getElementById("navToggle");
  const nav = document.getElementById("mainNav");
  if (!toggle || !nav) return;

  toggle.addEventListener("click", () => {
    nav.classList.toggle("is-open");
  });

  // Mark the current page's nav link active
  const current = window.location.pathname.split("/").pop() || "index.html";
  nav.querySelectorAll("a[data-nav]").forEach((link) => {
    if (link.getAttribute("data-nav") === current) {
      link.classList.add("is-active");
    }
  });
}

function initCartBadge() {
  const badge = document.getElementById("cartCount");
  if (!badge) return;

  const render = () => {
    const count = Store.cartCount();
    badge.textContent = count;
    badge.hidden = count === 0;
  };

  render();
  document.addEventListener("cart:changed", render);
}

function initIdentityWidget() {
  const chip = document.getElementById("identityChip");
  const label = document.getElementById("identityLabel");
  const modal = document.getElementById("identityModal");
  const list = document.getElementById("identityList");
  const closeBtn = document.getElementById("identityClose");
  if (!chip || !label) return;

  const renderChip = () => {
    const identity = Store.getIdentity();
    label.textContent = identity
      ? `Ordering as ${identity.firstName}`
      : "Choose your name";
  };

  renderChip();
  document.addEventListener("identity:changed", renderChip);

  if (!modal || !list) return; // some pages may only show the chip, no picker

  const openModal = async () => {
    modal.hidden = false;
    list.innerHTML = `<li class="skeleton" style="height:48px;margin-bottom:8px;"></li>`.repeat(4);
    try {
      const res = await Api.getCustomers({ pageSize: 50 });
      renderIdentityList(res.items);
    } catch (err) {
      list.innerHTML = `<li style="color:var(--danger);padding:12px;">
        Couldn't load customers. Is the API running at ${API_BASE_URL}?
      </li>`;
    }
  };

  const renderIdentityList = (customers) => {
    if (!customers.length) {
      list.innerHTML = `<li style="padding:12px;color:var(--ink-soft);">No customers found.</li>`;
      return;
    }
    list.innerHTML = customers
      .map(
        (c) => `
        <li>
          <button type="button" class="identity-option" data-customer='${JSON.stringify(c).replace(/'/g, "&apos;")}'>
            <span class="identity-chip__avatar">${c.first_name[0]}${c.last_name[0]}</span>
            <span>
              <strong>${c.first_name} ${c.last_name}</strong>
              <br><small>${c.email}</small>
            </span>
          </button>
        </li>`
      )
      .join("");

    list.querySelectorAll(".identity-option").forEach((btn) => {
      btn.addEventListener("click", () => {
        const customer = JSON.parse(btn.getAttribute("data-customer"));
        Store.setIdentity(customer);
        modal.hidden = true;
        showToast(`Ordering as ${customer.first_name} ${customer.last_name}`);
      });
    });
  };

  chip.addEventListener("click", openModal);
  closeBtn?.addEventListener("click", () => (modal.hidden = true));
  modal.addEventListener("click", (e) => {
    if (e.target === modal) modal.hidden = true;
  });
}

function showToast(message) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("is-visible");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => toast.classList.remove("is-visible"), 2400);
}

/** Require an identity before proceeding (checkout / order history pages). */
function requireIdentity(redirectTo) {
  const identity = Store.getIdentity();
  if (!identity) {
    document.dispatchEvent(new CustomEvent("identity:required"));
    return null;
  }
  return identity;
}
