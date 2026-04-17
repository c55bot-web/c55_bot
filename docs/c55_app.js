const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

const LAST_REASON_KEY = "c55_last_zv_reason";
const drawerWrap = document.getElementById("studentDrawerWrap");
const toast = document.getElementById("toast");
const ADMIN_IDS = new Set([1412535952, 1968855371, 857180040, 1023209296]);
const userId = tg.initDataUnsafe?.user?.id || 0;
const isAdmin = ADMIN_IDS.has(Number(userId));
const now = new Date();
const toDate = (d) => d.toISOString().slice(0, 10);
const toTime = (d) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
const showToast = (text) => {
  toast.textContent = text;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 1800);
};
const sendAction = (action, payload = {}) => {
  const body = { kind: "c55_student_webapp", action, ...payload };
  tg.sendData(JSON.stringify(body));
  if (tg.HapticFeedback?.notificationOccurred) tg.HapticFeedback.notificationOccurred("success");
  showToast("Відправлено");
};

document.getElementById("openStudent").onclick = () => drawerWrap.classList.add("open");
document.querySelector(".card.admin").onclick = () => {
  if (!isAdmin) {
    tg.showAlert("Адмін-панель доступна лише адміністраторам.");
    return;
  }
  drawerWrap.classList.add("open");
  showToast("Адмін-режим скоро буде доданий.");
};
document.getElementById("closeDrawer").onclick = () => drawerWrap.classList.remove("open");
drawerWrap.addEventListener("click", (e) => { if (e.target === drawerWrap) drawerWrap.classList.remove("open"); });

const panels = Array.from(document.querySelectorAll(".panel"));
const openPanel = (id, sourceButton = null) => {
  const target = panels.find((p) => p.id === id);
  if (!target) return;
  panels.forEach((p) => p.classList.remove("show"));
  if (sourceButton) {
    sourceButton.insertAdjacentElement("afterend", target);
  }
  target.classList.add("show");
};
document.querySelectorAll(".menu button[data-panel]").forEach(btn => {
  btn.onclick = () => openPanel(btn.dataset.panel, btn);
});
const firstMenuBtn = document.querySelector(".menu button[data-panel]");
openPanel("pProfile", firstMenuBtn);
drawerWrap.classList.add("open");

document.getElementById("df").value = toDate(now);
document.getElementById("tf").value = toTime(now);
const end = new Date(now.getTime() + 60 * 60 * 1000);
document.getElementById("dt").value = toDate(end);
document.getElementById("tt").value = toTime(end);

document.getElementById("profileSnapshotBtn").onclick = () => sendAction("profile_snapshot");
document.getElementById("profileUpdateBtn").onclick = () => {
  const field = document.getElementById("pfField").value;
  const value = document.getElementById("pfValue").value.trim();
  if (!value) return tg.showAlert("Введіть нове значення.");
  sendAction("profile_update_request", { field, value });
};
document.getElementById("zvCityBtn").onclick = () => sendAction("zv_city_submit");
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
  sendAction("zv_dorm_submit", { date_from, time_from, date_to, time_to, address_mode, address, reason });
};
document.getElementById("schShowBtn").onclick = async () => {
  const week = document.getElementById("schWeek").value;
  const day = document.getElementById("schDay").value;
  const box = document.getElementById("scheduleResult");
  box.textContent = "Завантаження...";
  try {
    const resp = await fetch(`./schedule_cache.json?v=20260417c`, { cache: "no-store" });
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
  sendAction("custom_request", { text });
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
  sendAction("custom_poll_submit", { question, options });
};
