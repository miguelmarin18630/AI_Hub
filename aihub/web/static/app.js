"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  user: null,
  providers: [],
  models: [],
  projects: [],
  settings: null,
  category: "code",
  providerFilter: null,
  search: "",
  filter: "all",
  sort: "price-asc",
  selected: null,
  project: "",
  messages: [],
  busy: false,
  generating: false,
  controller: null,
  filePath: "",
};

/* ------------------------------------------------------------------ util */

function esc(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function fmtSize(bytes) {
  if (!bytes) return "";
  if (bytes >= 1024 * 1024 * 1024) return (bytes / 1024 / 1024 / 1024).toFixed(1) + " GB";
  if (bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + " MB";
  if (bytes >= 1024) return Math.round(bytes / 1024) + " KB";
  return bytes + " B";
}

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

function toast(message, kind = "") {
  const root = $("toast-root");
  const item = document.createElement("div");
  item.className = "toast " + kind;
  item.textContent = message;
  root.appendChild(item);
  setTimeout(() => item.remove(), 5000);
}

function showLoading(text) {
  closeModal();
  const root = $("modal-root");
  root.innerHTML = `
    <div class="loading-overlay">
      <div class="loading-card"><span class="spinner"></span><span>${esc(text)}</span></div>
    </div>`;
}

function hideLoading() {
  const overlay = document.querySelector(".loading-overlay");
  if (overlay) overlay.remove();
}

function openModal(html) {
  const root = $("modal-root");
  root.innerHTML = `<div class="modal-overlay"><div class="modal">${html}</div></div>`;
  const overlay = root.querySelector(".modal-overlay");
  overlay.addEventListener("mousedown", (event) => {
    if (event.target === overlay) closeModal();
  });
}

function closeModal() {
  $("modal-root").innerHTML = "";
}

function markdown(text) {
  let html = esc(text || "");
  html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_m, lang, code) => {
    return `<pre><code>${code.replace(/\n$/, "")}</code></pre>`;
  });
  html = html.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/__([^_\n]+)__/g, "<strong>$1</strong>");
  html = html.replace(/^\s*-\s+(.*)$/gm, "• $1");
  html = html.replace(/\n/g, "<br>");
  return html;
}

async function api(path, options = {}) {
  const opts = { method: options.method || "GET", credentials: "same-origin", headers: {} };
  if (options.body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(options.body);
  }
  const res = await fetch(path, opts);
  if (res.status === 401 && !/^\/api\/(login|state|setup)/.test(path)) {
    showLogin();
    throw new Error("Sesión caducada.");
  }
  const text = await res.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = { error: text }; }
  }
  if (!res.ok) throw new Error((data && data.error) || `Error ${res.status}`);
  return data;
}

/* ------------------------------------------------------------------ login */

function showLogin(mode = "login") {
  $("app").hidden = true;
  $("login-screen").hidden = false;
  $("setup-view").hidden = mode !== "setup";
  $("login-view").hidden = mode !== "login";
  $("login-error").hidden = true;
  if (mode === "login") $("login-name").focus();
  else $("setup-password").focus();
}

function loginError(message) {
  const box = $("login-error");
  box.textContent = message;
  box.hidden = false;
}

async function doAuth(path, payload) {
  try {
    const data = await api(path, { method: "POST", body: payload });
    state.user = data.user;
    startApp();
  } catch (exc) {
    loginError(exc.message);
  }
}

async function boot() {
  try {
    const data = await api("/api/state");
    if (!data.setup_required) {
      try {
        const me = await api("/api/me");
        state.user = me.user;
        startApp();
        return;
      } catch {
        /* sin sesión: se muestra el login */
      }
    }
    showLogin(data.setup_required ? "setup" : "login");
  } catch (exc) {
    showLogin("login");
    loginError("No se pudo conectar con el servidor.");
  }
}

/* ------------------------------------------------------------------ inicio */

async function startApp() {
  $("login-screen").hidden = true;
  $("app").hidden = false;
  $("btn-admin").hidden = state.user.role !== "admin";
  $("btn-user").textContent = state.user.name;
  const prefs = JSON.parse(localStorage.getItem("aihub.web") || "{}");
  state.category = prefs.category || "code";
  state.sort = prefs.sort || "price-asc";
  state.filter = prefs.filter || "all";
  state.providerFilter = prefs.provider || null;
  $("sort").value = state.sort;
  $("filter").value = state.filter;
  syncTabs();
  bindEvents();
  await loadCatalog();
  await loadFiles();
  restoreConversation();
  const savedProject = localStorage.getItem("aihub.project");
  if (savedProject && (state.projects || []).some((item) => item.id === savedProject)) {
    state.project = savedProject;
    renderProjectChip();
    await loadFiles();
  }
}

