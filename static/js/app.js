// Cart (localStorage), drawers and share button. Cart logic is the original storefront's,
// adapted so each line stores its own product details (products now come from the database).
const CART_KEY = "marketplace-cart";
const symbol = document.body.dataset.currency || "$";

const money = (n) =>
  symbol + Number(n).toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 2 });

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = { lines: load(), done: false, payment: loadPayment() };
let paymentPolling = false;

function load() {
  try {
    const data = JSON.parse(localStorage.getItem(CART_KEY) || "[]");
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}
function save() {
  try { localStorage.setItem(CART_KEY, JSON.stringify(state.lines)); } catch {}
}
function loadPayment() {
  try {
    const payment = JSON.parse(sessionStorage.getItem("marketplace-payment") || "null");
    return payment && payment.checkout_id ? payment : null;
  } catch {
    return null;
  }
}
function savePayment() {
  try {
    if (state.payment) sessionStorage.setItem("marketplace-payment", JSON.stringify(state.payment));
    else sessionStorage.removeItem("marketplace-payment");
  } catch {}
}
const count = () => state.lines.reduce((n, l) => n + l.qty, 0);

function add(item, quantity = 1) {
  quantity = Math.max(1, Math.floor(Number(quantity) || 1));
  const line = state.lines.find((l) => l.id === item.id);
  if (line) line.qty += quantity;
  else state.lines.push({ ...item, qty: quantity });
  state.done = false;
  save();
  paintCount();
  paintCartPage();
  openCart();
}

function setQty(id, qty) {
  if (qty < 1) state.lines = state.lines.filter((l) => l.id !== id);
  else state.lines = state.lines.map((l) => (l.id === id ? { ...l, qty } : l));
  save();
  paintCount();
  paintCart();
  paintCartPage();
}

const menu = document.querySelector("[data-menu]");
const cart = document.querySelector("[data-cart]");
const menuTrigger = document.querySelector("[data-open-menu]");
const cartTrigger = document.querySelector("[data-open-cart]");
const drawerMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

function lock() {
  document.body.style.overflow =
    !menu.classList.contains("hidden") || !cart.classList.contains("hidden") ? "hidden" : "";
}
function showDrawer(overlay, trigger) {
  overlay.classList.remove("hidden");
  overlay.setAttribute("aria-hidden", "false");
  trigger.setAttribute("aria-expanded", "true");
  requestAnimationFrame(() => overlay.classList.add("is-open"));
  lock();
  overlay.querySelector(".drawer-head [data-close-menu], .drawer-head [data-close-cart]")?.focus();
}
function hideDrawer(overlay, trigger) {
  if (overlay.classList.contains("hidden")) return;
  overlay.classList.remove("is-open");
  overlay.setAttribute("aria-hidden", "true");
  trigger.setAttribute("aria-expanded", "false");
  const finishClose = () => {
    if (overlay.classList.contains("is-open")) return;
    overlay.classList.add("hidden");
    lock();
    trigger.focus();
  };
  if (drawerMotion.matches) finishClose();
  else window.setTimeout(finishClose, 280);
}
function openMenu() { showDrawer(menu, menuTrigger); }
function closeMenu() { hideDrawer(menu, menuTrigger); }
function openCart() { paintCart(); showDrawer(cart, cartTrigger); }
function closeCart() { hideDrawer(cart, cartTrigger); }

menuTrigger.onclick = openMenu;
cartTrigger.onclick = openCart;
document.querySelectorAll("[data-close-menu]").forEach((el) => (el.onclick = closeMenu));
document.querySelectorAll("[data-close-cart]").forEach((el) => (el.onclick = closeCart));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { closeMenu(); closeCart(); }
});

function paintCount() {
  const badge = document.querySelector("[data-count]");
  const label = document.querySelector("[data-cart-label]");
  const n = count();
  badge.textContent = String(n);
  badge.classList.toggle("hidden", n === 0);
  if (label) label.textContent = `${n} ${n === 1 ? "item" : "items"}`;
}

