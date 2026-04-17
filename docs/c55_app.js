const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

const LAST_REASON_KEY = "c55_last_zv_reason";
const studentDrawerWrap = document.getElementById("studentDrawerWrap");
const adminDrawerWrap = document.getElementById("adminDrawerWrap");
const mainWrap = document.getElementById("mainWrap");
const toast = document.getElementById("toast");
const params = new URLSearchParams(window.location.search);
const isAdmin = params.get("is_admin") === "1";
const now = new Date();
const toDate = (d) => d.toISOString().slice(0, 10);
const toTime = (d) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
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

document.getElementById("df").value = toDate(now);
document.getElementById("tf").value = toTime(now);
const end = new Date(now.getTime() + 60 * 60 * 1000);
document.getElementById("dt").value = toDate(end);
document.getElementById("tt").value = toTime(end);

document.getElementById("profileSnapshotBtn").onclick = () => sendAction("c55_student_webapp", "profile_snapshot");
document.getElementById("profileUpdateBtn").onclick = () => {
  const field = document.getElementById("pfField").value;
  const value = document.getElementById("pfValue").value.trim();
  if (!value) return tg.showAlert("Введіть нове значення.");
  sendAction("c55_student_webapp", "profile_update_request", { field, value });
};
document.getElementById("zvCityBtn").onclick = () => sendAction("c55_student_webapp", "zv_city_submit");
document.getElementById("lastReasonBtn").onclick = () => {
  const r = localStorage.getItem(LAST_REASON_KEY) || "";
  if (!r) return tg.showAlert("Немає збереженої причини.");
  document.getElementById("zvReason").value = r;
};
document.getElementById("zvDormBtn").onclick = () => {
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
};
document.getElementById("schShowBtn").onclick = async () => {
  const week = document.getElementById("schWeek").value;
  const day = document.getElementById("schDay").value;
  const box = document.getElementById("scheduleResult");
  box.textContent = "Завантаження...";
  try {
    const resp = await fetch(`./schedule_cache.json?v=20260417o`, { cache: "no-store" });
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
};
document.getElementById("customReqBtn").onclick = () => {
  const text = document.getElementById("customReqText").value.trim();
  if (!text) return tg.showAlert("Введіть текст запиту.");
  sendAction("c55_student_webapp", "custom_request", { text });
};
document.getElementById("pollBtn").onclick = () => {
  const question = document.getElementById("pollQ").value.trim();
  const options = document.getElementById("pollOpts").value
    .split("\n")
    .map(x => x.trim())
    .filter(Boolean);
  if (!question || options.length < 2 || options.length > 10) {
    return tg.showAlert("Потрібне питання і 2-10 варіантів.");
  }
  sendAction("c55_student_webapp", "custom_poll_submit", { question, options });
};

document.getElementById("adminStatsBtn").onclick = () => sendAction("c55_admin_webapp", "admin_stats");
document.getElementById("adminRequestsOverviewBtn").onclick = () => sendAction("c55_admin_webapp", "admin_requests_overview");
document.getElementById("adminCityReportBtn").onclick = () => sendAction("c55_admin_webapp", "admin_city_report");
document.getElementById("approveAllCityBtn").onclick = () => sendAction("c55_admin_webapp", "admin_confirm_all", { category: "zv_city" });
document.getElementById("approveAllDormBtn").onclick = () => sendAction("c55_admin_webapp", "admin_confirm_all", { category: "zv_dorm" });
document.getElementById("adminToggleBtn").onclick = () => {
  const key = document.getElementById("adminToggleKey").value;
  sendAction("c55_admin_webapp", "admin_toggle_auto", { key });
};
document.getElementById("adminPingBtn").onclick = () => sendAction("c55_admin_webapp", "admin_ping_all");
document.getElementById("adminPollsListBtn").onclick = () => sendAction("c55_admin_webapp", "admin_polls_list");
document.getElementById("adminClosePollsBtn").onclick = () => sendAction("c55_admin_webapp", "admin_close_all_polls");
document.getElementById("adminUsersOverviewBtn").onclick = () => sendAction("c55_admin_webapp", "admin_users_overview");
document.getElementById("adminHistoryRecentBtn").onclick = () => sendAction("c55_admin_webapp", "admin_history_recent");
document.getElementById("adminAutoStatusBtn").onclick = () => sendAction("c55_admin_webapp", "admin_auto_status");
document.querySelectorAll("#pAdminPollCreate [data-poll]").forEach((btn) => {
  btn.onclick = () => sendAction("c55_admin_webapp", "admin_create_poll", { poll_type: btn.dataset.poll });
});
document.getElementById("adminCustomPollBtn").onclick = () => {
  const question = document.getElementById("adminPollQ").value.trim();
  const options = document.getElementById("adminPollOpts").value
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);
  if (!question || options.length < 2 || options.length > 10) {
    return tg.showAlert("Потрібне питання і 2-10 варіантів.");
  }
  sendAction("c55_admin_webapp", "admin_custom_poll_create", { question, options });
};
document.getElementById("adminSchShowBtn").onclick = async () => {
  const week = document.getElementById("adminSchWeek").value;
  const day = document.getElementById("adminSchDay").value;
  const box = document.getElementById("adminScheduleResult");
  box.textContent = "Завантаження...";
  try {
    const resp = await fetch(`./schedule_cache.json?v=20260417o`, { cache: "no-store" });
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
};