function savePrefs() {
  localStorage.setItem(
    "aihub.web",
    JSON.stringify({
      category: state.category,
      sort: state.sort,
      filter: state.filter,
      provider: state.providerFilter,
    })
  );
}

function syncTabs() {
  document.querySelectorAll("#tabs .tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.category === state.category);
  });
}

function bindEvents() {
  if (state.eventsBound) return;
  state.eventsBound = true;

  document.querySelectorAll("#tabs .tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.category = btn.dataset.category;
      savePrefs();
      syncTabs();
      renderProviders();
      renderModels();
    });
  });

  $("provider-current").addEventListener("click", () => {
    const menu = $("provider-menu");
    menu.hidden = !menu.hidden;
  });
  document.addEventListener("click", (event) => {
    const select = $("provider-select");
    if (!select || select.contains(event.target)) return;
    $("provider-menu").hidden = true;
  });

  $("model-list").addEventListener("click", (event) => {
    const row = event.target.closest(".model-row");
    if (!row) return;
    const model = state.models.find((item) => item.uid === row.dataset.uid && item.provider === row.dataset.provider);
    if (model) selectModel(model);
  });

  $("search").addEventListener("input", debounce((event) => {
    state.search = event.target.value.trim().toLowerCase();
    renderModels();
  }, 150));

  $("filter").addEventListener("change", (event) => {
    state.filter = event.target.value;
    savePrefs();
    renderModels();
  });

  $("sort").addEventListener("change", (event) => {
    state.sort = event.target.value;
    savePrefs();
    renderModels();
  });

  $("btn-collapse").addEventListener("click", () => $("layout").classList.add("collapsed"));
  $("rail-open").addEventListener("click", () => $("layout").classList.remove("collapsed"));

  $("btn-refresh").addEventListener("click", () => refreshCatalog(true));
  $("btn-project").addEventListener("click", openProjects);
  $("btn-settings").addEventListener("click", () => openSettings("main"));
  $("btn-admin").addEventListener("click", () => openSettings("admin"));
  $("btn-user").addEventListener("click", () => openSettings("account"));
  $("btn-logout").addEventListener("click", logout);

  $("btn-clear").addEventListener("click", clearChat);
  $("btn-send").addEventListener("click", sendChat);
  $("prompt").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendChat();
    }
  });
  $("btn-stop").addEventListener("click", () => {
    if (state.controller) state.controller.abort();
  });

  $("btn-generate").addEventListener("click", generate);
  $("btn-gen-cancel").addEventListener("click", () => {
    if (state.controller) state.controller.abort();
  });

  $("btn-file-up").addEventListener("click", () => {
    if (!state.filePath) return;
    const parts = state.filePath.split("/").filter(Boolean);
    parts.pop();
    state.filePath = parts.join("/");
    loadFiles();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeModal();
  });
}

/* ------------------------------------------------------------------ catálogo */

async function loadCatalog() {
  const data = await api("/api/catalog");
  state.providers = data.providers || [];
  state.models = data.models || [];
  state.projects = data.projects || [];
  state.settings = data.settings || state.settings;
  state.favorites = data.favorites || [];
  const preferred = localStorage.getItem("aihub.model");
  if (preferred) {
    const [provider, uid] = preferred.split("::");
    const found = state.models.find((item) => item.provider === provider && item.uid === uid);
    if (found) selectModel(found);
  }
  renderProviders();
  renderModels();
  renderProjectChip();
  if (!state.models.length) {
    await refreshCatalog(false);
  }
}

async function refreshCatalog(showOverlay) {
  if (state.busy) return;
  if (showOverlay) showLoading("Actualizando catálogos…");
  try {
    const data = await api("/api/refresh", { method: "POST", body: {} });
    state.providers = data.providers || state.providers;
    state.models = data.models || state.models;
    renderProviders();
    renderModels();
    const errors = data.errors || {};
    const keys = Object.keys(errors);
    if (keys.length) {
      keys.slice(0, 3).forEach((key) => toast(`${key}: ${errors[key]}`, "error"));
    } else {
      toast("Catálogos actualizados.", "ok");
    }
  } catch (exc) {
    toast(exc.message, "error");
  } finally {
    hideLoading();
  }
}

function categoryMatches(model) {
  if (state.category === "code") return model.category === "code";
  return model.category === "image" || model.category === "video";
}

