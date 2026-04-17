const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

const LAST_REASON_KEY = "c55_last_zv_reason";
const studentDrawerWrap = document.getElementById("studentDrawerWrap");
const adminDrawerWrap = document.getElementById("adminDrawerWrap");
const mainWrap = document.querySelector(".app");
const toast = document.getElementById("toast");
const params = new URLSearchParams(window.location.search);
const isAdmin = params.get("is_admin") === "1";
const apiBaseRaw = params.get("api") || "";
let API_BASE = "";
if (apiBaseRaw) {
  try {
    API_BASE = decodeURIComponent(apiBaseRaw).replace(/\/$/, "");
  } catch {
    API_BASE = apiBaseRaw.replace(/\/$/, "");
  }
}
const now = new Date();
const toDate = (d) => d.toISOString().slice(0, 10);
const toTime = (d) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
const bindClick = (id, handler) => {
  const el = document.getElementById(id);
  if (el) el.onclick = handler;
};
const showToast = (text) => {
  if (!toast) return;
  toast.textContent = text;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 1800);
};
const sendAction = (kind, action, payload = {}) => {
  const body = { kind, action, ...payload };
  tg.sendData(JSON.stringify(body));
  if (tg.HapticFeedback?.notificationOccurred) tg.HapticFeedback.notificationOccurred("success");
  showToast("Відправлено");
};

const INIT_DATA_STORAGE_KEY = "c55_tg_init_data";

const decodeURIComponentSafe = (s) => {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
};

/** Повертає сирий initData рядок для валідації на бекенді (підпис hash). */
const getTelegramInitData = () => {
  const w = window.Telegram?.WebApp;
  const direct = (w && w.initData) ? String(w.initData) : "";
  if (direct) {
    try {
      sessionStorage.setItem(INIT_DATA_STORAGE_KEY, direct);
    } catch {
      // ignore
    }
    return direct;
  }

  const cached = (() => {
    try {
      return sessionStorage.getItem(INIT_DATA_STORAGE_KEY) || "";
    } catch {
      return "";
    }
  })();
  if (cached) return cached;

  const parseFromHashOrSearch = (raw) => {
    if (!raw) return "";
    const trimmed = raw.startsWith("#") ? raw.slice(1) : raw;
    const hp = new URLSearchParams(trimmed);
    const embedded = hp.get("tgWebAppData");
    if (embedded) return decodeURIComponentSafe(embedded);
    // Інколи initData приходить як «query string» прямо у фрагменті без ключа tgWebAppData
    if (trimmed.includes("hash=") && trimmed.includes("user=")) return trimmed;
    return "";
  };

  let v = parseFromHashOrSearch(window.location.hash);
  if (!v) {
    v = (() => {
      const sp = new URLSearchParams(window.location.search);
      const embedded = sp.get("tgWebAppData");
      return embedded ? decodeURIComponentSafe(embedded) : "";
    })();
  }
  if (v) {
    try {
      sessionStorage.setItem(INIT_DATA_STORAGE_KEY, v);
    } catch {
      // ignore
    }
  }
  return v;
};

