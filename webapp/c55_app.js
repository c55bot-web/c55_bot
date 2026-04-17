const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

const LAST_REASON_KEY = "c55_last_zv_reason";
const drawerWrap = document.getElementById("studentDrawerWrap");
const toast = document.getElementById("toast");
const launchMode = new URLSearchParams(window.location.search).get("mode") || "student";
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
document.getElementById("closeDrawer").onclick = () => drawerWrap.classList.remove("open");
drawerWrap.addEventListener("click", (e) => { if (e.target === drawerWrap) drawerWrap.classList.remove("open"); });

const panels = Array.from(document.querySelectorAll(".panel"));
const openPanel = (id) => {
  panels.forEach(p => p.classList.toggle("show", p.id === id));
};
document.querySelectorAll(".menu button[data-panel]").forEach(btn => {
  btn.onclick = () => openPanel(btn.dataset.panel);
});
openPanel("pProfile");

if (launchMode === "student") {
  drawerWrap.classList.add("open");
} else if (launchMode === "admin") {
  showToast("Адмін-панель буде підключена наступним етапом.");
}

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
document.getElementById("schSendBtn").onclick = () => {
  sendAction("schedule_to_chat", {
    week: document.getElementById("schWeek").value,
    day: document.getElementById("schDay").value
  });
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