function renderProviders() {
  const current = $("provider-current");
  const menu = $("provider-menu");
  if (!current || !menu) return;
  const counts = {};
  for (const model of state.models) {
    if (!categoryMatches(model)) continue;
    counts[model.provider] = counts[model.provider] || { total: 0, free: 0 };
    counts[model.provider].total += 1;
    if (model.free) counts[model.provider].free += 1;
  }
  const active = state.providers.find((item) => item.id === state.providerFilter);
  current.innerHTML = active
    ? `<span class="provider-logo" style="background:${esc(active.color)}">${esc(active.glyph)}</span> <span>${esc(active.name)}</span>`
    : "Todos los proveedores";
  menu.innerHTML = "";
  const all = document.createElement("button");
  all.type = "button";
  all.className = "provider-item" + (state.providerFilter ? "" : " active");
  all.innerHTML = `<span class="provider-logo" style="background:var(--panel-3)">＋</span> <span>Todos los proveedores</span>`;
  all.addEventListener("click", () => selectProvider(null));
  menu.appendChild(all);
  for (const provider of state.providers) {
    const count = counts[provider.id];
    if (!count) continue;
    const item = document.createElement("button");
    item.type = "button";
    item.className = "provider-item" + (state.providerFilter === provider.id ? " active" : "");
    item.innerHTML = `<span class="provider-logo" style="background:${esc(provider.color)}">${esc(provider.glyph)}</span>
      <span>${esc(provider.name)}</span> <small>${count.free}/${count.total}</small>`;
    item.addEventListener("click", () => selectProvider(provider.id));
    menu.appendChild(item);
  }
}

function selectProvider(id) {
  state.providerFilter = id || null;
  savePrefs();
  renderProviders();
  renderModels();
  $("provider-menu").hidden = true;
}

function renderModels() {
  const root = $("model-list");
  root.innerHTML = "";
  let items = state.models.filter(categoryMatches);
  if (state.filter === "favorites") {
    items = items.filter((item) => state.favorites.includes(`${item.provider}:${item.uid}`));
  } else {
    if (state.providerFilter) items = items.filter((item) => item.provider === state.providerFilter);
    if (state.filter === "free") items = items.filter((item) => item.free);
    if (state.filter === "paid") items = items.filter((item) => !item.free);
  }
  if (state.search) {
    items = items.filter((item) =>
      (item.name + " " + item.uid + " " + (item.desc || "")).toLowerCase().includes(state.search)
    );
  }
  items.sort((a, b) => {
    if (state.sort === "name") return a.name.localeCompare(b.name);
    if (state.sort === "context") return (b.context || 0) - (a.context || 0);
    if (state.sort === "price-desc") return (b.effective_price ?? Infinity) - (a.effective_price ?? Infinity);
    if (a.free !== b.free) return a.free ? -1 : 1;
    return (a.effective_price ?? Infinity) - (b.effective_price ?? Infinity);
  });
  $("model-count").textContent = `${items.length} modelo${items.length === 1 ? "" : "s"}`;
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "model-list-empty";
    empty.textContent = "No hay modelos. Pulsa «Actualizar» para descargar el catálogo.";
    root.appendChild(empty);
    return;
  }
  const frag = document.createDocumentFragment();
  for (const model of items) {
    const row = document.createElement("div");
    row.className = "model-row" + (state.selected && state.selected.uid === model.uid ? " selected" : "");
    row.dataset.uid = model.uid;
    row.dataset.provider = model.provider;
    const priceClass = model.free ? "free" : (model.effective_price == null ? "unknown" : "");
    row.innerHTML = `
      <span class="model-glyph" style="color:${esc(model.provider_color)}">${esc(model.provider_glyph)}</span>
      <div class="model-main">
        <div class="model-name">${esc(model.name)}</div>
        <div class="model-sub">${esc(model.provider_name)} · ${esc(model.info_text)}</div>
      </div>
      <div class="model-price ${priceClass}">${esc(model.price_text)}</div>`;
    frag.appendChild(row);
  }
  root.appendChild(frag);
}

function selectModel(model) {
  state.selected = model;
  localStorage.setItem("aihub.model", `${model.provider}::${model.uid}`);
  renderModels();
  renderDetail();
  renderCenterMode();
  const toolsBox = $("tools-label");
  if (model.category !== "code") toolsBox.style.opacity = "0.45";
  else toolsBox.style.opacity = "1";
}

function renderDetail() {
  const root = $("model-detail");
  const model = state.selected;
  if (!model) {
    root.innerHTML = `<small class="empty">Elige un modelo para ver su precio y detalles.</small>`;
    $("usage-text").textContent = "Elige un modelo para ver su consumo.";
    $("quota-text").textContent = "";
    return;
  }
  const isFavorite = state.favorites.includes(`${model.provider}:${model.uid}`);
  root.innerHTML = `
    <div class="detail-title">
      <span class="model-glyph" style="color:${esc(model.provider_color)}">${esc(model.provider_glyph)}</span>
      <div>
        <strong>${esc(model.name)}</strong>
        <div class="usage-dim">${esc(model.provider_name)} · ${esc(model.uid)}</div>
      </div>
    </div>
    <div class="detail-price ${model.free ? "" : "paid"}">${esc(model.price_text)}</div>
    <div class="usage-dim">${esc(model.price_detail)}</div>
    <div class="detail-desc">${esc(model.desc || "")}</div>
    <div class="detail-tags">${tags}</div>
    <div class="usage-dim" style="margin-top:8px">${esc(model.context_text)} contexto · ${esc(model.unit)}</div>
    <div style="margin-top:10px">
      <button id="btn-favorite" class="btn ghost small">${isFavorite ? "★ Favorito" : "☆ Favorito"}</button>
    </div>`;
  $("btn-favorite").addEventListener("click", toggleFavorite);  $("conv-title").textContent = model.name;
  $("conv-sub").textContent = `${model.provider_name} · ${model.price_text}`;
  loadUsage();
}