const fetchAdminHistory = async () => {
  const box = document.getElementById("adminHistoryResult");
  if (!API_BASE) {
    if (box) {
      box.textContent =
        "Щоб «Історія» не закривала Web App, потрібен HTTPS API endpoint.\n\n" +
        "Додай у .env змінну C55_WEBAPP_API_URL (публічний URL до бота-API) і nginx/proxy на /api/c55/* → порт C55_WEBAPP_API_PORT.";
    }
    return tg.showAlert("Не налаштовано C55_WEBAPP_API_URL (API для WebApp). Без цього Telegram завжди закриє app на sendData().");
  }
  const initData = getTelegramInitData();
  if (!initData) {
    return tg.showAlert(
      "Немає Telegram initData.\n\n" +
        "Відкрий Web App саме кнопкою в Telegram (Reply keyboard).\n" +
        "Якщо все одно порожньо — зроби /refresh і відкрий ще раз.\n\n" +
        "RU: Нет initData — открой Mini App кнопкой в Telegram, затем /refresh."
    );
  }
  if (box) box.textContent = "Завантаження...";
  try {
    const url = `${API_BASE}/api/c55/admin/history`;
    const resp = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Telegram-Web-App-Init-Data": initData,
      },
      body: JSON.stringify({ limit_days: 7 }),
      cache: "no-store",
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || !data.ok) {
      throw new Error(data.error || `http_${resp.status}`);
    }
    if (box) {
      // HTML з бекенду — показуємо як plain text, щоб не XSS і не ламати Telegram WebView
      const tmp = document.createElement("div");
      tmp.innerHTML = String(data.text || "");
      box.textContent = tmp.textContent || String(data.text || "");
    }
    showToast("Готово");
  } catch (e) {
    if (box) box.textContent = `Помилка завантаження історії: ${e?.message || e}`;
  }
};

const bindDrawer = (drawerWrap, menuSelector, defaultPanelId) => {
  if (!drawerWrap) return () => {};
  drawerWrap.addEventListener("click", (e) => { if (e.target === drawerWrap) drawerWrap.classList.remove("open"); });

  const menuButtons = Array.from(drawerWrap.querySelectorAll(`${menuSelector} button[data-panel]`));
  const panels = Array.from(drawerWrap.querySelectorAll(".panel"));
  const openPanel = (id, sourceButton = null) => {
    const target = panels.find((p) => p.id === id);
    if (!target) return;
    panels.forEach((p) => p.classList.remove("show"));
    if (sourceButton) sourceButton.insertAdjacentElement("afterend", target);
    target.classList.add("show");
  };
  menuButtons.forEach((btn) => {
    btn.onclick = () => openPanel(btn.dataset.panel, btn);
  });
  if (menuButtons.length) {
    openPanel(defaultPanelId, menuButtons[0]);
  }
  return openPanel;
};

const studentOpenPanel = bindDrawer(studentDrawerWrap, ".menu", "pProfile");
bindDrawer(adminDrawerWrap, ".menu", "pAdminApprovals");

const openStudentBtn = document.getElementById("openStudent");
if (openStudentBtn) openStudentBtn.onclick = () => {
  if (studentDrawerWrap) studentDrawerWrap.classList.add("open");
};
const openAdminBtn = document.getElementById("openAdmin");
if (openAdminBtn) openAdminBtn.onclick = () => {
  if (!isAdmin) {
    tg.showAlert("Адмін-панель доступна лише адміністраторам.");
    return;
  }
  if (adminDrawerWrap) adminDrawerWrap.classList.add("open");
};
const backToChooserFromStudent = document.getElementById("backToChooserFromStudent");
if (backToChooserFromStudent) backToChooserFromStudent.onclick = () => {
  if (studentDrawerWrap) studentDrawerWrap.classList.remove("open");
  if (mainWrap) mainWrap.classList.remove("hidden");
};
const backToChooserFromAdmin = document.getElementById("backToChooserFromAdmin");
if (backToChooserFromAdmin) backToChooserFromAdmin.onclick = () => {
  if (adminDrawerWrap) adminDrawerWrap.classList.remove("open");
  if (mainWrap) mainWrap.classList.remove("hidden");
};

const df = document.getElementById("df");
const tf = document.getElementById("tf");
const dt = document.getElementById("dt");
const tt = document.getElementById("tt");
if (df) df.value = toDate(now);
if (tf) tf.value = toTime(now);
const end = new Date(now.getTime() + 60 * 60 * 1000);
if (dt) dt.value = toDate(end);
if (tt) tt.value = toTime(end);

