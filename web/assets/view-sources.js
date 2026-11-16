// --- 8. RENDER SOURCES & LEVY ARCHIVES ---
function filterSources(cat) {
    activeSourceFilter = cat;
    document.querySelectorAll(".src-filter-btn").forEach(btn => {
    btn.className = "src-filter-btn px-3.5 py-1.5 rounded-lg text-xs font-mono font-semibold bg-cream-card text-wood-umber border border-cream-border hover:bg-cream-hover";
    });
    const activeBtn = document.getElementById(`src-btn-${cat}`);
    if (activeBtn) {
    activeBtn.className = "src-filter-btn px-3.5 py-1.5 rounded-lg text-xs font-mono font-semibold bg-wood-walnut text-cream-bg";
    }
    renderSources();
}

function renderSources() {
    const container = document.getElementById("sources-grid-container");
    const filtered = appData.sources.filter(s => activeSourceFilter === "ALL" || s.category === activeSourceFilter);

    const categoryLabels = {
    levy_video: { label: "Levy's Videos (GothamChess)", icon: "video", color: "text-wood-terracotta bg-wood-terracotta/10 border-wood-terracotta/30" },
    interview: { label: "Interview Recording", icon: "mic", color: "text-wood-amber bg-wood-amber/15 border-wood-amber/30" },
    bibliography: { label: "Annotated Bibliography", icon: "book-marked", color: "text-wood-walnut bg-wood-walnut/10 border-wood-walnut/30" }
    };

    container.innerHTML = filtered.map(s => {
    const meta = categoryLabels[s.category] || categoryLabels.bibliography;
    return `
        <div class="bg-cream-card border border-cream-border rounded-2xl p-6 flex flex-col justify-between space-y-4 shadow-sm hover:border-wood-walnut/50 transition-all">
        <div class="space-y-3">
            <div class="flex items-center justify-between gap-2">
            <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-mono font-semibold border ${meta.color}">
                <i data-lucide="${meta.icon}" class="w-3.5 h-3.5"></i> ${meta.label}
            </span>
            <span class="text-xs font-mono text-wood-umber">${escapeHTML(s.badge)}</span>
            </div>
            <h3 class="font-serif text-xl font-bold text-wood-espresso leading-snug">
            ${escapeHTML(s.title)}
            </h3>
            <p class="text-sm text-wood-umber leading-relaxed bg-cream-bg p-3.5 rounded-xl border border-cream-border">
            ${escapeHTML(s.notes)}
            </p>
        </div>
        <div class="pt-2 flex items-center justify-between">
            <span class="text-[11px] font-mono text-wood-umber truncate max-w-[65%]">${escapeHTML(s.url)}</span>
            <a href="${escapeHTML(s.url)}" target="_blank" rel="noopener noreferrer" class="px-3.5 py-1.5 rounded-lg bg-wood-walnut hover:bg-wood-walnutHover text-cream-bg text-xs font-mono font-semibold transition-colors inline-flex items-center gap-1.5">
            Open Source <i data-lucide="external-link" class="w-3.5 h-3.5"></i>
            </a>
        </div>
        </div>
    `;
    }).join("");
    if (window.lucide && typeof window.lucide.createIcons === "function") {
        window.lucide.createIcons();
    }
}