async function toggleFavorite() {
  const model = state.selected;
  if (!model) return;
  const key = `${model.provider}:${model.uid}`;
  const isFavorite = state.favorites.includes(key);
  try {
    const data = await api("/api/favorites", { method: "POST", body: { provider: model.provider, uid: model.uid, favorite: !isFavorite } });
    state.favorites = data.favorites || state.favorites;
    renderDetail();
    renderModels();
  } catch (exc) {
    toast(exc.message, "error");
  }
}

function renderCenterMode() {
  const model = state.selected;
  const isGenerator = model && (model.category === "image" || model.category === "video");
  $("composer").hidden = !!isGenerator;
  $("generator").hidden = !isGenerator;
  if (!isGenerator) return;
  const isVideo = model.category === "video";
  $("gen-title").textContent = isVideo ? "Generar vídeo" : "Generar imagen";
  $("gen-model").textContent = `${model.name} · ${model.price_text}`;
  $("gen-duration-wrap").hidden = !isVideo;
  $("gen-resolution-wrap").hidden = !isVideo;
  $("gen-aspect").hidden = false;
  $("gen-result").innerHTML = "";
}

/* ------------------------------------------------------------------ chat */

function addMessage(kind, text) {
  const root = $("messages");
  const item = document.createElement("div");
  item.className = "msg " + kind;
  if (kind === "user" || kind === "assistant") {
    item.innerHTML = `<div class="msg-body"></div>`;
    item.querySelector(".msg-body").innerHTML = kind === "user" ? esc(text) : markdown(text);
  } else {
    item.textContent = text;
  }
  root.appendChild(item);
  root.scrollTop = root.scrollHeight;
  return item;
}

function saveConversation() {
  try {
    localStorage.setItem("aihub.conversation", JSON.stringify(state.messages || []));
  } catch (exc) {
    /* ignore */
  }
}

function restoreConversation() {
  let messages = [];
  try {
    messages = JSON.parse(localStorage.getItem("aihub.conversation") || "[]");
  } catch {
    messages = [];
  }
  if (!Array.isArray(messages) || !messages.length) return;
  state.messages = messages.filter((item) => item && (item.role === "user" || item.role === "assistant") && typeof item.content === "string");
  $("messages").innerHTML = "";
  for (const item of state.messages) {
    addMessage(item.role, item.content);
  }
}

async function sendChat() {
  if (state.busy) return;
  const model = state.selected;
  const text = $("prompt").value.trim();
  if (!model) { toast("Elige un modelo primero.", "error"); return; }
  if (!text) return;
  state.messages.push({ role: "user", content: text });
  addMessage("user", text);
  $("prompt").value = "";
  $("prompt").style.height = "auto";

  const assistant = addMessage("assistant", "");
  const body = assistant.querySelector(".msg-body");
  body.innerHTML = `<span class="cursor"></span>`;
  let answer = "";
  state.busy = true;
  state.controller = new AbortController();
  $("btn-send").disabled = true;
  $("btn-stop").hidden = false;
  $("chat-status").textContent = "Pensando…";

  try {
    const project = state.project;
    const res = await fetch("/api/chat", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: model.provider,
        uid: model.uid,
        category: model.category,
        project: project,
        use_tools: $("use-tools").checked && !!project,
        messages: state.messages,
      }),
      signal: state.controller.signal,
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `Error ${res.status}`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const cursor = () => `<span class="cursor"></span>`;
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      let index;
      while ((index = buffer.indexOf("\n\n")) !== -1) {
        const raw = buffer.slice(0, index);
        buffer = buffer.slice(index + 2);
        for (const line of raw.split("\n")) {
          if (!line.startsWith("data:")) continue;
          let event;
          try { event = JSON.parse(line.slice(5).trim()); } catch { continue; }
          if (event.type === "delta") {
            answer += event.text;
            body.innerHTML = markdown(answer) + cursor();
            $("messages").scrollTop = $("messages").scrollHeight;
          } else if (event.type === "tool") {
            addMessage("tool", `${event.status === "error" ? "⚠" : event.status === "done" ? "✓" : "⚙"} ${event.name} · ${event.detail || ""}`);
          } else if (event.type === "done") {
            $("chat-status").textContent = `Listo en ${event.elapsed}s · ${event.usage_text || "sin consumo"}`;
            if (event.usage_text) loadUsage();
            loadFiles();
          } else if (event.type === "error") {
            addMessage("error", event.message);
          }
        }
      }
    }
    if (answer.trim()) {
      state.messages.push({ role: "assistant", content: answer });
      body.innerHTML = markdown(answer);
    } else if (!state.messages.some((item) => item.role === "assistant")) {
      assistant.remove();
    }
  } catch (exc) {
    if (exc.name !== "AbortError") {
      addMessage("error", exc.message);
      $("chat-status").textContent = "";
    } else {
      if (answer.trim()) {
        state.messages.push({ role: "assistant", content: answer });
        body.innerHTML = markdown(answer);
      }
      $("chat-status").textContent = "Detenido.";
    }
  } finally {
    state.busy = false;
    state.controller = null;
    $("btn-send").disabled = false;
    $("btn-stop").hidden = true;
    saveConversation();
  }
}