bindClick("profileSnapshotBtn", () => sendAction("c55_student_webapp", "profile_snapshot"));
bindClick("profileUpdateBtn", () => {
  const field = document.getElementById("pfField").value;
  const value = document.getElementById("pfValue").value.trim();
  if (!value) return tg.showAlert("Введіть нове значення.");
  sendAction("c55_student_webapp", "profile_update_request", { field, value });
});
bindClick("zvCityBtn", () => sendAction("c55_student_webapp", "zv_city_submit"));
bindClick("lastReasonBtn", () => {
  const r = localStorage.getItem(LAST_REASON_KEY) || "";
  if (!r) return tg.showAlert("Немає збереженої причини.");
  document.getElementById("zvReason").value = r;
});
bindClick("zvDormBtn", () => {
  const date_from = document.getElementById("df").value;
  const time_from = document.getElementById("tf").value;
  const date_to = document.getElementById("dt").value;
  const time_to = document.getElementById("tt").value;
  const address_mode = document.getElementById("addrMode").value;
  const address = document.getElementById("addrManual").value.trim();
  const reason = document.getElementById("zvReason").value.trim();
  if (!date_from || !time_from || !date_to || !time_to || !reason) {
    return tg.showAlert("Заповніть дату/час і причину.");
  }
  if (address_mode === "manual" && !address) {
    return tg.showAlert("Введіть адресу вручну.");
  }
  localStorage.setItem(LAST_REASON_KEY, reason);
  sendAction("c55_student_webapp", "zv_dorm_submit", { date_from, time_from, date_to, time_to, address_mode, address, reason });
});
bindClick("schShowBtn", async () => {
  const week = document.getElementById("schWeek").value;
  const day = document.getElementById("schDay").value;
  const box = document.getElementById("scheduleResult");
  if (!box) return;
  box.textContent = "Завантаження...";
  try {
    const resp = await fetch(`./schedule_cache.json?v=20260417t`, { cache: "no-store" });
    if (!resp.ok) throw new Error("cache-miss");
    const cache = await resp.json();
    const key = week === "next" ? "next" : "current";
    const dayRows = (cache?.[key] || {})[day] || [];
    if (!dayRows.length) {
      box.textContent = `На ${day} пар немає.`;
      return;
    }
    const header = cache?.meta?.week_labels?.[key] || (key === "next" ? "Наступний тиждень" : "Поточний тиждень");
    const lines = [`${header}, ${day}`];
    for (const row of dayRows) {
      const pair = row.pair_num ?? "?";
      const text = row.lesson_text || "";
      lines.push(`${pair} пара: ${text}`);
    }
    box.textContent = lines.join("\n");
  } catch (e) {
    box.textContent = "Не вдалося завантажити розклад. Спробуйте пізніше.";
  }
});
bindClick("customReqBtn", () => {
  const text = document.getElementById("customReqText").value.trim();
  if (!text) return tg.showAlert("Введіть текст запиту.");
  sendAction("c55_student_webapp", "custom_request", { text });
});
bindClick("pollBtn", () => {
  const question = document.getElementById("pollQ").value.trim();
  const options = document.getElementById("pollOpts").value
    .split("\n")
    .map(x => x.trim())
    .filter(Boolean);
  if (!question || options.length < 2 || options.length > 10) {
    return tg.showAlert("Потрібне питання і 2-10 варіантів.");
  }
  sendAction("c55_student_webapp", "custom_poll_submit", { question, options });
});