function paintCart() {
  const body = document.querySelector("[data-cart-body]");
  const lines = state.lines;

  if (!lines.length && !state.done) {
    body.innerHTML = `<div class="empty">
      <span class="empty-bag-icon" aria-hidden="true"><svg viewBox="0 0 48 48" fill="none"><path d="M10 17h28l2 25H8l2-25Z" stroke="currentColor" stroke-width="1.7"/><path d="M17 19v-5a7 7 0 0 1 14 0v5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg></span>
      <p>Your bag is taking a breather.</p>
      <span>Find something useful, beautiful, or both. Your picks will stay here while you browse.</span>
      <a class="btn" href="${esc(document.body.dataset.browseUrl)}">Explore the shop</a>
      <button class="cart-continue" type="button" data-close-cart>Continue browsing</button>
    </div>`;
    body.querySelector("[data-close-cart]").onclick = closeCart;
    return;
  }
  if (state.done) {
    body.innerHTML = `<div class="done">
      <span class="done-mark" aria-hidden="true">✓</span>
      <p>Payment received</p>
      <span>Your order payment was confirmed by M-Pesa.</span>
      <a class="btn" href="${esc(document.body.dataset.browseUrl)}" data-back>Back to the shop</a>
    </div>`;
    body.querySelector("[data-back]").onclick = () => { state.done = false; };
    return;
  }
  const total = lines.reduce((n, l) => n + l.price * l.qty, 0);
  body.innerHTML = `
    <ul class="lines">
      ${lines.map((l) => `<li class="line">
        <img src="${esc(l.image)}" alt="" />
        <div class="line-info">
          <div class="line-top"><p>${esc(l.name)}</p><button class="remove-line" type="button" aria-label="Remove ${esc(l.name)}" data-remove="${esc(l.id)}">Remove</button></div>
          <p class="muted">${money(l.price)} each</p>
          <div class="qty">
            <button type="button" aria-label="Decrease quantity of ${esc(l.name)}" data-dec="${esc(l.id)}">−</button>
            <span aria-live="polite">${l.qty}</span>
            <button type="button" aria-label="Increase quantity of ${esc(l.name)}" data-inc="${esc(l.id)}">+</button>
          </div>
          <p class="line-total">${money(l.price * l.qty)}</p>
        </div>
      </li>`).join("")}
    </ul>
    <div class="checkout">
      <p class="delivery-caption">Delivery details are agreed with each seller.</p>
      <div class="subtotal"><span class="muted">Subtotal</span><strong>${money(total)}</strong></div>
      <a class="btn" href="${esc(document.body.dataset.cartUrl)}">Continue to checkout</a>
    </div>`;
  const qtyOf = (id) => state.lines.find((l) => l.id === id).qty;
  body.querySelectorAll("[data-remove]").forEach((b) => (b.onclick = () => setQty(b.dataset.remove, 0)));
  body.querySelectorAll("[data-dec]").forEach((b) => (b.onclick = () => setQty(b.dataset.dec, qtyOf(b.dataset.dec) - 1)));
  body.querySelectorAll("[data-inc]").forEach((b) => (b.onclick = () => setQty(b.dataset.inc, qtyOf(b.dataset.inc) + 1)));
}

