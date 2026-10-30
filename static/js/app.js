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

function lock() {
  document.body.style.overflow =
    !menu.classList.contains("hidden") || !cart.classList.contains("hidden") ? "hidden" : "";
}
function openMenu() { menu.classList.remove("hidden"); lock(); }
function closeMenu() { menu.classList.add("hidden"); lock(); }
function openCart() { cart.classList.remove("hidden"); paintCart(); lock(); }
function closeCart() { cart.classList.add("hidden"); lock(); }

document.querySelector("[data-open-menu]").onclick = openMenu;
document.querySelector("[data-open-cart]").onclick = openCart;
document.querySelectorAll("[data-close-menu]").forEach((el) => (el.onclick = closeMenu));
document.querySelectorAll("[data-close-cart]").forEach((el) => (el.onclick = closeCart));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { closeMenu(); closeCart(); }
});

function paintCount() {
  const badge = document.querySelector("[data-count]");
  const n = count();
  badge.textContent = String(n);
  badge.classList.toggle("hidden", n === 0);
}

function paintCart() {
  const body = document.querySelector("[data-cart-body]");
  const lines = state.lines;

  if (!lines.length && !state.done) {
    body.innerHTML = `<div class="empty"><p>Nothing here yet</p><span>Add a piece from the shop. It stays in this browser.</span><button class="ink-btn" type="button" data-close-cart>Continue browsing</button></div>`;
    body.querySelector("[data-close-cart]").onclick = closeCart;
    return;
  }
  if (state.done) {
    body.innerHTML = `<div class="done"><p>Order noted</p><span>This is a demo checkout — nothing was charged. Your bag is clear.</span><button class="btn" type="button" data-back>Back to the shop</button></div>`;
    body.querySelector("[data-back]").onclick = () => { state.done = false; closeCart(); };
    return;
  }
  const total = lines.reduce((n, l) => n + l.price * l.qty, 0);
  body.innerHTML = `
    <ul class="lines">
      ${lines.map((l) => `<li class="line">
        <img src="${esc(l.image)}" alt="" />
        <div class="line-info">
          <div class="line-top"><p>${esc(l.name)}</p><button type="button" aria-label="Remove" data-remove="${esc(l.id)}">×</button></div>
          <p class="muted">${money(l.price)} each</p>
          <div class="qty">
            <button type="button" aria-label="Decrease" data-dec="${esc(l.id)}">−</button>
            <span>${l.qty}</span>
            <button type="button" aria-label="Increase" data-inc="${esc(l.id)}">+</button>
          </div>
          <p class="line-total">${money(l.price * l.qty)}</p>
        </div>
      </li>`).join("")}
    </ul>
    <div class="checkout">
      <p class="delivery-caption">Delivery details are agreed with each seller.</p>
      <div class="subtotal"><span class="muted">Subtotal</span><strong>${money(total)}</strong></div>
      <a class="cart-full-link" href="${esc(document.body.dataset.cartUrl)}">Review full cart</a>
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
    page.innerHTML = `<div class="cart-empty"><p>Your cart is empty.</p><a class="btn" href="${esc(document.body.dataset.browseUrl)}">Browse products</a></div>`;
    return;
  }
  if (state.done) {
    page.innerHTML = `<div class="cart-empty"><p>Demo checkout complete. No payment was taken.</p><a class="btn" href="${esc(document.body.dataset.browseUrl)}">Continue shopping</a></div>`;
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
