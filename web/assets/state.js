const STORAGE_KEY = "HALLUCINATION_CASCADE_PORTAL_DATA_V1";
let appData = loadAppData();
let activeComparisonGame = "Chess";
let activeSourceFilter = "ALL";
let simulatedAdmin = false;

function loadAppData() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) return JSON.parse(saved);
  } catch (e) {
    console.warn("Could not read localStorage, falling back to default dataset.", e);
  }
  return JSON.parse(JSON.stringify(DEFAULT_DATA));
}

function saveAppData() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(appData));
  } catch (e) {
    console.warn("Could not save to localStorage.", e);
  }
  refreshAllViews();
}

function escapeHTML(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function showToast(message) {
  const box = document.getElementById("toast-box");
  document.getElementById("toast-message").textContent = message;
  box.classList.remove("hidden");
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => box.classList.add("hidden"), 3500);
}

function copyText(encodedStr, msg) {
  const text = decodeURIComponent(encodedStr);
  navigator.clipboard?.writeText(text).catch(() => {
    const tempInput = document.createElement("textarea");
    tempInput.value = text;
    document.body.appendChild(tempInput);
    tempInput.select();
    document.execCommand("copy");
    tempInput.remove();
  });
  showToast(msg);
}

function openQRModal() {
  const urlInput = document.getElementById("qr-url-input");
  if (!urlInput.value.trim() && /^https?:$/.test(window.location.protocol)) {
    urlInput.value = window.location.href.split(/[?#]/)[0];
  }
  updateQRUrl(urlInput.value);
  document.getElementById("qr-modal").classList.remove("hidden");
}

function closeQRModal() {
  document.getElementById("qr-modal").classList.add("hidden");
}

function updateQRUrl(val) {
  const image = document.getElementById("qr-image");
  const url = val.trim();
  if (!/^https?:\/\/\S+$/i.test(url)) {
    image.removeAttribute("src");
    image.classList.add("hidden");
    return;
  }
  image.src = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&color=2A1B12&bgcolor=FAF6F0&data=${encodeURIComponent(url)}`;
  image.classList.remove("hidden");
}

function copyPortalUrl() {
  const val = document.getElementById("qr-url-input").value;
  if (!/^https?:\/\/\S+$/i.test(val.trim())) {
    showToast("Enter your hosted project URL first.");
    return;
  }
  copyText(encodeURIComponent(val), "Portal URL copied to clipboard!");
}