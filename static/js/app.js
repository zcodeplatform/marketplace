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

function add(item) {
  const line = state.lines.find((l) => l.id === item.id);
  if (line) line.qty += 1;
  else state.lines.push({ ...item, qty: 1 });
  state.done = false;
  save();
  paintCount();
  openCart();
}

function setQty(id, qty) {
  if (qty < 1) state.lines = state.lines.filter((l) => l.id !== id);
  else state.lines = state.lines.map((l) => (l.id === id ? { ...l, qty } : l));
  save();
  paintCount();
  paintCart();
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
        <div>
          <div class="line-top"><p>${esc(l.name)}</p><button type="button" aria-label="Remove" data-remove="${esc(l.id)}">×</button></div>
          <p class="muted">${money(l.price)}</p>
          <div class="qty">
            <button type="button" aria-label="Decrease" data-dec="${esc(l.id)}">−</button>
            <span>${l.qty}</span>
            <button type="button" aria-label="Increase" data-inc="${esc(l.id)}">+</button>
          </div>
        </div>
      </li>`).join("")}
    </ul>
    <div class="checkout">
      <div class="subtotal"><span class="muted">Subtotal</span><strong>${money(total)}</strong></div>
      <button class="btn" type="button" data-checkout>Checkout</button>
    </div>`;
  const qtyOf = (id) => state.lines.find((l) => l.id === id).qty;
  body.querySelectorAll("[data-remove]").forEach((b) => (b.onclick = () => setQty(b.dataset.remove, 0)));
  body.querySelectorAll("[data-dec]").forEach((b) => (b.onclick = () => setQty(b.dataset.dec, qtyOf(b.dataset.dec) - 1)));
  body.querySelectorAll("[data-inc]").forEach((b) => (b.onclick = () => setQty(b.dataset.inc, qtyOf(b.dataset.inc) + 1)));
  body.querySelector("[data-checkout]").onclick = () => {
    state.lines = [];
    state.done = true;
    save();
    paintCount();
    paintCart();
  };
}

// "Add to bag" buttons on any page (event delegation).
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-add]");
  if (!btn) return;
  add({ id: btn.dataset.id, name: btn.dataset.name, price: Number(btn.dataset.price), image: btn.dataset.image });
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