function paintCartPage() {
  const page = document.querySelector("[data-cart-page]");
  if (!page) return;

  if (!state.lines.length && !state.done && !(state.payment && state.payment.status === "pending")) {
    page.innerHTML = `<div class="cart-empty">
      <span class="cart-empty-icon" aria-hidden="true"><svg viewBox="0 0 48 48" fill="none"><path d="M10 17h28l2 25H8l2-25Z" stroke="currentColor" stroke-width="1.7"/><path d="M17 19v-5a7 7 0 0 1 14 0v5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg></span>
      <p class="cart-empty-title">Your cart is empty</p>
      <p class="cart-empty-copy">Take a look around and add something you love. Your items will be waiting here.</p>
      <a class="btn" href="${esc(document.body.dataset.browseUrl)}">Browse products</a>
      <a class="cart-empty-secondary" href="/">Back to marketplace</a>
    </div>`;
    return;
  }
  if (state.done) {
    page.innerHTML = `<div class="cart-empty">
      <span class="done-mark" aria-hidden="true">✓</span>
      <p class="cart-empty-title">Payment received</p>
      <p class="cart-empty-copy">M-Pesa confirmed your payment. Thank you for your order.</p>
      <a class="btn" href="${esc(document.body.dataset.browseUrl)}">Continue shopping</a>
    </div>`;
    return;
  }

  const total = state.lines.reduce((sum, line) => sum + line.price * line.qty, 0);
  const authenticated = document.body.dataset.authenticated === "true";
  const pending = state.payment && state.payment.status === "pending";
  const failed = state.payment && ["failed", "cancelled"].includes(state.payment.status);
  page.innerHTML = `
    <div class="cart-page-layout">
      <section class="cart-page-items" aria-label="Cart items">
        <ul class="cart-page-lines">
          ${state.lines.map((line) => `<li class="line">
            <img src="${esc(line.image)}" alt="" />
            <div class="line-info">
              <div class="line-top"><p>${esc(line.name)}</p><button type="button" aria-label="Remove ${esc(line.name)}" data-remove="${esc(line.id)}">Remove</button></div>
              <p class="muted">${money(line.price)} each</p>
              <div class="qty">
                <button type="button" aria-label="Decrease quantity" data-dec="${esc(line.id)}">−</button>
                <span>${line.qty}</span>
                <button type="button" aria-label="Increase quantity" data-inc="${esc(line.id)}">+</button>
              </div>
              <p class="line-total">${money(line.price * line.qty)}</p>
            </div>
          </li>`).join("")}
        </ul>
      </section>
      <aside class="cart-summary">
        <h2>Order summary</h2>
        <div class="subtotal"><span>Subtotal</span><strong>${money(total)}</strong></div>
        <p>Delivery details are agreed with each seller.</p>
        ${pending && authenticated ? `
          <div class="payment-message" role="status" data-payment-status>Waiting for M-Pesa confirmation…</div>
          <small>Amount: ${money(state.payment.amount)} · Prompt reference: ${esc(state.payment.reference)}</small>
          <div class="payment-actions">
            <button type="button" class="btn btn-outline" data-query-payment>Check M-Pesa now</button>
            <a class="cart-full-link" href="${esc(document.body.dataset.browseUrl)}">Continue shopping</a>
          </div>
          <small>M-Pesa has not confirmed whether this payment completed. Don’t start another payment until this one is confirmed failed or canceled.</small>
        ` : pending ? `
          <div class="payment-message" role="status">Sign in to check the status of your pending payment.</div>
          <a class="btn" href="${esc(document.body.dataset.loginUrl)}">Sign in to continue</a>
        ` : `
          ${failed ? `<div class="payment-message payment-error" role="status">${state.payment.status === "cancelled" ? "You canceled the M-Pesa prompt. No payment was completed." : `Payment failed: ${esc(state.payment.message || "The payment was not completed.")}`}</div>` : ""}
          ${authenticated ? `
          <form class="checkout-form" data-checkout-form>
            <label for="checkout-phone">M-Pesa phone number</label>
            <input id="checkout-phone" name="phone" type="tel" autocomplete="tel" placeholder="0712345678" required />
            <button class="btn" type="submit">Pay with M-Pesa</button>
            <small>You’ll receive a payment prompt on your phone. The final amount is checked against current product prices.</small>
          </form>
          ` : `
          <div class="checkout-signin">
            <p>Sign in or create an account to place your order and track its payment.</p>
            <a class="btn" href="${esc(document.body.dataset.loginUrl)}">Sign in to checkout</a>
            <a class="cart-full-link" href="${esc(document.body.dataset.signupUrl)}">Create an account</a>
          </div>
          `}
        `}
        <div class="payment-message" role="status" data-checkout-status></div>
      </aside>
    </div>`;

  const qtyOf = (id) => state.lines.find((line) => line.id === id).qty;
  page.querySelectorAll("[data-remove]").forEach((button) => (button.onclick = () => setQty(button.dataset.remove, 0)));
  page.querySelectorAll("[data-dec]").forEach((button) => (button.onclick = () => setQty(button.dataset.dec, qtyOf(button.dataset.dec) - 1)));
  page.querySelectorAll("[data-inc]").forEach((button) => (button.onclick = () => setQty(button.dataset.inc, qtyOf(button.dataset.inc) + 1)));
  const form = page.querySelector("[data-checkout-form]");
  if (form) form.addEventListener("submit", startCheckout);
  const queryButton = page.querySelector("[data-query-payment]");
  if (queryButton) queryButton.addEventListener("click", queryPayment);
}