/* ------------------------------------------------------------------ imagen y vídeo */

async function generate() {
  const model = state.selected;
  if (!model || state.generating) return;
  const prompt = $("gen-prompt").value.trim();
  if (!prompt) { toast("Describe lo que quieres generar.", "error"); return; }
  state.generating = true;
  state.controller = new AbortController();
  $("btn-generate").disabled = true;
  $("btn-gen-cancel").hidden = false;
  $("gen-result").innerHTML = `<span class="gen-note">Generando… esto puede tardar unos segundos.</span>`;
  try {
    const payload = {
      provider: model.provider,
      uid: model.uid,
      prompt,
      aspect_ratio: $("gen-aspect").value || null,
    };
    let data;
    if (model.category === "video") {
      payload.duration = $("gen-duration").value ? Number($("gen-duration").value) : null;
      payload.resolution = $("gen-resolution").value || null;
      data = await api("/api/video", { method: "POST", body: payload });
    } else {
      data = await api("/api/image", { method: "POST", body: payload });
    }
    const note = data.cost ? ` · coste $${Number(data.cost).toFixed(6)}` : "";
    $("gen-result").innerHTML =
      (model.category === "video"
        ? `<video controls autoplay src="${esc(data.url)}"></video>`
        : `<img src="${esc(data.url)}" alt="Imagen generada">`) +
      `<div class="gen-note">Generado${note}</div>`;
    loadUsage();
  } catch (exc) {
    $("gen-result").innerHTML = `<span class="gen-note" style="color:var(--red)">${esc(exc.message)}</span>`;
  } finally {
    state.generating = false;
    state.controller = null;
    $("btn-generate").disabled = false;
    $("btn-gen-cancel").hidden = true;
  }
}

/* ------------------------------------------------------------------ proyectos y archivos */

function renderProjectChip() {
  const active = (state.projects || []).find((item) => item.active);
  const label = active ? (active.root ? "Todos los proyectos" : active.name) : "Proyecto";
  $("btn-project").textContent = label;
}

function openProjects() {
  const rows = (state.projects || []).map((item) => `
    <tr>
      <td>${esc(item.name)}</td>
      <td>${esc((item.kinds || []).join(", ") || "carpeta")}</td>
      <td>${item.count}</td>
      <td class="user-actions">
        ${item.active ? '<span class="usage-dim">actual</span>' : `<button class="btn ghost mini" data-select="${esc(item.id)}">Usar</button>`}
      </td>
    </tr>`).join("");
  openModal(`
    <div class="modal-head"><h2>Proyectos</h2><button class="icon-btn" data-close>Cerrar ✕</button></div>
    <section>
      <p class="hint">Cada cuenta tiene sus propios proyectos, dentro de su carpeta personal del servidor.</p>
      <table class="user-table"><thead><tr><th>Proyecto</th><th>Tipo</th><th>Elementos</th><th></th></tr></thead>
      <tbody>${rows || '<tr><td colspan="4">Todavía no hay proyectos.</td></tr>'}</tbody></table>
      <div class="modal-row">
        <input id="new-project" type="text" placeholder="Nombre del proyecto nuevo">
        <button id="btn-create-project" class="btn primary" style="flex:0 0 auto">Crear</button>
      </div>
      <div class="modal-actions">
        <button class="btn ghost" data-select="">Sin proyecto</button>
      </div>
    </section>`);
  document.querySelector("#modal-root").addEventListener("click", async (event) => {
    if (event.target.closest("[data-close]")) { closeModal(); return; }
    const select = event.target.closest("[data-select]");
    if (!select) return;
    await chooseProject(select.dataset.select);
    closeModal();
  });
  $("btn-create-project").addEventListener("click", async () => {
    const name = $("new-project").value.trim();
    if (!name) return;
    try {
      await api("/api/project/create", { method: "POST", body: { name } });
      toast("Proyecto creado.", "ok");
      await loadCatalog();
      closeModal();
    } catch (exc) { toast(exc.message, "error"); }
  });
}

