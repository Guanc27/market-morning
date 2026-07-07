const API = location.origin;

const state = {
  token: localStorage.getItem("mm_token") || "",
  user: null,
  tiers: [],
  usage: null,
  config: null,
  authMode: "login",
};

window.__mmToken = state.token;

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const res = await fetch(`${API}${path}`, { ...opts, headers, credentials: "include" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

function $(sel) { return document.querySelector(sel); }
function show(el) { el?.classList.remove("hidden"); }
function hide(el) { el?.classList.add("hidden"); }

function setView(name) {
  document.querySelectorAll(".view").forEach(v => hide(v));
  show($(`#view-${name}`));
  location.hash = name;
}

async function bootstrap() {
  state.config = await api("/saas/config");
  state.tiers = (await api("/saas/tiers")).tiers;
  renderTiers();
  if (state.token) {
    try {
      const me = await api("/saas/auth/me");
      state.user = me.user;
      state.usage = me.subscription;
      renderAuth();
      renderAccount();
      renderTierBanner();
    } catch {
      logout();
    }
  } else {
    renderAuth();
  }
}

function renderAuth() {
  const zone = $("#auth-zone");
  if (!zone) return;
  if (state.user) {
    const tier = state.usage?.tier_name || state.usage?.tier || "free";
    zone.innerHTML = `
      <span class="tier-pill">${tier}</span>
      <span class="user-email">${state.user.email}</span>
      <button type="button" class="btn ghost" id="btn-logout">Log out</button>
    `;
    $("#btn-logout")?.addEventListener("click", logout);
  } else {
    zone.innerHTML = `
      <button type="button" class="btn ghost" id="btn-login">Log in</button>
      <button type="button" class="btn primary" id="btn-signup">Sign up free</button>
    `;
    $("#btn-login")?.addEventListener("click", () => openAuth("login"));
    $("#btn-signup")?.addEventListener("click", () => openAuth("signup"));
  }
}

function renderTierBanner() {
  const el = $("#tier-banner");
  if (!el || !state.usage) return;
  const tier = state.usage.tier;
  if (tier === "free") {
    el.textContent = "Free plan — portfolio AI analysis and today's picks require Pro. Upgrade anytime.";
    show(el);
  } else {
    hide(el);
  }
}

function renderTiers() {
  const grid = $("#tier-grid");
  if (!grid) return;
  grid.innerHTML = state.tiers.map(t => {
    const f = t.features;
    const bullets = [
      f.morning_brief_daily && "Daily morning brief",
      f.late_day_daily && "Late-day desk update",
      f.picks_daily && "Daily top 5 picks (held-excluded)",
      f.picks_preview_only && "Yesterday's picks preview only",
      f.portfolio_analysis_per_month > 0 && `${f.portfolio_analysis_daily ? "Daily" : f.portfolio_analysis_per_month + "/mo"} portfolio AI`,
      f.explore_per_month === null ? "Unlimited explore" : `${f.explore_per_month} explore / mo`,
      f.robinhood_sync && "Robinhood sync",
    ].filter(Boolean);
    const monthly = t.price_monthly_usd;
    const cta = monthly === 0
      ? `<button class="btn ghost" data-tier="${t.id}">Current default</button>`
      : `<button class="btn primary" data-checkout="${t.id}">Subscribe $${monthly}/mo</button>`;
    return `
      <article class="tier-card ${t.id === "pro" ? "featured" : ""}">
        <h3>${t.name}</h3>
        <p class="price">${monthly === 0 ? "Free" : `$${monthly}<span>/mo</span>`}</p>
        <p class="tagline">${t.tagline}</p>
        <ul>${bullets.map(b => `<li>${b}</li>`).join("")}</ul>
        ${cta}
      </article>`;
  }).join("");

  grid.querySelectorAll("[data-checkout]").forEach(btn => {
    btn.addEventListener("click", () => startCheckout(btn.dataset.checkout));
  });
}

async function startCheckout(tierId) {
  if (!state.token) {
    openAuth("signup");
    return;
  }
  const priceKey = `${tierId}_monthly`;
  const priceId = state.config?.prices?.[`${tierId === "pro" ? "pro" : "desk"}_monthly`];
  if (!priceId) {
    alert("Stripe price IDs not configured on server. Set STRIPE_PRICE_* in backend/.env");
    return;
  }
  const { checkout_url } = await api("/saas/billing/checkout", {
    method: "POST",
    body: JSON.stringify({ price_id: priceId }),
  });
  location.href = checkout_url;
}

function renderAccount() {
  const panel = $("#account-panel");
  if (!panel || !state.usage) return;
  const u = state.usage.usage_month || {};
  const lim = state.usage.limits || {};
  panel.innerHTML = `
    <p><strong>Plan:</strong> ${state.usage.tier_name} (${state.usage.tier})</p>
    <h4>Usage this month</h4>
    <ul class="usage-list">
      <li>Brief regens: ${u.brief_regen || 0} / ${lim.brief_regen_per_month ?? 0}</li>
      <li>Portfolio analyses: ${u.portfolio_analysis || 0} / ${lim.portfolio_analysis_per_month ?? 0}</li>
      <li>Explore: ${u.explore || 0} / ${lim.explore_per_month ?? "∞"}</li>
    </ul>
    <button type="button" class="btn primary" id="btn-portal">Manage billing</button>
  `;
  $("#btn-portal")?.addEventListener("click", async () => {
    const { portal_url } = await api("/saas/billing/portal", { method: "POST" });
    location.href = portal_url;
  });
}

function openAuth(mode) {
  state.authMode = mode;
  $("#auth-title").textContent = mode === "signup" ? "Create account" : "Log in";
  show($("#name-field"));
  hide($("#name-field"));
  if (mode === "signup") show($("#name-field"));
  $("#auth-error").textContent = "";
  $("#auth-dialog").showModal();
}

async function submitAuth(e) {
  e.preventDefault();
  const fd = new FormData($("#auth-form"));
  const body = Object.fromEntries(fd.entries());
  try {
    const path = state.authMode === "signup" ? "/saas/auth/signup" : "/saas/auth/login";
    const data = await api(path, { method: "POST", body: JSON.stringify(body) });
    state.token = data.token;
    localStorage.setItem("mm_token", state.token);
    window.__mmToken = state.token;
    $("#auth-dialog").close();
    await bootstrap();
    setView("app");
  } catch (err) {
    $("#auth-error").textContent = err.message;
  }
}

function logout() {
  state.token = "";
  state.user = null;
  localStorage.removeItem("mm_token");
  window.__mmToken = "";
  api("/saas/auth/logout", { method: "POST" }).catch(() => {});
  renderAuth();
  setView("pricing");
}

document.querySelectorAll("[data-view]").forEach(a => {
  a.addEventListener("click", e => {
    e.preventDefault();
    setView(a.dataset.view);
  });
});

$("#auth-form")?.addEventListener("submit", submitAuth);
$("#auth-cancel")?.addEventListener("click", () => $("#auth-dialog").close());

const hash = (location.hash || "#app").slice(1);
setView(["app", "pricing", "account"].includes(hash) ? hash : "app");

bootstrap();

if (location.search.includes("checkout=success")) {
  setTimeout(bootstrap, 1500);
}