async function startCheckout(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const status = document.querySelector("[data-checkout-status]");
  const cents = state.lines.reduce((sum, line) => sum + Math.round(Number(line.price) * 100) * line.qty, 0);
  button.disabled = true;
  status.textContent = "Checking your cart and contacting M-Pesa…";

  try {
    const response = await fetch(document.body.dataset.checkoutUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": document.body.dataset.csrfToken,
      },
      body: JSON.stringify({
        phone: form.elements.phone.value,
        expected_total: (cents / 100).toFixed(2),
        items: state.lines.map((line) => ({ id: Number(line.id), qty: line.qty })),
      }),
    });
    const data = await response.json();
    if (response.status === 401) {
      window.location.assign(data.login_url || document.body.dataset.loginUrl);
      return;
    }
    if (response.status === 409 && data.items) {
      const currentLines = new Map(state.lines.map((line) => [String(line.id), line]));
      state.lines = data.items.map((item) => ({
        ...currentLines.get(String(item.id)),
        ...item,
        id: String(item.id),
        price: Number(item.price),
      }));
      save();
      paintCount();
      paintCartPage();
      document.querySelector("[data-checkout-status]").textContent = data.error;
      return;
    }
    if (!response.ok) throw new Error(data.error || "Could not start M-Pesa checkout.");

    state.payment = {
      checkout_id: data.checkout_id,
      reference: data.reference,
      amount: data.amount,
      status: "pending",
      items: state.lines.map((line) => ({ id: String(line.id), qty: line.qty })),
    };
    savePayment();
    paintCartPage();
    pollPayment();
  } catch (error) {
    status.textContent = error.message || "Could not start M-Pesa checkout. Please try again.";
  } finally {
    if (button.isConnected) button.disabled = false;
  }
}

async function pollPayment() {
  if (paymentPolling || !state.payment || state.payment.status !== "pending" ||
      !document.querySelector("[data-payment-status]")) return;
  paymentPolling = true;
  const url = document.body.dataset.paymentStatusUrl.replace(
    "CHECKOUT_ID",
    encodeURIComponent(state.payment.checkout_id),
  );

  for (let attempt = 0; attempt < 10; attempt += 1) {
    if (attempt) await new Promise((resolve) => setTimeout(resolve, 5000));
    if (!document.querySelector("[data-payment-status]") || !state.payment ||
        state.payment.status !== "pending") break;
    try {
      const response = await fetch(url);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not check payment status.");
      if (applyPaymentStatus(data)) break;
    } catch (error) {
      const notice = document.querySelector("[data-payment-status]");
      if (notice) notice.textContent = error.message || "Could not check payment status.";
      break;
    }
  }
  paymentPolling = false;
  const notice = document.querySelector("[data-payment-status]");
  if (notice && state.payment && state.payment.status === "pending") {
    notice.textContent = "Still waiting: M-Pesa has not confirmed success, failure, or cancellation. Use “Check M-Pesa now” or continue shopping.";
  }
}