async function chooseProject(id) {
  try {
    const data = await api("/api/project/select", { method: "POST", body: { name: id } });
    state.project = id;
    state.filePath = "";
    localStorage.setItem("aihub.project", id);
    await loadCatalog();
    await loadFiles();
    toast(data.workdir ? `Proyecto: ${data.name}` : "Sin proyecto.", "ok");
  } catch (exc) {
    toast(exc.message, "error");
  }
}

async function loadFiles() {
  const list = $("file-list");
  if (!state.project) {
    list.innerHTML = `<small class="usage-dim">Elige un proyecto para ver sus archivos.</small>`;
    $("files-project").textContent = "Sin proyecto";
    $("btn-file-up").hidden = true;
    return;
  }
  try {
    const data = await api(`/api/files?project=${encodeURIComponent(state.project)}&path=${encodeURIComponent(state.filePath)}`);
    const entries = data.entries || [];
    $("files-project").textContent = state.filePath ? `Carpeta: ${state.filePath}` : "Raíz del proyecto";
    $("btn-file-up").hidden = !state.filePath;
    if (!entries.length) {
      list.innerHTML = `<small class="usage-dim">Carpeta vacía.</small>`;
      return;
    }
    list.innerHTML = entries.map((item) => `
      <div class="file-row" data-path="${esc(item.path)}" data-dir="${item.dir ? "1" : "0"}">
        <span>${item.dir ? "📁" : "📄"}</span>
        <span class="file-name">${esc(item.name)}</span>
        <small>${item.dir ? "carpeta" : fmtSize(item.size)}</small>
      </div>`).join("");
  } catch (exc) {
    list.innerHTML = `<small class="usage-dim">${esc(exc.message)}</small>`;
  }
}

$("file-list")?.addEventListener?.("click", async (event) => {
  const row = event.target.closest(".file-row");
  if (!row || !state.project) return;
  if (row.dataset.dir === "1") {
    state.filePath = row.dataset.path;
    await loadFiles();
    return;
  }
  try {
    const data = await api(`/api/file?project=${encodeURIComponent(state.project)}&path=${encodeURIComponent(row.dataset.path)}`);
    openModal(`
      <div class="modal-head"><h2>${esc(data.path)}</h2><button class="icon-btn" data-close>Cerrar ✕</button></div>
      <section class="file-viewer"><pre>${esc(data.text)}</pre></section>`);
  } catch (exc) {
    toast(exc.message, "error");
  }
});

/* ------------------------------------------------------------------ ajustes y usuarios */

