// Cart (localStorage), drawers and share button. Cart logic is the original storefront's,
// adapted so each line stores its own product details (products now come from the database).
const CART_KEY = "marketplace-cart";
const symbol = document.body.dataset.currency || "$";

const money = (n) =>
  symbol + Number(n).toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 2 });

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = { lines: load(), done: false };

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
      <p>All set</p>
      <span>This is a demo checkout. Nothing was charged, and your bag is clear.</span>
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
      <a class="cart-full-link" href="${esc(document.body.dataset.cartUrl)}">View full cart</a>
      <button class="btn" type="button" data-checkout>Checkout (demo)</button>
    </div>`;
  const qtyOf = (id) => state.lines.find((l) => l.id === id).qty;
  body.querySelectorAll("[data-remove]").forEach((b) => (b.onclick = () => setQty(b.dataset.remove, 0)));
  body.querySelectorAll("[data-dec]").forEach((b) => (b.onclick = () => setQty(b.dataset.dec, qtyOf(b.dataset.dec) - 1)));
  body.querySelectorAll("[data-inc]").forEach((b) => (b.onclick = () => setQty(b.dataset.inc, qtyOf(b.dataset.inc) + 1)));
  body.querySelector("[data-checkout]").onclick = finishCheckout;
}

function paintCartPage() {
  const page = document.querySelector("[data-cart-page]");
  if (!page) return;

  if (!state.lines.length && !state.done) {
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
      <p class="cart-empty-title">Demo checkout complete</p>
      <p class="cart-empty-copy">No payment was taken. Your cart is clear.</p>
      <a class="btn" href="${esc(document.body.dataset.browseUrl)}">Continue shopping</a>
    </div>`;
    return;
  }

  const total = state.lines.reduce((sum, line) => sum + line.price * line.qty, 0);
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
        <button class="btn" type="button" data-checkout>Checkout (demo)</button>
        <small>Checkout is a demo. No payment will be taken.</small>
      </aside>
    </div>`;

  const qtyOf = (id) => state.lines.find((line) => line.id === id).qty;
  page.querySelectorAll("[data-remove]").forEach((button) => (button.onclick = () => setQty(button.dataset.remove, 0)));
  page.querySelectorAll("[data-dec]").forEach((button) => (button.onclick = () => setQty(button.dataset.dec, qtyOf(button.dataset.dec) - 1)));
  page.querySelectorAll("[data-inc]").forEach((button) => (button.onclick = () => setQty(button.dataset.inc, qtyOf(button.dataset.inc) + 1)));
  page.querySelector("[data-checkout]").onclick = finishCheckout;
}

function finishCheckout() {
  state.lines = [];
  state.done = true;
  save();
  paintCount();
  paintCart();
  paintCartPage();
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