function applyPaymentStatus(data) {
  if (!state.payment) return true;
  if (data.status === "success") {
    const paid = new Map(state.payment.items.map((item) => [item.id, item.qty]));
    state.lines = state.lines
      .map((line) => ({ ...line, qty: line.qty - (paid.get(String(line.id)) || 0) }))
      .filter((line) => line.qty > 0);
    state.payment = null;
    state.done = state.lines.length === 0;
    savePayment();
    save();
    paintCount();
    paintCart();
    paintCartPage();
    return true;
  }
  if (data.status === "failed" || data.status === "cancelled") {
    state.payment.status = data.status;
    state.payment.message = data.message;
    savePayment();
    paintCartPage();
    return true;
  }
  const notice = document.querySelector("[data-payment-status]");
  if (notice) notice.textContent = data.message || "M-Pesa has not confirmed the payment yet.";
  return false;
}

async function queryPayment(event) {
  const button = event.currentTarget;
  const notice = document.querySelector("[data-payment-status]");
  button.disabled = true;
  if (notice) notice.textContent = "Asking M-Pesa for the latest transaction status…";
  try {
    const url = document.body.dataset.paymentQueryUrl.replace(
      "CHECKOUT_ID",
      encodeURIComponent(state.payment.checkout_id),
    );
    const response = await fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": document.body.dataset.csrfToken },
    });
    const data = await response.json();
    if (!response.ok && response.status !== 502) {
      throw new Error(data.error || data.message || "Could not check this payment.");
    }
    if (applyPaymentStatus(data)) return;
    if (response.status === 502 && notice) notice.textContent = data.message;
  } catch (error) {
    const currentNotice = document.querySelector("[data-payment-status]");
    if (currentNotice) currentNotice.textContent = error.message || "Could not check this payment.";
  } finally {
    if (button.isConnected) button.disabled = false;
  }
}

// "Add to bag" buttons on any page (event delegation).
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-add]");
  if (!btn) return;
  const quantity = btn.closest(".detail-info")?.querySelector("[data-product-quantity]")?.value || 1;
  add({ id: btn.dataset.id, name: btn.dataset.name, price: Number(btn.dataset.price), image: btn.dataset.image }, quantity);
});

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-quantity-decrease], [data-quantity-increase]");
  if (!button) return;
  const input = button.closest(".product-quantity")?.querySelector("[data-product-quantity]");
  if (!input) return;
  const current = Math.max(1, Math.floor(Number(input.value) || 1));
  input.value = String(button.hasAttribute("data-quantity-increase") ? current + 1 : Math.max(1, current - 1));
});

// Copy link / share button on product pages.
document.querySelectorAll("[data-share]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const url = btn.dataset.url;
    const label = btn.textContent;
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      const input = document.querySelector("[data-share-input]");
      if (input) { input.select(); document.execCommand("copy"); }
    }
    btn.textContent = "Link copied ✓";
    setTimeout(() => (btn.textContent = label), 2000);
  });
});

paintCount();
paintCartPage();
if (state.payment && state.payment.status === "pending") pollPayment();

const pageLoader = document.querySelector("[data-page-loader]");
const showPageLoader = () => {
  if (pageLoader) pageLoader.hidden = false;
};

document.addEventListener("click", (event) => {
  if (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  ) return;

  const link = event.target.closest("a[href]");
  if (!link || link.hasAttribute("download") || link.dataset.noLoader !== undefined) return;
  if (link.target && link.target !== "_self") return;

  const destination = new URL(link.href, window.location.href);
  if (
    destination.origin !== window.location.origin ||
    (destination.pathname === window.location.pathname &&
      destination.search === window.location.search &&
      destination.hash)
  ) return;

  showPageLoader();
});

document.addEventListener("submit", (event) => {
  if (event.defaultPrevented || event.target.matches("[data-live-search]")) return;
  showPageLoader();
});

window.addEventListener("pageshow", () => {
  if (pageLoader) pageLoader.hidden = true;
});

const liveSearch = document.querySelector("[data-live-search]");
const productResults = document.querySelector("#product-results");