async function openSettings(tab = "main") {
  let settings;
  let users = [];
  try {
    settings = await api("/api/settings");
    if (state.user.role === "admin") users = (await api("/api/admin/users")).users || [];
  } catch (exc) {
    toast(exc.message, "error");
    return;
  }
  const providerRows = (settings.custom_providers || []).map((item) => `
    <tr>
      <td><span style="color:${esc(item.color)}">${esc(item.glyph)}</span> ${esc(item.name)}</td>
      <td>${esc(item.base)}</td>
      <td>${item.key_set ? "guardada" : "sin clave"}</td>
      <td class="user-actions">
        <button class="btn ghost mini" data-edit-provider="${esc(item.id)}">Editar</button>
        <button class="btn danger mini" data-delete-provider="${esc(item.id)}">Quitar</button>
      </td>
    </tr>`).join("");
  const userRows = users.map((item) => `
    <tr>
      <td>${esc(item.name)}</td><td>${esc(item.id)}</td><td>${esc(item.role)}</td>
      <td class="user-actions">
        <button class="btn ghost mini" data-reset-user="${esc(item.id)}">Contraseña</button>
        ${item.id === state.user.id ? "" : `<button class="btn danger mini" data-delete-user="${esc(item.id)}">Borrar</button>`}
      </td>
    </tr>`).join("");
  openModal(`
    <div class="modal-head"><h2>Ajustes</h2><button class="icon-btn" data-close>Cerrar ✕</button></div>
    <section id="settings-main">
      <h3>OPENROUTER</h3>
      <p class="hint">Clave guardada: ${settings.openrouter_set ? "sí" + (settings.openrouter_hint ? " (…" + esc(settings.openrouter_hint) + ")" : "") : "no"}</p>
      <div class="modal-row">
        <input id="openrouter-key" type="password" placeholder="Pega la clave (o déjala vacía para no cambiarla)" autocomplete="off">
        <button id="btn-check-key" class="btn ghost" style="flex:0 0 auto">Comprobar</button>
        <button id="btn-save-key" class="btn primary" style="flex:0 0 auto">Guardar</button>
        <button id="btn-clear-key" class="btn danger" style="flex:0 0 auto">Quitar</button>
      </div>
    </section>
    <section>
      <h3>PROVEEDORES PROPIOS</h3>
      <p class="hint">APIs compatibles con OpenAI (OpenAI, Gemini, Groq, DeepSeek, Mistral, Together o un servidor local).</p>
      <table class="user-table"><thead><tr><th>Nombre</th><th>URL</th><th>Clave</th><th></th></tr></thead>
      <tbody>${providerRows || '<tr><td colspan="4">Sin proveedores propios.</td></tr>'}</tbody></table>
      <div class="modal-row">
        <select id="preset" class="select">
          ${(settings.presets || []).map((item) => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join("")}
        </select>
        <input id="custom-name" type="text" placeholder="Nombre">
        <input id="custom-base" type="text" placeholder="URL base (p. ej. https://api.openai.com/v1)">
        <input id="custom-key" type="password" placeholder="Clave" autocomplete="off">
      </div>
      <div class="modal-row">
        <label class="check"><input type="checkbox" id="cat-code" checked> Programación</label>
        <label class="check"><input type="checkbox" id="cat-media"> Imagen y vídeo</label>
        <button id="btn-add-provider" class="btn primary" style="flex:0 0 auto">Añadir y leer modelos</button>
      </div>
    </section>
    <section>
      <h3>MI CUENTA</h3>
      <div class="modal-row">
        <input id="pw-current" type="password" placeholder="Contraseña actual" autocomplete="off">
        <input id="pw-new" type="password" placeholder="Contraseña nueva (mínimo 8)" autocomplete="off">
        <button id="btn-change-password" class="btn primary" style="flex:0 0 auto">Cambiar</button>
      </div>
    </section>
    ${state.user.role === "admin" ? `
    <section id="settings-admin">
      <h3>USUARIOS DE LA FAMILIA</h3>
      <table class="user-table"><thead><tr><th>Nombre</th><th>Usuario</th><th>Rol</th><th></th></tr></thead>
      <tbody>${userRows || '<tr><td colspan="4">Sin usuarios.</td></tr>'}</tbody></table>
      <div class="modal-row">
        <input id="new-user-name" type="text" placeholder="Nombre">
        <input id="new-user-id" type="text" placeholder="Usuario (para entrar)">
        <input id="new-user-password" type="password" placeholder="Contraseña" autocomplete="off">
        <label class="check" style="flex:0 0 auto"><input type="checkbox" id="new-user-admin"> Admin</label>
        <button id="btn-add-user" class="btn primary" style="flex:0 0 auto">Crear</button>
      </div>
    </section>` : ""}
  `);
  if (tab === "admin") $("settings-admin")?.scrollIntoView();
  if (tab === "account") $("pw-current")?.focus();

  const root = $("modal-root");
  root.querySelector("[data-close]").addEventListener("click", closeModal);
  root.querySelector("#btn-save-key").addEventListener("click", async () => {
    try {
      await api("/api/settings", { method: "POST", body: { openrouter_api_key: $("openrouter-key").value } });
      toast("Clave guardada.", "ok");
      await openSettings("main");
    } catch (exc) { toast(exc.message, "error"); }
  });
  root.querySelector("#btn-clear-key").addEventListener("click", async () => {
    try {
      await api("/api/settings", { method: "POST", body: { openrouter_api_key: "__clear__" } });
      toast("Clave eliminada.", "ok");
      await openSettings("main");
    } catch (exc) { toast(exc.message, "error"); }
  });
  root.querySelector("#btn-check-key").addEventListener("click", async () => {
    const key = $("openrouter-key").value.trim();
    if (!key) { toast("Pega una clave para comprobarla.", "error"); return; }
    try {
      const data = await api("/api/settings", { method: "POST", body: { openrouter_api_key: key } });
      void data;
      const result = await api("/api/check", { method: "POST", body: {} });
      const bits = ["Clave válida"];
      if (result.free_remaining != null) bits.push(`${result.free_remaining} gratis hoy`);
      if (result.remaining != null) bits.push(`saldo $${result.remaining}`);
      toast(bits.join(" · "), "ok");
    } catch (exc) { toast(exc.message, "error"); }
  });
  root.querySelector("#btn-add-provider").addEventListener("click", async () => {
    const preset = $("preset").value;
    const body = {
      preset,
      name: $("custom-name").value.trim(),
      base: $("custom-base").value.trim(),
      key: $("custom-key").value,
      categories: [$("cat-code").checked ? "code" : "", $("cat-media").checked ? "media" : ""].filter(Boolean),
    };
    try {
      const data = await api("/api/custom/add", { method: "POST", body });
      toast(data.error ? `Añadido, pero: ${data.error}` : "Proveedor añadido.", "ok");
      await loadCatalog();
      await openSettings("main");
    } catch (exc) { toast(exc.message, "error"); }
  });
  root.querySelector("#btn-change-password").addEventListener("click", async () => {
    try {
      await api("/api/account/password", {
        method: "POST",
        body: { current: $("pw-current").value, new: $("pw-new").value },
      });
      toast("Contraseña cambiada.", "ok");
      closeModal();
    } catch (exc) { toast(exc.message, "error"); }
  });
  root.querySelector("#btn-add-user").addEventListener("click", async () => {
    try {
      await api("/api/admin/users", {
        method: "POST",
        body: {
          name: $("new-user-id").value.trim() || $("new-user-name").value.trim(),
          password: $("new-user-password").value,
          role: $("new-user-admin").checked ? "admin" : "user",
        },
      });
      toast("Usuario creado.", "ok");
      await openSettings("admin");
    } catch (exc) { toast(exc.message, "error"); }
  });
  root.addEventListener("click", async (event) => {
    const editProvider = event.target.closest("[data-edit-provider]");
    if (editProvider) {
      closeModal();
      await openEditProvider(editProvider.dataset.editProvider);
      return;
    }
    const deleteProvider = event.target.closest("[data-delete-provider]");
    if (deleteProvider) {
      try {
        await api("/api/custom/delete", { method: "POST", body: { id: deleteProvider.dataset.deleteProvider } });
        await loadCatalog();
        await openSettings("main");
      } catch (exc) { toast(exc.message, "error"); }
      return;
    }
    const resetUser = event.target.closest("[data-reset-user]");
    if (resetUser) {
      const password = prompt("Nueva contraseña para " + resetUser.dataset.resetUser + " (mínimo 8):");
      if (!password) return;
      try {
        await api("/api/admin/users/password", { method: "POST", body: { id: resetUser.dataset.resetUser, password } });
        toast("Contraseña actualizada.", "ok");
      } catch (exc) { toast(exc.message, "error"); }
      return;
    }
    const deleteUser = event.target.closest("[data-delete-user]");
    if (deleteUser) {
      if (!confirm("¿Borrar este usuario? Sus proyectos y claves se conservarán en disco.")) return;
      try {
        await api("/api/admin/users/delete", { method: "POST", body: { id: deleteUser.dataset.deleteUser } });
        await openSettings("admin");
      } catch (exc) { toast(exc.message, "error"); }
    }
  });
}

