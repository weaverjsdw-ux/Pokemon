const qs = (selector) => document.querySelector(selector);

const state = {
  retailers: {},
  busy: false,
  configDirty: false,
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok && !payload.errors) {
    payload.errors = [`HTTP ${response.status}`];
  }
  return payload;
}

function setBusy(value) {
  state.busy = value;
  document.querySelectorAll("button").forEach((button) => {
    button.disabled = value;
  });
}

function configIsBeingEdited() {
  const active = document.activeElement;
  const configForm = qs("#configForm");
  const retailerList = qs("#retailerList");
  return Boolean(
    state.configDirty ||
      (active && configForm?.contains(active)) ||
      (active && retailerList?.contains(active))
  );
}

function renderErrors(errors = []) {
  const box = qs("#errorList");
  box.innerHTML = "";
  for (const error of errors) {
    const item = document.createElement("div");
    item.className = "error";
    item.textContent = error;
    box.appendChild(item);
  }
}

function renderRetailers(retailers = []) {
  const list = qs("#retailerList");
  list.innerHTML = "";
  state.retailers = {};
  for (const retailer of retailers) {
    state.retailers[retailer.slug] = retailer;
    const row = document.createElement("label");
    row.className = "retailer";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = retailer.enabled;
    checkbox.disabled = !retailer.supported;
    checkbox.dataset.slug = retailer.slug;

    const text = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = retailer.name;
    const meta = document.createElement("div");
    meta.className = "meta";
    const mode = retailer.onlineOnly ? "online" : "route";
    const support = retailer.supported ? `${mode} scanner` : retailer.unsupportedReason || "unsupported";
    meta.textContent = `${support} | ${retailer.selectedProductIds} product IDs`;
    text.append(title, meta);

    const pill = document.createElement("span");
    pill.className = "pill";
    pill.textContent = retailer.enabled ? "enabled" : "disabled";

    checkbox.addEventListener("change", () => {
      state.configDirty = true;
      retailer.enabled = checkbox.checked;
      pill.textContent = checkbox.checked ? "enabled" : "disabled";
    });

    row.append(checkbox, text, pill);
    list.appendChild(row);
  }
}

