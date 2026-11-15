// --- 5. RENDER HOME METRICS ---
function renderHomeMetrics() {
  const totalTrials = appData.trials.length;
  const avgCollapse = (appData.trials.reduce((acc, t) => acc + Number(t.collapseTurn || 0), 0) / (totalTrials || 1)).toFixed(1);
  const totalIllegal = appData.trials.reduce((acc, t) => acc + Number(t.illegalMovesCount || 0), 0);
  const totalCredits = appData.trials.reduce((acc, t) => acc + Number(t.creditsBurned || 0), 0).toFixed(2);

  const metrics = [
    {
      label: "Total Trials Logged",
      value: totalTrials,
      sub: "Across 4 deterministic games",
      icon: "swords",
      accent: "text-wood-walnut"
    },
    {
      label: "Mean Collapse Horizon",
      value: `Turn ${avgCollapse}`,
      sub: "Onset of coordinate drift",
      icon: "flame",
      accent: "text-wood-terracotta"
    },
    {
      label: "Illegal Moves Recorded",
      value: totalIllegal,
      sub: "Phantom spawns & teleports",
      icon: "alert-triangle",
      accent: "text-wood-amber"
    },
    {
      label: "API Credits Burned",
      value: `$${totalCredits}`,
      sub: "Multi-agent token overhead",
      icon: "coins",
      accent: "text-wood-espresso"
    }
  ];

  const grid = document.getElementById("home-metrics-grid");
  grid.innerHTML = metrics.map(m => `
    <div class="bg-cream-card border border-cream-border rounded-2xl p-5 flex items-start justify-between shadow-sm">
      <div>
        <span class="text-xs font-mono uppercase text-wood-umber">${m.label}</span>
        <div class="font-serif text-3xl font-bold ${m.accent} mt-1">${m.value}</div>
        <p class="text-xs text-wood-umber mt-1">${m.sub}</p>
      </div>
      <div class="p-2.5 rounded-xl bg-cream-bg border border-cream-border ${m.accent}">
        <i data-lucide="${m.icon}" class="w-5 h-5"></i>
      </div>
    </div>
  `).join("");

}