async function openEditProvider(id) {
  const settings = await api("/api/settings").catch(() => null);
  const provider = (settings?.custom_providers || []).find((item) => item.id === id);
  if (!provider) { toast("Proveedor no encontrado.", "error"); return; }
  openModal(`
    <div class="modal-head"><h2>Editar proveedor</h2><button class="icon-btn" data-close>Cerrar ✕</button></div>
    <section>
      <div class="modal-row">
        <input id="edit-name" type="text" value="${esc(provider.name)}" placeholder="Nombre">
        <input id="edit-base" type="text" value="${esc(provider.base)}" placeholder="URL base">
        <input id="edit-key" type="password" placeholder="Nueva clave (vacío = no cambiar)" autocomplete="off">
      </div>
      <div class="modal-row">
        <label class="check"><input type="checkbox" id="edit-cat-code" ${ (provider.categories||[]).includes("code") ? "checked" : "" }> Programación</label>
        <label class="check"><input type="checkbox" id="edit-cat-media" ${ (provider.categories||[]).includes("media") ? "checked" : "" }> Imagen y vídeo</label>
        <button id="btn-save-provider" class="btn primary" style="flex:0 0 auto">Guardar y leer modelos</button>
      </div>
    </section>`);
  document.querySelector("#modal-root [data-close]").addEventListener("click", closeModal);
  document.querySelector("#btn-save-provider").addEventListener("click", async () => {
    try {
      const data = await api("/api/custom/update", {
        method: "POST",
        body: {
          id: provider.id,
          name: document.querySelector("#edit-name").value.trim(),
          base: document.querySelector("#edit-base").value.trim(),
          key: document.querySelector("#edit-key").value,
          categories: [document.querySelector("#edit-cat-code").checked ? "code" : "", document.querySelector("#edit-cat-media").checked ? "media" : ""].filter(Boolean),
        },
      });
      toast(data.error ? `Guardado, pero: ${data.error}` : "Proveedor actualizado.", "ok");
      await loadCatalog();
      closeModal();
      await openSettings("main");
    } catch (exc) {
      toast(exc.message, "error");
    }
  });
}

/* ------------------------------------------------------------------ sesión */

async function logout() {
  try { await api("/api/logout", { method: "POST", body: {} }); } catch {}
  localStorage.removeItem("aihub.model");
  location.reload();
}

/* ------------------------------------------------------------------ arranque */

document.addEventListener("DOMContentLoaded", () => {
  $("login-view").addEventListener("submit", (event) => {
    event.preventDefault();
    doAuth("/api/login", { name: $("login-name").value, password: $("login-password").value });
  });
  $("setup-view").addEventListener("submit", (event) => {
    event.preventDefault();
    doAuth("/api/setup", { name: $("setup-name").value, password: $("setup-password").value });
  });
  boot();
});
