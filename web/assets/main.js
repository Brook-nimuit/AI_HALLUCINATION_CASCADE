function switchTab(tabId) {
  document.querySelectorAll(".tab-section").forEach(sec => sec.classList.add("hidden"));
  const target = document.getElementById(`tab-${tabId}`);
  if (target) target.classList.remove("hidden");

  document.querySelectorAll(".nav-btn").forEach(btn => {
    if (btn.id === "nav-admin") return;
    btn.className = "nav-btn px-3.5 py-2 rounded-lg text-sm font-semibold transition-all whitespace-nowrap flex items-center gap-1.5 text-wood-umber hover:text-wood-espresso hover:bg-cream-card";
  });

  const activeBtn = document.getElementById(`nav-${tabId}`);
  if (activeBtn && tabId !== "admin") {
    activeBtn.className = "nav-btn px-3.5 py-2 rounded-lg text-sm font-semibold transition-all whitespace-nowrap flex items-center gap-1.5 bg-wood-walnut text-cream-bg shadow-sm";
  }

  window.scrollTo({ top: 0, behavior: "smooth" });
  lucide.createIcons();
}

function refreshAllViews() {
  renderHomeMetrics();
  renderComparison();
  renderSources();
  lucide.createIcons();
}

window.addEventListener("DOMContentLoaded", () => {
  checkAdminAccess();
  refreshAllViews();
  switchTab("home");
});