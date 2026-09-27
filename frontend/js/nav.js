/**
 * js/nav.js
 * ==========
 * Behavior shared by every page's header and footer:
 *   - mobile nav toggle
 *   - cart badge count (kept in sync with Store)
 *   - login: an email + OTP flow against POST /auth/request-otp and
 *     POST /auth/verify-otp. Clicking the chip while logged in logs out.
 *   - a small toast helper used for "Added to cart" / login feedback
 *
 * Expects this markup to exist on the page (see partials in each HTML file):
 *   #navToggle, #mainNav, #cartCount, #identityChip, #identityLabel,
 *   #identityModal, #identityClose, #loginBanner, #requestOtpForm,
 *   #verifyOtpForm, #toast
 */

document.addEventListener("DOMContentLoaded", () => {
  initMobileNav();
  initCartBadge();
  initLoginWidget();
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

function initLoginWidget() {
  const chip = document.getElementById("identityChip");
  const label = document.getElementById("identityLabel");
  const modal = document.getElementById("identityModal");
  const closeBtn = document.getElementById("identityClose");
  if (!chip || !label) return;

  const renderChip = () => {
    const identity = Store.getIdentity();
    label.textContent = identity ? `Hi, ${identity.firstName}` : "Log in";
  };
  renderChip();
  document.addEventListener("identity:changed", renderChip);

  // Any page can trigger the login modal without a logged-in user by
  // dispatching this event (see checkout.js / orders.js).
  document.addEventListener("identity:required", () => openModal());

  if (!modal) return; // some future page might show only the chip

  const banner = document.getElementById("loginBanner");
  const requestForm = document.getElementById("requestOtpForm");
  const verifyForm = document.getElementById("verifyOtpForm");
  const nameFields = document.getElementById("signupNameFields");
  const otpEmailLabel = document.getElementById("otpEmailLabel");
  const backBtn = document.getElementById("backToEmailBtn");

  const showBanner = (message) => {
    if (!banner) return;
    banner.textContent = message;
    banner.hidden = false;
  };
  const hideBanner = () => banner && (banner.hidden = true);

  const resetToStep1 = () => {
    hideBanner();
    nameFields.hidden = true;
    requestForm.hidden = false;
    verifyForm.hidden = true;
    requestForm.reset();
    verifyForm.reset();
  };

  const openModal = () => {
    resetToStep1();
    modal.hidden = false;
    document.getElementById("loginEmail")?.focus();
  };

  chip.addEventListener("click", () => {
    const identity = Store.getIdentity();
    if (identity) {
      Store.logout();
      showToast("Logged out");
    } else {
      openModal();
    }
  });
  closeBtn?.addEventListener("click", () => (modal.hidden = true));
  modal.addEventListener("click", (e) => {
    if (e.target === modal) modal.hidden = true;
  });

  requestForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    hideBanner();
    const email = document.getElementById("loginEmail").value.trim();
    const firstName = document.getElementById("loginFirstName")?.value.trim();
    const lastName = document.getElementById("loginLastName")?.value.trim();
    const submitBtn = document.getElementById("sendCodeBtn");

    submitBtn.disabled = true;
    submitBtn.innerHTML = `<span class="spinner"></span> Sending...`;
    try {
      const res = await Api.requestOtp({ email, first_name: firstName, last_name: lastName });
      otpEmailLabel.textContent = email;
      requestForm.hidden = true;
      verifyForm.hidden = false;
      verifyForm.dataset.email = email;
      if (res.dev_otp_code) {
        document.getElementById("loginOtpCode").value = res.dev_otp_code;
        showToast(`Dev mode: code is ${res.dev_otp_code}`);
      }
      document.getElementById("loginOtpCode")?.focus();
    } catch (err) {
      if (err instanceof ApiError && err.errorCode === "NAME_REQUIRED_FOR_SIGNUP") {
        nameFields.hidden = false;
        showBanner("New here? Add your name so we can create your account.");
      } else {
        showBanner(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      }
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Send code";
    }
  });

  verifyForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    hideBanner();
    const email = verifyForm.dataset.email;
    const code = document.getElementById("loginOtpCode").value.trim();
    const submitBtn = document.getElementById("verifyCodeBtn");

    submitBtn.disabled = true;
    submitBtn.innerHTML = `<span class="spinner"></span> Verifying...`;
    try {
      const res = await Api.verifyOtp({ email, code });
      Store.setSession(res);
      modal.hidden = true;
      showToast(`Welcome, ${res.customer.first_name}!`);
      document.dispatchEvent(new CustomEvent("identity:loggedIn", { detail: res.customer }));
    } catch (err) {
      showBanner(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Verify & log in";
    }
  });

  backBtn?.addEventListener("click", () => resetToStep1());
}

function showToast(message) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("is-visible");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => toast.classList.remove("is-visible"), 2400);
}

/** Require a logged-in identity before proceeding (checkout / order history). */
function requireIdentity() {
  const identity = Store.getIdentity();
  if (!identity) {
    document.dispatchEvent(new CustomEvent("identity:required"));
    return null;
  }
  return identity;
}
