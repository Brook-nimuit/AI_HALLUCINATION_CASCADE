// web/assets/view-comparison.js
// Loads cloud trial records from Supabase and renders the AI Models Comparison tab.

let liveComparisonData = [];

window.onLiveTrialsUpdated = function (trials) {
  liveComparisonData = buildComparisonFromTrials(trials);

  const banner = document.getElementById("data-status-banner");
  if (banner && liveComparisonData.length > 0) {
    banner.innerHTML =
      "<strong>Cloud research data:</strong> AI Models Performance Matrix synchronized with " +
      trials.length +
      " verified trial records.";
  }

  if (liveComparisonData.length > 0) {
    let foundMatch = false;
    for (let i = 0; i < liveComparisonData.length; i++) {
      if (
        liveComparisonData[i].game.toLowerCase() ===
        String(activeComparisonGame).toLowerCase()
      ) {
        foundMatch = true;
      }
    }
    if (!foundMatch) {
      activeComparisonGame = liveComparisonData[0].game;
    }
  }

  renderComparison();
};

function selectComparisonGame(game) {
  activeComparisonGame = game;
  renderComparison();
}

function createModelCardHtml(m) {
  const collapseDisplay =
    m.avgCollapseTurn !== null ? "Turn " + m.avgCollapseTurn : "No Collapse";
  const trialWord = m.totalGames === 1 ? "trial" : "trials";

  return `
    <div class="bg-cream-card border border-cream-border rounded-2xl p-6 flex flex-col justify-between space-y-5 shadow-sm hover:border-wood-walnut/50 transition-all">
      <div class="space-y-3">
        <div class="flex items-center justify-between">
          <span class="text-xs font-mono uppercase px-2.5 py-0.5 rounded bg-cream-bg border border-cream-border text-wood-umber">${escapeHTML(m.provider)}</span>
          <span class="text-[11px] font-mono text-wood-umber">${m.totalGames} ${trialWord}</span>
        </div>
        <h4 class="font-serif text-2xl font-bold text-wood-espresso">${escapeHTML(m.name)}</h4>
        <div class="p-3 rounded-xl bg-cream-bg border border-cream-border space-y-1">
          <span class="text-[10px] font-mono uppercase text-wood-terracotta font-semibold">Most frequent collapse</span>
          <p class="text-xs font-semibold text-wood-espresso">${escapeHTML(m.archetype)}</p>
        </div>
      </div>

      <div class="space-y-3 pt-3 border-t border-cream-border">
        <div class="bg-cream-bg p-3 rounded-xl border border-cream-border text-center">
          <div class="text-[10px] font-mono text-wood-umber uppercase">Avg Collapse</div>
          <div class="font-serif text-xl font-bold text-wood-espresso">${collapseDisplay}</div>
        </div>

        <div class="space-y-1">
          <div class="flex justify-between text-[11px] font-mono">
            <span class="text-wood-sage font-semibold">Valid Completion: ${m.validRate}%</span>
            <span class="text-wood-terracotta font-semibold">Cascade: ${m.collapseRate}%</span>
          </div>
          <div class="w-full h-2.5 rounded-full bg-cream-bg overflow-hidden flex border border-cream-border">
            <div style="width: ${m.validRate}%" class="bg-wood-sage h-full"></div>
            <div style="width: ${m.collapseRate}%" class="bg-wood-terracotta h-full"></div>
          </div>
        </div>
      </div>
    </div>
  `;
}

function renderComparison() {
  const pillsContainer = document.getElementById("comparison-game-pills");
  const bannerContainer = document.getElementById("comparison-game-banner");
  const modelsGrid = document.getElementById("comparison-models-grid");
  if (!pillsContainer || !bannerContainer || !modelsGrid) return;

  const dataset =
    liveComparisonData.length > 0 ? liveComparisonData : appData.modelsComparison;
  if (!dataset || dataset.length === 0) return;

  // 1. Build game selector pills
  let pillsHtml = "";
  let currentGameObj = dataset[0];

  for (let i = 0; i < dataset.length; i++) {
    const g = dataset[i];
    const isActive =
      g.game.toLowerCase() === String(activeComparisonGame).toLowerCase();
    if (isActive) currentGameObj = g;

    const btnClass = isActive
      ? "bg-wood-walnut text-cream-bg shadow-sm"
      : "bg-cream-card text-wood-umber border border-cream-border hover:bg-cream-hover";

    pillsHtml += `<button onclick="selectComparisonGame('${escapeHTML(g.game)}')" class="px-4 py-2 rounded-xl text-xs font-mono font-semibold transition-all ${btnClass}">${escapeHTML(g.game)}</button>`;
  }
  pillsContainer.innerHTML = pillsHtml;

  // 2. Build game header banner
  bannerContainer.innerHTML = `
    <div class="flex items-center gap-3">
      <div class="w-9 h-9 rounded-lg bg-wood-walnut/15 text-wood-walnut flex items-center justify-center font-serif font-bold">
        ${escapeHTML(currentGameObj.game[0])}
      </div>
      <div>
        <h3 class="font-serif font-bold text-wood-espresso text-lg">${escapeHTML(currentGameObj.game)} State Benchmark</h3>
        <p class="text-xs text-wood-umber">${escapeHTML(currentGameObj.description)}</p>
      </div>
    </div>
    <span class="text-xs font-mono px-3 py-1 rounded-full bg-cream-bg border border-cream-border text-wood-walnut">
      ${currentGameObj.models.length} Architectures Evaluated
    </span>
  `;

  // 3. Build model cards
  let cardsHtml = "";
  for (let i = 0; i < currentGameObj.models.length; i++) {
    cardsHtml += createModelCardHtml(currentGameObj.models[i]);
  }
  modelsGrid.innerHTML = cardsHtml;
}

// Auto-fetch cloud records from Supabase when the page loads
async function initCloudComparison() {
  if (typeof fetchAllCatalogTrials !== "function") return;
  try {
    const cloudTrials = await fetchAllCatalogTrials();
    if (Array.isArray(cloudTrials) && cloudTrials.length > 0) {
      window.onLiveTrialsUpdated(cloudTrials);
    }
  } catch (err) {
    console.warn("Could not load Supabase comparison data, using defaults:", err);
  }
}

document.addEventListener("DOMContentLoaded", initCloudComparison);