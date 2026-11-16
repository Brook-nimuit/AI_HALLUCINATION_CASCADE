function switchTab(tabId) {
  document.querySelectorAll(".tab-section").forEach(sec => sec.classList.add("hidden"));
  const target = document.getElementById(`tab-${tabId}`);
  if (target) target.classList.remove("hidden");

  document.querySelectorAll(".nav-btn").forEach(btn => {
    if (btn.id === "nav-admin") return;
    btn.className = "nav-btn px-3.5 py-2 rounded-lg text-sm font-semibold transition-all whitespace-nowrap flex items-center gap-1.5 text-wood-umber hover:text-wood-espresso hover:bg-cream-card";
  });

  const activeBtn = document.getElementById(`nav-${tabId}`);
  if (activeBtn && activeBtn.classList.contains("floater-pill")) {
    document.querySelectorAll(".floater-pill").forEach(btn => {
      btn.classList.toggle("active-pill", btn === activeBtn);
    });
  } else if (activeBtn && tabId !== "admin") {
    activeBtn.className = "nav-btn px-3.5 py-2 rounded-lg text-sm font-semibold transition-all whitespace-nowrap flex items-center gap-1.5 bg-wood-walnut text-cream-bg shadow-sm";
  }

  window.scrollTo({ top: 0, behavior: "smooth" });
  if (window.lucide && typeof window.lucide.createIcons === "function") {
    window.lucide.createIcons();
  }
}

function selectFloaterTab(tabId) {
  switchTab(tabId);
}

function refreshAllViews() {
  renderHomeMetrics();
  renderComparison();
  renderSources();
  if (window.lucide && typeof window.lucide.createIcons === "function") {
    window.lucide.createIcons();
  }
}

window.addEventListener("DOMContentLoaded", () => {
  checkAdminAccess();
  refreshAllViews();
  switchTab("home");
});