function formatTimestamp(epochSeconds) {
  if (!epochSeconds) return "none";
  return new Date(epochSeconds * 1000).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

function renderRunner(runner = {}, config = {}) {
  const stateText = runner.running ? `${runner.phase || "running"}` : runner.phase || "idle";
  qs("#runnerState").textContent = stateText;
  const interval = runner.intervalSeconds || config.pollIntervalSeconds || 180;
  const stats = [
    ["Mode", runner.running ? "interval running" : "not scanning"],
    ["Interval", `${interval}s`],
    ["Scans", String(runner.scanCount || 0)],
    ["Last scan", formatTimestamp(runner.lastScanAt)],
    ["Next scan", runner.running ? formatTimestamp(runner.nextScanAt) : "stopped"],
  ];
  const root = qs("#runnerStats");
  root.innerHTML = "";
  for (const [label, value] of stats) {
    const item = document.createElement("div");
    item.className = "stat";
    const labelEl = document.createElement("span");
    labelEl.textContent = label;
    const valueEl = document.createElement("strong");
    valueEl.textContent = value;
    item.append(labelEl, valueEl);
    root.appendChild(item);
  }
}

function renderProducts(products = []) {
  const active = products.filter((product) => product.scanned);
  qs("#scanCoverage").textContent = `${active.length}/${products.length} active`;
  const list = qs("#productList");
  list.innerHTML = "";

  for (const product of products) {
    const card = document.createElement("article");
    card.className = "product";

    const header = document.createElement("div");
    header.className = "product-header";
    const text = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = product.name;
    const meta = document.createElement("div");
    meta.className = "meta";
    const parts = [product.key, product.set, product.type].filter(Boolean);
    meta.textContent = parts.join(" | ");
    text.append(name, meta);

    const status = document.createElement("span");
    status.className = "pill";
    status.textContent = product.scanned ? "scanning" : "not active";
    header.append(text, status);

    const tags = document.createElement("div");
    tags.className = "scan-tags";
    const scannedRetailers = product.retailers.filter((retailer) => retailer.active);
    if (!scannedRetailers.length) {
      const tag = document.createElement("span");
      tag.className = "scan-tag inactive";
      tag.textContent = "No enabled retailer ID";
      tags.appendChild(tag);
    }
    for (const retailer of scannedRetailers) {
      const tag = document.createElement("span");
      tag.className = "scan-tag";
      const ids = Object.entries(retailer.ids)
        .map(([field, value]) => `${field}: ${value}`)
        .join(", ");
      tag.textContent = `${retailer.name} | ${ids}`;
      tags.appendChild(tag);
    }

    card.append(header, tags);
    list.appendChild(card);
  }
}

function renderStores(storesByRetailer = {}) {
  const root = qs("#stores");
  root.innerHTML = "";
  const entries = Object.entries(storesByRetailer);
  if (!entries.length) return;
  for (const [slug, stores] of entries) {
    if (!stores.length) {
      const item = document.createElement("div");
      item.className = "store";
      item.innerHTML = `<strong>${slug}</strong><div class="meta">online-only or no route stores found</div>`;
      root.appendChild(item);
      continue;
    }
    for (const store of stores) {
      const item = document.createElement("div");
      item.className = "store";
      const miles = typeof store.distanceMiles === "number" ? `${store.distanceMiles.toFixed(2)} mi from route` : "distance unavailable";
      item.innerHTML = `<strong>${store.name}</strong><div class="meta">${slug} | ${miles}</div>`;
      root.appendChild(item);
    }
  }
}

function renderAlerts(alerts = []) {
  const root = qs("#alerts");
  root.innerHTML = "";
  for (const alert of alerts) {
    const item = document.createElement("div");
    item.className = "alert";
    const price = alert.price ? ` | ${alert.price}` : "";
    item.innerHTML = `<strong>${alert.status}: ${alert.product_name}</strong><div class="meta">${alert.retailer} | ${alert.store_label}${price}</div>`;
    root.appendChild(item);
  }
}

function renderLog(payload = {}) {
  const text = [payload.stdout || "", payload.stderr || ""].filter(Boolean).join("\n");
  if (text) qs("#logOutput").textContent = text;
}

function fillConfig(config = {}) {
  qs("#homeAddress").value = config.homeAddress || "";
  qs("#workAddress").value = config.workAddress || "";
  qs("#routeRadiusMiles").value = config.routeRadiusMiles ?? 4;
  qs("#pollIntervalSeconds").value = config.pollIntervalSeconds ?? 180;
  qs("#routingEngine").value = config.routingEngine || "osrm";
  qs("#discordWebhook").value = "";
  qs("#ntfyTopic").value = config.ntfyTopicSet ? "" : "";
  qs("#productCount").textContent = `${config.productsSelected || 0}/${config.productsTotal || 0} products`;
}

function renderStatus(payload) {
  const config = payload.config || {};
  const runner = payload.runner || {};
  const preserveConfigInputs = configIsBeingEdited();
  const configLabel = config.configMissing ? "example config loaded; save config.yaml to run scanners" : "config.yaml loaded";
  const okLabel = payload.ok ? "ready" : "needs attention";
  qs("#statusText").textContent = `${okLabel} | ${configLabel}`;
  renderRunner(runner, config);
  renderProducts(payload.products || []);
  if (!preserveConfigInputs) {
    fillConfig(config);
    renderRetailers(payload.retailers || []);
  }
  if (!payload.ok || (payload.errors || []).length) {
    renderErrors(payload.errors || []);
  }
  if (Object.keys(runner.stores || {}).length) {
    renderStores(runner.stores || {});
  }
  if ((runner.lastAlerts || []).length) {
    renderAlerts(runner.lastAlerts || []);
  }
  if (runner.stdout || runner.stderr) {
    renderLog(runner);
  }
}

function collectConfig() {
  const retailers = {};
  document.querySelectorAll("#retailerList input[type='checkbox']").forEach((checkbox) => {
    retailers[checkbox.dataset.slug] = { enabled: checkbox.checked };
  });
  return {
    homeAddress: qs("#homeAddress").value,
    workAddress: qs("#workAddress").value,
    routeRadiusMiles: Number(qs("#routeRadiusMiles").value),
    pollIntervalSeconds: Number(qs("#pollIntervalSeconds").value),
    routingEngine: qs("#routingEngine").value,
    discordWebhook: qs("#discordWebhook").value,
    ntfyTopic: qs("#ntfyTopic").value,
    retailers,
  };
}

async function refresh() {
  const payload = await api("/api/status");
  renderStatus(payload);
}

async function runAction(path, body = {}, refreshAfter = true) {
  setBusy(true);
  try {
    const payload = await api(path, {
      method: "POST",
      body: JSON.stringify(body),
    });
    renderErrors(payload.errors || []);
    renderStores(payload.stores || payload.runner?.stores || {});
    renderAlerts(payload.alerts || payload.runner?.lastAlerts || []);
    renderLog(payload);
    if (refreshAfter) {
      await refresh();
    }
    return payload;
  } finally {
    setBusy(false);
  }
}

qs("#configForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = await runAction("/api/config", collectConfig(), false);
  if (payload.ok) {
    state.configDirty = false;
    await refresh();
  }
});

qs("#configForm").addEventListener("input", () => {
  state.configDirty = true;
});

qs("#configForm").addEventListener("change", () => {
  state.configDirty = true;
});

qs("#refreshBtn").addEventListener("click", refresh);
qs("#dryRunBtn").addEventListener("click", () => runAction("/api/dry-run", {}, false));
qs("#scanOnceBtn").addEventListener("click", () => runAction("/api/scan-once", { notify: false }, false));
qs("#startBtn").addEventListener("click", () => runAction("/api/start", { notify: true }));
qs("#stopBtn").addEventListener("click", () => runAction("/api/stop"));

refresh();
setInterval(refresh, 5000);