bindClick("adminStatsBtn", () => sendAction("c55_admin_webapp", "admin_stats"));
bindClick("adminRequestsOverviewBtn", () => sendAction("c55_admin_webapp", "admin_requests_overview"));
bindClick("adminPendingCityBtn", () => sendAction("c55_admin_webapp", "admin_pending_list", { category: "zv_city" }));
bindClick("adminPendingDormBtn", () => sendAction("c55_admin_webapp", "admin_pending_list", { category: "zv_dorm" }));
bindClick("adminPendingOtherBtn", () => sendAction("c55_admin_webapp", "admin_pending_list", { category: "other" }));
bindClick("adminCityReportBtn", () => sendAction("c55_admin_webapp", "admin_city_report"));
bindClick("approveAllCityBtn", () => sendAction("c55_admin_webapp", "admin_confirm_all", { category: "zv_city" }));
bindClick("approveAllDormBtn", () => sendAction("c55_admin_webapp", "admin_confirm_all", { category: "zv_dorm" }));
bindClick("adminApprovalApplyBtn", () => {
  const id = Number(document.getElementById("adminApprovalId").value.trim());
  const decision = document.getElementById("adminApprovalDecision").value;
  if (!Number.isInteger(id) || id <= 0) return tg.showAlert("Вкажіть коректний ID запиту.");
  sendAction("c55_admin_webapp", "admin_approval_apply", { approval_id: id, decision });
});
bindClick("adminToggleBtn", () => {
  const key = document.getElementById("adminToggleKey").value;
  sendAction("c55_admin_webapp", "admin_toggle_auto", { key });
});
bindClick("adminPingBtn", () => sendAction("c55_admin_webapp", "admin_ping_all"));
bindClick("adminPollsListBtn", () => sendAction("c55_admin_webapp", "admin_polls_list"));
bindClick("adminClosePollsBtn", () => sendAction("c55_admin_webapp", "admin_close_all_polls"));
bindClick("adminUsersOverviewBtn", () => sendAction("c55_admin_webapp", "admin_users_overview"));
bindClick("adminUsersListBtn", () => sendAction("c55_admin_webapp", "admin_users_list"));
bindClick("adminHistoryRecentBtn", () => {
  void fetchAdminHistory();
});
bindClick("adminAutoStatusBtn", () => sendAction("c55_admin_webapp", "admin_auto_status"));
document.querySelectorAll("#pAdminPollCreate [data-poll]").forEach((btn) => {
  btn.onclick = () => sendAction("c55_admin_webapp", "admin_create_poll", { poll_type: btn.dataset.poll });
});
bindClick("adminCustomPollBtn", () => {
  const question = document.getElementById("adminPollQ").value.trim();
  const options = document.getElementById("adminPollOpts").value
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);
  if (!question || options.length < 2 || options.length > 10) {
    return tg.showAlert("Потрібне питання і 2-10 варіантів.");
  }
  sendAction("c55_admin_webapp", "admin_custom_poll_create", { question, options });
});
bindClick("adminSchShowBtn", async () => {
  const week = document.getElementById("adminSchWeek").value;
  const day = document.getElementById("adminSchDay").value;
  const box = document.getElementById("adminScheduleResult");
  if (!box) return;
  box.textContent = "Завантаження...";
  try {
    const resp = await fetch(`./schedule_cache.json?v=20260417t`, { cache: "no-store" });
    if (!resp.ok) throw new Error("cache-miss");
    const cache = await resp.json();
    const key = week === "next" ? "next" : "current";
    const dayRows = (cache?.[key] || {})[day] || [];
    if (!dayRows.length) {
      box.textContent = `На ${day} пар немає.`;
      return;
    }
    const header = cache?.meta?.week_labels?.[key] || (key === "next" ? "Наступний тиждень" : "Поточний тиждень");
    const lines = [`${header}, ${day}`];
    for (const row of dayRows) {
      const pair = row.pair_num ?? "?";
      const text = row.lesson_text || "";
      lines.push(`${pair} пара: ${text}`);
    }
    box.textContent = lines.join("\n");
  } catch (e) {
    box.textContent = "Не вдалося завантажити розклад. Спробуйте пізніше.";
  }
});
bindClick("adminSchReportBtn", () => {
  const week = document.getElementById("adminSchWeek").value;
  sendAction("c55_admin_webapp", "admin_schedule_report", { week });
});
bindClick("adminSchClearBtn", () => {
  const week = document.getElementById("adminSchWeek").value;
  sendAction("c55_admin_webapp", "admin_schedule_clear", { week });
});
