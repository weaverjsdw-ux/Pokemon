const qs = (selector) => document.querySelector(selector);
const clear = (element) => element.replaceChildren();

const state = {
  retailers: {},
  products: [],
  busy: false,
  configDirty: false,
};

function appendTextBlock(parent, titleText, metaText = "") {
  const title = document.createElement("strong");
  title.textContent = titleText;
  parent.appendChild(title);
  if (metaText) {
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = metaText;
    parent.appendChild(meta);
  }
}

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

function renderErrors(errors = [], warnings = []) {
  const box = qs("#errorList");
  clear(box);
  for (const error of errors) {
    const item = document.createElement("div");
    item.className = "error";
    item.textContent = error;
    box.appendChild(item);
  }
  for (const warning of warnings) {
    const item = document.createElement("div");
    item.className = "notice";
    item.textContent = warning;
    box.appendChild(item);
  }
}

function renderRetailers(retailers = []) {
  const list = qs("#retailerList");
  clear(list);
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
    let support = retailer.supported ? `${mode} scanner` : retailer.unsupportedReason || "unsupported";
    if (retailer.missingApiKey) support = `${support} | missing API key`;
    meta.textContent = `${support} | ${retailer.selectedProductIds} product IDs`;
    text.append(title, meta);

    const pill = document.createElement("span");
    pill.className = "pill";
    pill.textContent = retailer.enabled ? "scanning" : "off";

    checkbox.addEventListener("change", () => {
      state.configDirty = true;
      retailer.enabled = checkbox.checked;
      pill.textContent = checkbox.checked ? "scanning" : "off";
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
  clear(root);
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

function formatMiles(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "not measured";
  return `${value.toFixed(value % 1 ? 1 : 0)} mi`;
}

function renderPriceMetric(parent, label, value, detail = "", url = "", options = {}) {
  const item = document.createElement("div");
  item.className = "price-metric";
  for (const className of options.classNames || []) item.classList.add(className);
  if (options.title) item.title = options.title;
  const labelEl = document.createElement("span");
  labelEl.textContent = label;
  const valueEl = url ? document.createElement("a") : document.createElement("strong");
  valueEl.textContent = value || "Not set";
  if (url) {
    valueEl.href = url;
    valueEl.target = "_blank";
    valueEl.rel = "noreferrer";
  }
  item.append(labelEl, valueEl);
  if (detail) {
    const detailEl = document.createElement("small");
    detailEl.textContent = detail;
    item.appendChild(detailEl);
  }
  parent.appendChild(item);
}

function formatPremiumRatio(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "";
  return `${value.toFixed(value >= 10 ? 1 : 2).replace(/\.?0+$/, "")}x MSRP`;
}

function resaleConfidenceClasses(row = {}) {
  const classes = [];
  const confidence = row.confidence || "none";
  classes.push(`price-confidence-${confidence}`);
  if (row.needsVerification || row.asterisk) classes.push("price-needs-verification");
  return classes;
}

function resalePriceDetail(row = {}) {
  if (!row || !row.status) return "waiting for resale refresh";
  if (row.status === "ok") {
    const bits = [];
    if (row.confidenceLabel) bits.push(row.confidenceLabel);
    const ratio = formatPremiumRatio(row.premiumRatio);
    if (ratio) bits.push(ratio);
    if (row.needsVerification || row.asterisk) bits.push("verify before acting");
    if (row.low && row.high && row.low !== row.high) bits.push(`${row.low}-${row.high} middle range`);
    if (row.basis) bits.push(row.basis);
    if (row.sampleSize && !String(row.source || "").includes("PriceCharting")) bits.push(`${row.sampleSize} listings`);
    if (row.source) bits.push(row.source);
    if (row.checkedAt) bits.push(`checked ${formatAgo(row.checkedAt)}`);
    return bits.join(" | ");
  }
  if (row.status === "needs_auth") return "eBay API not configured";
  if (row.status === "pending") return "waiting for resale refresh";
  if (row.status === "no_matches") return "no matching resale source";
  if (row.status === "no_market") return row.detail || "No reliable resale market yet; use MSRP.";
  if (row.status === "not_released") return row.detail || "MSRP only until release/preorder data appears.";
  if (row.status === "disabled") return "resale checks disabled";
  return row.detail || "resale source unavailable; use MSRP.";
}

function resaleDisplayValue(row = {}) {
  if (row.estimate) return `${row.estimate}${row.asterisk ? "*" : ""}`;
  const status = row.status || "";
  if (status === "not_released") return "MSRP only";
  if (status === "no_market" || status === "no_matches") return "MSRP only";
  if (status === "pending") return "Checking";
  if (status === "needs_auth") return "Needs eBay auth";
  if (status === "disabled") return "Off";
  if (status === "error") return "MSRP only";
  return "Checking";
}

function resaleStatusLabel(row = {}) {
  const status = row.status || "";
  if (status === "ok") return row.asterisk ? "verify" : "priced";
  if (status === "not_released") return "not released";
  if (status === "no_market" || status === "no_matches") return "MSRP only";
  if (status === "needs_auth") return "needs auth";
  if (status === "disabled") return "off";
  if (status === "error") return "source issue";
  return "checking";
}

function resaleStatusClass(row = {}) {
  const status = row.status || "";
  if (status === "ok" && !row.asterisk) return "market-ok";
  if (status === "ok") return "market-verify";
  if (status === "pending") return "market-pending";
  if (status === "error" || status === "needs_auth") return "market-warning";
  return "market-msrp";
}

function renderProductPrices(parent, product) {
  const row = document.createElement("div");
  row.className = "price-row";
  renderPriceMetric(row, "MSRP", product.msrp || "MSRP not set");
  const resale = product.resale || {};
  renderPriceMetric(
    row,
    "Resale",
    resaleDisplayValue(resale),
    resalePriceDetail(resale),
    resale.url || "",
    {
      classNames: resaleConfidenceClasses(resale),
      title: resale.confidenceReason || resale.detail || "",
    },
  );
  parent.appendChild(row);
}

function renderStoreDiagnostics(rows = [], config = {}) {
  const root = qs("#storeDiagnostics");
  clear(root);
  if (!rows.length) {
    const note = document.createElement("div");
    note.className = "discovery-note";
    note.textContent = "Run Check Stores or Scan Once to see how the route radius is applied.";
    root.appendChild(note);
    return;
  }

  const heading = document.createElement("div");
  heading.className = "discovery-heading";
  const title = document.createElement("strong");
  title.textContent = "Store Discovery";
  const radius = document.createElement("span");
  radius.className = "meta";
  radius.textContent = `configured route radius ${formatMiles(config.routeRadiusMiles)}`;
  heading.append(title, radius);
  root.appendChild(heading);

  for (const row of rows) {
    const card = document.createElement("div");
    card.className = `discovery-card discovery-${row.status || "unknown"}`;
    const cardTitle = document.createElement("div");
    cardTitle.className = "discovery-title";
    const name = document.createElement("strong");
    name.textContent = row.name || row.slug;
    const pill = document.createElement("span");
    pill.className = "pill";
    pill.textContent = row.status || "unknown";
    cardTitle.append(name, pill);

    const meta = document.createElement("div");
    meta.className = "meta";
    if (row.onlineOnly) {
      meta.textContent = "Online-only source; route radius does not apply.";
    } else {
      meta.textContent = [
        `route filter ${formatMiles(row.corridorRadiusMiles)}`,
        `candidate search ${formatMiles(row.candidateSearchRadiusMiles)}`,
        `${row.centersQueried || 0}/${row.centersPlanned || 0} centers`,
        `${row.uniqueCandidateStores || 0} unique candidates`,
        `${row.keptStores || 0} kept`,
        `${row.filteredOutStores || 0} filtered out`,
      ].join(" / ");
    }

    const detail = document.createElement("div");
    detail.className = "meta discovery-detail";
    if ((row.errors || []).length) {
      detail.textContent = row.errors[0];
    } else if (row.status === "filtered_out") {
      detail.textContent = "Stores were found, but none landed inside the route corridor radius.";
    } else if (row.status === "empty") {
      detail.textContent = "The retailer returned no candidate stores for the home/work search centers.";
    } else if (row.status === "ready") {
      detail.textContent = "Radius is active: stores found by the retailer were filtered against the route corridor.";
    } else if (row.status === "skipped") {
      detail.textContent = "This source checks online stock only, so increasing radius will not change its store count.";
    }

    card.append(cardTitle, meta);
    if (detail.textContent) card.appendChild(detail);
    root.appendChild(card);
  }
}

function renderProducts(products = []) {
  state.products = products;
  const sortedProducts = [...products].sort((a, b) => {
    if (a.scanned !== b.scanned) return a.scanned ? -1 : 1;
    if ((b.priorityScore || 0) !== (a.priorityScore || 0)) {
      return (b.priorityScore || 0) - (a.priorityScore || 0);
    }
    return String(a.name).localeCompare(String(b.name));
  });
  const active = sortedProducts.filter((product) => product.scanned);
  qs("#scanCoverage").textContent = `${active.length}/${products.length} active`;
  const list = qs("#productList");
  clear(list);

  for (const product of sortedProducts) {
    const card = document.createElement("article");
    card.className = "product";

    const header = document.createElement("div");
    header.className = "product-header";
    const text = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = product.name;
    const meta = document.createElement("div");
    meta.className = "meta";
    const parts = [product.key, product.game, product.set, product.type].filter(Boolean);
    meta.textContent = parts.join(" | ");
    text.append(name, meta);

    const status = document.createElement("span");
    status.className = "pill";
    status.classList.toggle("priority", product.priority === "High priority");
    status.textContent = product.scanned ? product.priority : "not active";
    header.append(text, status);

    const tags = document.createElement("div");
    tags.className = "scan-tags";
    const scannedRetailers = product.retailers.filter((retailer) => retailer.active);
    if (!scannedRetailers.length) {
      const blockers = product.retailers
        .filter((retailer) => retailer.enabled && retailer.supported && retailer.blockedReason)
        .slice(0, 3);
      if (blockers.length) {
        for (const retailer of blockers) {
          const tag = document.createElement("span");
          tag.className = "scan-tag inactive";
          tag.textContent = `${retailer.name}: ${retailer.blockedReason}`;
          tags.appendChild(tag);
        }
      } else {
        const tag = document.createElement("span");
        tag.className = "scan-tag inactive";
        tag.textContent = "No enabled retailer ID";
        tags.appendChild(tag);
      }
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

    card.appendChild(header);
    renderProductPrices(card, product);
    card.appendChild(tags);
    list.appendChild(card);
  }
}

function queueActionButtonLabel(oneClick = {}) {
  if (oneClick.type === "add-id") return "Fill Add ID";
  if (oneClick.type === "settings") return "Open Settings";
  return "";
}

function applyQueueAction(oneClick = {}) {
  if (oneClick.type === "add-id") {
    const retailer = qs("#idRetailer");
    const product = qs("#idProduct");
    if (oneClick.retailer && [...retailer.options].some((option) => option.value === oneClick.retailer)) {
      retailer.value = oneClick.retailer;
    }
    if (oneClick.productKey && [...product.options].some((option) => option.value === oneClick.productKey)) {
      product.value = oneClick.productKey;
    }
    qs("#productIdForm").scrollIntoView({ behavior: "smooth", block: "start" });
    qs("#idValue").focus();
    qs("#idSaveStatus").textContent = "Paste the product URL or retailer ID, then Add ID.";
    return;
  }
  if (oneClick.type === "settings") {
    qs("#configForm").scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function renderActionQueue(items = []) {
  const root = qs("#workQueue");
  clear(root);
  qs("#workQueueCount").textContent = `${items.length} open`;
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    appendTextBlock(
      empty,
      "No setup blockers",
      "Enabled sources either have usable IDs or are waiting on the next scan.",
    );
    root.appendChild(empty);
    return;
  }

  for (const item of items) {
    const card = document.createElement("article");
    card.className = "work-card";

    const head = document.createElement("div");
    head.className = "work-card-title";
    const title = document.createElement("strong");
    title.textContent = item.title || item.action || item.slug;
    const pill = document.createElement("span");
    pill.className = "pill";
    pill.textContent = item.action || item.state || "next";
    head.append(title, pill);

    const detail = document.createElement("div");
    detail.className = "meta";
    detail.textContent = item.detail || "";

    const facts = document.createElement("div");
    facts.className = "work-facts";
    for (const [label, value] of [
      ["Unlocks", item.count ? `${item.count} products` : ""],
      ["Source", item.retailerName || item.slug],
    ]) {
      if (!value) continue;
      const fact = document.createElement("span");
      fact.textContent = `${label}: ${value}`;
      facts.appendChild(fact);
    }

    const products = document.createElement("div");
    products.className = "mini-products";
    for (const product of (item.products || []).slice(0, 3)) {
      const chip = document.createElement("span");
      chip.textContent = product.name || product.key;
      products.appendChild(chip);
    }
    if ((item.products || []).length > 3) {
      const chip = document.createElement("span");
      chip.textContent = `+${item.products.length - 3} more`;
      products.appendChild(chip);
    }

    card.append(head, detail);
    if (facts.childElementCount) card.appendChild(facts);
    if (products.childElementCount) card.appendChild(products);

    const label = queueActionButtonLabel(item.oneClick || {});
    if (label) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary compact";
      button.textContent = label;
      button.addEventListener("click", () => applyQueueAction(item.oneClick || {}));
      card.appendChild(button);
    }
    root.appendChild(card);
  }
}

function formatReleaseDate(value) {
  if (!value) return "";
  return `releases ${value}`;
}

function renderMarketWatch(products = []) {
  const root = qs("#marketWatch");
  clear(root);
  const watched = products
    .filter((product) => product.selected)
    .sort((a, b) => {
      if ((b.priorityScore || 0) !== (a.priorityScore || 0)) {
        return (b.priorityScore || 0) - (a.priorityScore || 0);
      }
      return String(a.name).localeCompare(String(b.name));
    });
  const priced = watched.filter((product) => product.resale?.status === "ok").length;
  qs("#marketCount").textContent = `${priced}/${watched.length} priced`;

  if (!watched.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    appendTextBlock(empty, "No watched products", "Select products in config.yaml to track MSRP and resale.");
    root.appendChild(empty);
    return;
  }

  for (const product of watched) {
    const resale = product.resale || {};
    const card = document.createElement("article");
    card.className = `market-card ${resaleStatusClass(resale)}`;

    const head = document.createElement("div");
    head.className = "market-card-title";
    const title = document.createElement("strong");
    title.textContent = product.name;
    const pill = document.createElement("span");
    pill.className = "pill";
    pill.textContent = resaleStatusLabel(resale);
    head.append(title, pill);

    const prices = document.createElement("div");
    prices.className = "market-prices";
    const msrp = document.createElement("div");
    appendTextBlock(msrp, product.msrp || "MSRP not set", "MSRP");
    const estimate = document.createElement("div");
    appendTextBlock(estimate, resaleDisplayValue(resale), "resale");
    prices.append(msrp, estimate);

    const detail = document.createElement("div");
    detail.className = "meta";
    const bits = [
      product.set,
      product.type,
      formatReleaseDate(product.releaseDate),
      resalePriceDetail(resale),
    ].filter(Boolean);
    detail.textContent = bits.join(" | ");

    card.append(head, prices, detail);
    if (resale.url) {
      const link = document.createElement("a");
      link.href = resale.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.className = "source-link";
      link.textContent = "Open price source";
      card.appendChild(link);
    }
    root.appendChild(card);
  }
}

function renderProductIdOptions(retailers = [], products = []) {
  const retailerSelect = qs("#idRetailer");
  const productSelect = qs("#idProduct");
  const previousRetailer = retailerSelect.value;
  const previousProduct = productSelect.value;
  clear(retailerSelect);
  clear(productSelect);

  const eligibleRetailers = retailers.filter(
    (retailer) => retailer.supported && (retailer.productIdFields || []).length,
  );
  for (const retailer of eligibleRetailers) {
    const option = document.createElement("option");
    option.value = retailer.slug;
    const field = (retailer.productIdFields || []).join("/");
    option.textContent = `${retailer.name} (${field})`;
    retailerSelect.appendChild(option);
  }

  const sortedProducts = [...products].sort((a, b) => {
    if (a.scanned !== b.scanned) return a.scanned ? -1 : 1;
    return String(a.name).localeCompare(String(b.name));
  });
  for (const product of sortedProducts) {
    const option = document.createElement("option");
    option.value = product.key;
    option.textContent = product.name;
    productSelect.appendChild(option);
  }

  if (previousRetailer && [...retailerSelect.options].some((option) => option.value === previousRetailer)) {
    retailerSelect.value = previousRetailer;
  }
  if (previousProduct && [...productSelect.options].some((option) => option.value === previousProduct)) {
    productSelect.value = previousProduct;
  }
}

function stockClass(status) {
  if (status === "IN_STOCK" || status === "ONLINE_IN_STOCK") return "stock-in";
  if (status === "LIMITED") return "stock-limited";
  if (status === "OUT" || status === "ONLINE_OUT") return "stock-out";
  if (status === "SCOPED") return "stock-scoped";
  if (status === "BLOCKED" || status === "SOURCE_ERROR" || status === "DISCOVERY_FAILED") return "stock-error";
  return "stock-unknown";
}

function stockLabel(status) {
  const labels = {
    IN_STOCK: "In stock",
    ONLINE_IN_STOCK: "Online in stock",
    LIMITED: "Limited",
    OUT: "Out",
    ONLINE_OUT: "Online out",
    BLOCKED: "Source blocked",
    SOURCE_ERROR: "Source error",
    NO_DATA: "No data",
    DISCOVERY_FAILED: "Store discovery failed",
    NOT_CHECKED: "Not checked",
    SCOPED: "Scoped",
    UNKNOWN: "Unknown",
  };
  return labels[status] || status || "Unknown";
}

function renderStockBoard(board = []) {
  const root = qs("#stockBoard");
  clear(root);
  if (!board.length) {
    const note = document.createElement("div");
    note.className = "discovery-note";
    appendTextBlock(
      note,
      "No scoped inventory board yet",
      "Run Check Stores to list route stores and products, or Scan Once to check inventory now.",
    );
    root.appendChild(note);
    return;
  }

  for (const retailer of board) {
    const section = document.createElement("section");
    section.className = "stock-retailer";
    const inventoryChecked = retailer.inventoryChecked !== false;

    const title = document.createElement("div");
    title.className = "stock-retailer-title";
    const titleText = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = retailer.retailerName;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = [
      retailer.onlineOnly ? "Online checks" : inventoryChecked ? "Route inventory checks" : "Scoped route stores",
      `${retailer.activeProductCount} products`,
      inventoryChecked ? "inventory checked" : "ready for Scan Once",
    ].join(" | ");
    titleText.append(name, meta);
    const checked = document.createElement("span");
    checked.className = "pill";
    checked.textContent = inventoryChecked && retailer.checkedAt ? `checked ${formatTimestamp(retailer.checkedAt)}` : "scoped";
    title.append(titleText, checked);
    section.appendChild(title);
    if (retailer.verdict) {
      const verdict = document.createElement("div");
      verdict.className = "notice";
      verdict.textContent = retailer.verdict;
      section.appendChild(verdict);
    }

    for (const location of retailer.locations || []) {
      const card = document.createElement("article");
      card.className = "stock-location";
      const head = document.createElement("div");
      head.className = "stock-location-head";
      const storeText = document.createElement("div");
      const storeName = document.createElement("strong");
      storeName.textContent = location.storeLabel;
      const storeMeta = document.createElement("div");
      storeMeta.className = "meta";
      storeMeta.textContent = typeof location.distanceMiles === "number"
        ? `${location.distanceMiles.toFixed(2)} mi from route`
        : retailer.onlineOnly ? "online" : "distance unavailable";
      storeText.append(storeName, storeMeta);
      const count = document.createElement("span");
      count.className = "pill";
      count.textContent = inventoryChecked
        ? `${location.inStockCount || 0} in stock`
        : "scoped";
      head.append(storeText, count);
      card.appendChild(head);

      const products = document.createElement("div");
      products.className = "stock-products";
      for (const item of location.products || []) {
        const chip = document.createElement("div");
        chip.className = `stock-chip ${stockClass(item.status)}`;
        const productName = document.createElement("strong");
        productName.textContent = item.productName;
        const itemMeta = document.createElement("div");
        itemMeta.className = "meta";
        const price = item.price ? ` | ${item.price}` : "";
        const reason = item.statusReason ? ` | ${item.statusReason}` : "";
        itemMeta.textContent = `${stockLabel(item.status)} | ${item.priority}${price}${reason}`;
        chip.append(productName, itemMeta);
        if (item.verdict) {
          const v = document.createElement('span');
          const tier = item.verdict.split(' ')[0].toLowerCase(); // buy|thin|skip
          v.className = 'verdict verdict-' + tier;
          v.textContent = item.verdict;
          chip.appendChild(v);
        }
        products.appendChild(chip);
      }
      if (!(location.products || []).length) {
        const chip = document.createElement("div");
        chip.className = "stock-chip stock-unknown";
        const label = String(location.storeLabel || "").toLowerCase();
        const noStores = label.includes("no route stores") || label.includes("blocked") || label.includes("failed");
        appendTextBlock(
          chip,
          noStores ? "No store products checked" : "No tracked products checked",
          noStores
            ? "No scoped stores are available for this retailer right now."
            : "No active product IDs for this scanner/store.",
        );
        products.appendChild(chip);
      }
      card.appendChild(products);
      section.appendChild(card);
    }
    root.appendChild(section);
  }
}

function renderStores(storesByRetailer = {}) {
  const root = qs("#stores");
  clear(root);
  const entries = Object.entries(storesByRetailer);
  if (!entries.length) return;
  for (const [slug, stores] of entries) {
    if (!stores.length) {
      const item = document.createElement("div");
      item.className = "store";
      appendTextBlock(item, slug, "online-only or no route stores found");
      root.appendChild(item);
      continue;
    }
    for (const store of stores) {
      const item = document.createElement("div");
      item.className = "store";
      const miles = typeof store.distanceMiles === "number" ? `${store.distanceMiles.toFixed(2)} mi from route` : "distance unavailable";
      appendTextBlock(item, store.name, `${slug} | ${miles}`);
      root.appendChild(item);
    }
  }
}

function renderAlerts(alerts = []) {
  const root = qs("#alerts");
  clear(root);
  for (const alert of alerts) {
    const item = document.createElement("div");
    item.className = "alert";
    const price = alert.price ? ` | ${alert.price}` : "";
    appendTextBlock(item, `${alert.status}: ${alert.product_name}`, `${alert.retailer} | ${alert.store_label}${price}`);
    root.appendChild(item);
  }
}

function renderLog(payload = {}) {
  const text = [payload.stdout || "", payload.stderr || ""].filter(Boolean).join("\n");
  qs("#logOutput").textContent = text;
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

function formatAgo(ts) {
  if (!ts) return "never";
  const delta = Math.max(0, Math.floor(Date.now() / 1000) - ts);
  if (delta < 90) return `${delta}s ago`;
  if (delta < 5400) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 36 * 3600) return `${Math.floor(delta / 3600)}h ago`;
  return `${Math.floor(delta / 86400)}d ago`;
}

function renderSummary(summary = {}, coverage = {}) {
  const score = summary.coverageScore ?? coverage.score ?? 0;
  const actionable = summary.actionableProducts ?? coverage.actionableProducts ?? 0;
  const total = summary.totalProducts ?? coverage.totalProducts ?? 0;
  const activeSources = summary.activeSources ?? 0;
  const enabledSources = summary.enabledSources ?? 0;
  const healthCounts = summary.sourceHealth || {};
  const degraded = healthCounts.degraded || 0;
  const down = healthCounts.down || 0;
  const healthy = healthCounts.healthy || 0;
  const unknown = healthCounts.unknown || 0;

  qs("#summaryCoverage").textContent = `${score}%`;
  qs("#summaryCoverageSub").textContent = `${actionable}/${total} actionable`;
  qs("#summarySources").textContent = `${activeSources} active`;
  qs("#summarySourcesSub").textContent = `${enabledSources} enabled`;

  if (down > 0) {
    qs("#summaryHealth").textContent = `${down} down`;
  } else if (degraded > 0) {
    qs("#summaryHealth").textContent = `${degraded} degraded`;
  } else if (healthy > 0) {
    qs("#summaryHealth").textContent = "healthy";
  } else {
    qs("#summaryHealth").textContent = "unknown";
  }
  qs("#summaryHealthSub").textContent = `${healthy} ok / ${degraded} degraded / ${unknown} unknown`;

  qs("#summaryLastScan").textContent = formatTimestamp(summary.lastScanAt);
  const hits = summary.stockHits || 0;
  const restocks = summary.recentRestocks || 0;
  qs("#summaryLastScanSub").textContent = `${summary.phase || "idle"} / ${summary.scanCount || 0} scans / ${hits} hits / ${restocks} recent`;
}

function renderCoverage(coverage = {}) {
  const score = coverage.score || 0;
  qs("#coverageScore").textContent = `${score}%`;
  const fill = qs("#coverageFill");
  fill.style.width = `${score}%`;
  fill.style.background = score >= 67 ? "#2ecc71" : score >= 34 ? "#f1c40f" : "#e74c3c";

  const detail = [
    `${coverage.actionableProducts || 0}/${coverage.totalProducts || 0} products actionable`,
  ];
  const perRetailer = (coverage.retailers || [])
    .filter((r) => r.enabled && r.supported)
    .map((r) => `${r.name} ${r.withId}/${r.total}`);
  if (perRetailer.length) detail.push(perRetailer.join(" / "));
  qs("#coverageDetail").textContent = detail.join(" - ");

  const root = qs("#coverageBreakdown");
  clear(root);
  const rows = [...(coverage.retailers || [])]
    .filter((r) => r.enabled && r.supported)
    .sort((a, b) => (b.withId || 0) - (a.withId || 0) || String(a.name).localeCompare(String(b.name)));
  if (!rows.length) {
    const note = document.createElement("div");
    note.className = "meta";
    note.textContent = "No enabled supported retailers are active.";
    root.appendChild(note);
    return;
  }
  for (const retailer of rows) {
    const row = document.createElement("div");
    row.className = "coverage-row";
    const label = document.createElement("span");
    label.textContent = retailer.name;
    const miniBar = document.createElement("div");
    miniBar.className = "mini-bar";
    const miniFill = document.createElement("div");
    miniFill.style.width = `${retailer.pct || 0}%`;
    miniBar.appendChild(miniFill);
    const count = document.createElement("strong");
    count.textContent = `${retailer.withId}/${retailer.total}`;
    row.append(label, miniBar, count);
    root.appendChild(row);
  }
}

const HEALTH_LABEL = {
  OK: "ok",
  NO_DATA: "no data (parser?)",
  BLOCKED: "blocked",
  ERROR: "error",
  DISCOVERY_FAILED: "store search failed",
  "": "not checked",
};

function renderHealth(healthList = [], retailers = []) {
  const root = qs("#healthGrid");
  clear(root);
  const bySlug = {};
  for (const h of healthList) bySlug[h.slug] = h;
  const enabledRetailers = retailers
    .filter((r) => r.enabled && r.supported)
    .sort((a, b) => String(a.name).localeCompare(String(b.name)));

  if (!enabledRetailers.length) {
    const note = document.createElement("div");
    note.className = "meta";
    note.textContent = "No enabled supported sources.";
    root.appendChild(note);
    return;
  }

  for (const retailer of enabledRetailers) {
    const h = bySlug[retailer.slug] || {
      slug: retailer.slug,
      state: "unknown",
      last_status: "",
      last_http_status: null,
      last_success_ts: null,
      last_check_ts: null,
      last_items_found: 0,
      last_detail: "",
    };
    const card = document.createElement("div");
    card.className = `health-card health-${h.state || "unknown"}`;
    const title = document.createElement("div");
    title.className = "health-card-title";
    const label = document.createElement("strong");
    const dot = document.createElement("span");
    dot.className = "dot";
    label.append(dot, document.createTextNode(retailer.name || h.slug));
    const statePill = document.createElement("span");
    statePill.className = "pill";
    statePill.textContent = h.state || "unknown";
    title.append(label, statePill);

    const meta = document.createElement("div");
    meta.className = "meta";
    const bits = [HEALTH_LABEL[h.last_status] ?? h.last_status];
    if (typeof h.last_http_status === "number") bits.push(`HTTP ${h.last_http_status}`);
    if (typeof retailer.selectedProductIds === "number") bits.push(`${retailer.selectedProductIds} IDs`);
    bits.push(`checked ${formatAgo(h.last_check_ts)}`);
    bits.push(`last ok ${formatAgo(h.last_success_ts)}`);
    if (h.last_items_found) bits.push(`${h.last_items_found} rows`);
    meta.textContent = bits.filter(Boolean).join(" / ");

    card.append(title, meta);
    if (h.last_detail) {
      const detail = document.createElement("div");
      detail.className = "meta health-detail";
      detail.textContent = h.last_detail.length > 180 ? `${h.last_detail.slice(0, 177)}...` : h.last_detail;
      detail.title = h.last_detail;
      card.appendChild(detail);
    }
    root.appendChild(card);
  }
}

function renderRecentRestocks(rows = []) {
  const root = qs("#recentRestocks");
  clear(root);
  qs("#restockCount").textContent = String(rows.length);
  if (!rows.length) {
    const note = document.createElement("div");
    note.className = "meta";
    note.textContent = "Nothing seen in stock yet. History builds as scans run.";
    root.appendChild(note);
    return;
  }
  for (const r of rows) {
    const item = document.createElement("div");
    item.className = "restock";
    const title = document.createElement("strong");
    title.textContent = r.productName || r.productKey;
    const meta = document.createElement("div");
    meta.className = "meta";
    const where = r.storeId && r.storeId !== "_online_" ? `store ${r.storeId}` : "online";
    meta.textContent = `${r.retailerName || r.retailer} / ${where} / seen ${formatAgo(r.lastInStockTs)} / ${r.inStockCount}x`;
    item.append(title, meta);
    root.appendChild(item);
  }
}

function renderStatus(payload) {
  const config = payload.config || {};
  const runner = payload.runner || {};
  const preserveConfigInputs = configIsBeingEdited();
  const configLabel = config.configMissing ? "example config loaded; save config.yaml to run scanners" : "config.yaml loaded";
  const okLabel = payload.ok ? "ready" : "needs attention";
  qs("#statusText").textContent = `${okLabel} | ${configLabel}`;
  renderSummary(payload.summary || {}, payload.coverage || {});
  renderActionQueue(payload.workQueue || []);
  renderCoverage(payload.coverage || {});
  renderHealth(payload.health || [], payload.retailers || []);
  renderRecentRestocks(payload.recentRestocks || []);
  renderRunner(runner, config);
  renderStoreDiagnostics(runner.storeDiagnostics || [], config);
  renderProducts(payload.products || []);
  renderMarketWatch(payload.products || []);
  renderProductIdOptions(payload.retailers || [], payload.products || []);
  const runnerBoard = runner.stockBoard || [];
  renderStockBoard(runnerBoard);
  if (!preserveConfigInputs) {
    fillConfig(config);
    renderRetailers(payload.retailers || []);
  }
  renderErrors(payload.errors || [], runner.warnings || []);
  if (!runnerBoard.length && Object.keys(runner.stores || {}).length) {
    renderStores(runner.stores || {});
  } else {
    renderStores({});
  }
  renderAlerts(runner.lastAlerts || []);
  renderLog(runner);
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
    renderErrors(payload.errors || [], payload.warnings || []);
    const board = payload.stockBoard || payload.runner?.stockBoard || [];
    renderStockBoard(board);
    if (!board.length) {
      renderStores(payload.stores || payload.runner?.stores || {});
    } else {
      renderStores({});
    }
    renderAlerts(payload.alerts || payload.runner?.lastAlerts || []);
    renderLog(payload);
    if (payload.coverage) renderCoverage(payload.coverage);
    if (payload.summary || payload.coverage) renderSummary(payload.summary || {}, payload.coverage || {});
    if (payload.workQueue) renderActionQueue(payload.workQueue);
    if (payload.products) {
      renderProducts(payload.products);
      renderMarketWatch(payload.products);
      renderProductIdOptions(payload.retailers || Object.values(state.retailers), payload.products);
    }
    if (payload.storeDiagnostics || payload.runner?.storeDiagnostics) {
      renderStoreDiagnostics(payload.storeDiagnostics || payload.runner?.storeDiagnostics || [], {
        routeRadiusMiles: Number(qs("#routeRadiusMiles").value),
      });
    }
    if (payload.health) renderHealth(payload.health, payload.retailers || Object.values(state.retailers));
    if (payload.recentRestocks) renderRecentRestocks(payload.recentRestocks);
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

qs("#productIdForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = qs("#idSaveStatus");
  status.textContent = "";
  const payload = await runAction(
    "/api/product-id",
    {
      retailer: qs("#idRetailer").value,
      productKey: qs("#idProduct").value,
      urlOrId: qs("#idValue").value,
    },
    false,
  );
  if (payload.ok) {
    status.textContent = payload.message || "Product ID saved.";
    qs("#idValue").value = "";
    renderStatus(payload.currentStatus || (await api("/api/status")));
  } else {
    status.textContent = (payload.errors || ["Could not save product ID."])[0];
  }
});

qs("#refreshBtn").addEventListener("click", refresh);
qs("#safeDemoBtn").addEventListener("click", () => runAction("/api/safe-demo", {}, false));
qs("#dryRunBtn").addEventListener("click", () => runAction("/api/dry-run", {}, false));
qs("#scanOnceBtn").addEventListener("click", () => runAction("/api/scan-once", { notify: false }, false));
qs("#startBtn").addEventListener("click", () => runAction("/api/start", { notify: true }));
qs("#stopBtn").addEventListener("click", () => runAction("/api/stop"));

refresh();
setInterval(refresh, 5000);