if (liveSearch && productResults) {
  let searchTimer;
  let searchRequest;

  const refreshResults = async () => {
    searchRequest?.abort();
    const controller = new AbortController();
    searchRequest = controller;
    const params = new URLSearchParams(new FormData(liveSearch));
    for (const [key, value] of params) {
      if (!value) params.delete(key);
    }
    const visibleParams = new URLSearchParams(params);
    const url = new URL(liveSearch.action || window.location.pathname, window.location.origin);
    params.set("_partial", "1");
    url.search = params.toString();
    productResults.setAttribute("aria-busy", "true");

    try {
      const response = await fetch(url, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("Search request failed");
      const markup = await response.text();
      const fragment = document.createElement("template");
      fragment.innerHTML = markup;
      productResults.replaceChildren(fragment.content.cloneNode(true));
      history.replaceState(null, "", `${url.pathname}${visibleParams.size ? `?${visibleParams}` : ""}`);
    } catch (error) {
      if (error.name !== "AbortError") liveSearch.submit();
    } finally {
      if (!controller.signal.aborted) productResults.setAttribute("aria-busy", "false");
    }
  };

  liveSearch.addEventListener("input", (event) => {
    if (event.target.matches('input[type="search"]')) {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(refreshResults, 250);
    }
  });
  liveSearch.addEventListener("change", (event) => {
    if (event.target.matches("select, input[type=checkbox]")) refreshResults();
  });
  liveSearch.addEventListener("submit", (event) => {
    event.preventDefault();
    clearTimeout(searchTimer);
    refreshResults();
  });
}

document.querySelectorAll("[data-ad-carousel]").forEach((carousel) => {
  const slides = [...carousel.querySelectorAll("[data-ad-slide]")];
  const dots = [...carousel.querySelectorAll("[data-ad-dot]")];
  const count = carousel.querySelector("[data-ad-count]");
  const previous = carousel.querySelector("[data-ad-prev]");
  const next = carousel.querySelector("[data-ad-next]");
  if (!slides.length) return;

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const mobileLayout = window.matchMedia("(max-width: 600px)");
  let activeIndex = 0;
  let timer;

  const showSlide = (index) => {
    activeIndex = (index + slides.length) % slides.length;
    slides.forEach((slide, slideIndex) => {
      slide.hidden = mobileLayout.matches && slideIndex !== activeIndex;
    });
    dots.forEach((dot, dotIndex) => {
      if (dotIndex === activeIndex) dot.setAttribute("aria-current", "true");
      else dot.removeAttribute("aria-current");
    });
    if (count) count.textContent = `${activeIndex + 1} / ${slides.length}`;
    if (previous) previous.disabled = !mobileLayout.matches;
    if (next) next.disabled = !mobileLayout.matches;
  };

  const stop = () => {
    window.clearInterval(timer);
    timer = undefined;
  };
  const start = () => {
    stop();
    if (
      reducedMotion.matches ||
      !mobileLayout.matches ||
      slides.length < 2 ||
      document.hidden ||
      carousel.matches(":hover") ||
      carousel.contains(document.activeElement)
    ) return;
    timer = window.setInterval(() => showSlide(activeIndex + 1), 5000);
  };

  previous?.addEventListener("click", () => {
    showSlide(activeIndex - 1);
    start();
  });
  next?.addEventListener("click", () => {
    showSlide(activeIndex + 1);
    start();
  });
  dots.forEach((dot) => {
    dot.addEventListener("click", () => {
      showSlide(Number(dot.dataset.adDot));
      start();
    });
  });
  carousel.addEventListener("mouseenter", stop);
  carousel.addEventListener("mouseleave", start);
  carousel.addEventListener("focusin", stop);
  carousel.addEventListener("focusout", (event) => {
    if (!carousel.contains(event.relatedTarget)) start();
  });
  document.addEventListener("visibilitychange", start);
  reducedMotion.addEventListener?.("change", start);
  mobileLayout.addEventListener("change", () => {
    showSlide(activeIndex);
    start();
  });

  showSlide(0);
  start();
});
