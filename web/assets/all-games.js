// web/assets/all-games.js
// Renders 25 game cards per page from Supabase and powers the slide-up match overlay.

(function () {
  "use strict";

  const PAGE_SIZE = 25;
  const REPLAY_URLS = {
    chess: "/chess-replay/",
    checkers: "/checkers-replay/",
    uno: "/uno-replay/"
  };

  let allTrials = [];
  let currentPage = 0;

  function byId(id) {
    return document.getElementById(id);
  }

  function escapeHtml(val) {
    return String(val ?? "").replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function formatCatalogRow(row) {
    const rawId = String(row.trial_id || "");
    const parts = rawId.split("__");
    const runTag = parts.length >= 3 && parts[2] ? parts[2] : "Official Run";
    const shortTrial = parts.length >= 4 ? parts[3] : rawId;

    const statusRaw = String(row.status || "").toLowerCase();
    let cleanStatus = "invalid_or_illegal";
    if (statusRaw === "completed" || statusRaw === "complete") {
      cleanStatus = "complete";
    } else if (statusRaw === "api_error" || statusRaw === "partial_api_error") {
      cleanStatus = "partial_api_error";
    }

    const plies = Number(row.plies_survived ?? row.turns ?? 0) || 0;

    return {
      trial_id: rawId,
      short_label: runTag + " · " + shortTrial,
      game: String(row.game || "unknown").toLowerCase(),
      model: String(row.white_model || row.model || "unknown"),
      opponent_model: String(row.black_model || row.opponent_model || "unknown"),
      status: cleanStatus,
      turns: plies,
      board_print_requests: Number(row.board_print_requests || 0),
      reason: String(row.failure_reason || row.reason || "Completed"),
      exact_prompt: String(row.exact_prompt || ""),
      has_replay: Boolean(row.has_replay)
    };
  }

  function getFilteredTrials() {
    const gameVal = byId("filter-game").value;
    const modelVal = byId("filter-model").value;
    const searchVal = byId("filter-search").value.trim().toLowerCase();

    const list = [];
    for (let i = 0; i < allTrials.length; i++) {
      const t = allTrials[i];
      const matchesGame = gameVal === "ALL" || t.game === gameVal;
      const matchesModel =
        modelVal === "ALL" || t.model === modelVal || t.opponent_model === modelVal;

      let matchesSearch = true;
      if (searchVal) {
        const hay = (
          t.game + " " + t.model + " " + t.opponent_model + " " + t.short_label + " " + t.reason
        ).toLowerCase();
        matchesSearch = hay.includes(searchVal);
      }

      if (matchesGame && matchesModel && matchesSearch) {
        list.push(t);
      }
    }
    return list;
  }

  function renderSummary(visible) {
    let complete = 0;
    let invalid = 0;
    let partial = 0;

    for (let i = 0; i < visible.length; i++) {
      if (visible[i].status === "complete") complete++;
      else if (visible[i].status === "partial_api_error") partial++;
      else invalid++;
    }

    const metrics = [
      ["Total Matches", visible.length],
      ["Valid Completions", complete],
      ["Illegal Move Collapses", invalid],
      ["API Interruptions", partial]
    ];

    let html = "";
    for (let i = 0; i < metrics.length; i++) {
      html += `
        <div class="bg-cream-card border border-cream-border rounded-xl p-4">
          <div class="text-[11px] font-mono uppercase text-wood-umber">${metrics[i][0]}</div>
          <div class="font-serif text-3xl font-bold text-wood-espresso mt-1">${metrics[i][1]}</div>
        </div>
      `;
    }
    byId("trial-summary").innerHTML = html;
  }

  function buildSingleCardHtml(trial, indexOnPage) {
    let badgeClass = "bg-wood-terracotta/15 text-wood-terracotta border-wood-terracotta/30";
    let badgeText = "Illegal Move";

    if (trial.status === "complete") {
      badgeClass = "bg-wood-sage/15 text-wood-sage border-wood-sage/30";
      badgeText = "Completed";
    } else if (trial.status === "partial_api_error") {
      badgeClass = "bg-wood-amber/20 text-wood-walnut border-wood-amber/40";
      badgeText = "Ran Out of Time / API";
    }

    const shortReason =
      trial.reason.length > 110 ? trial.reason.slice(0, 110) + "…" : trial.reason;

    return `
      <article onclick="openReplayOverlay(${indexOnPage})" class="cursor-pointer group bg-cream-bg hover:bg-cream-card border border-cream-border hover:border-wood-walnut rounded-2xl p-5 flex flex-col justify-between gap-4 transition-all shadow-sm hover:shadow-md">
        <div class="space-y-3">
          <div class="flex items-center justify-between gap-2">
            <span class="font-mono text-[11px] uppercase font-bold px-2.5 py-0.5 rounded bg-wood-walnut/10 text-wood-walnut">
              ${escapeHtml(formatGameTitle(trial.game))}
            </span>
            <span class="font-mono text-[11px] font-semibold px-2.5 py-0.5 rounded-full border ${badgeClass}">
              ${badgeText}
            </span>
          </div>

          <div>
            <h4 class="font-serif text-lg font-bold text-wood-espresso group-hover:text-wood-walnut transition-colors leading-snug">
              ${escapeHtml(trial.model)} <span class="text-wood-umber font-normal text-sm">vs</span> ${escapeHtml(trial.opponent_model)}
            </h4>
            <p class="font-mono text-[11px] text-wood-umber mt-0.5">${escapeHtml(trial.short_label)}</p>
          </div>

          <div class="p-3 rounded-xl bg-cream-card border border-cream-border space-y-1">
            <div class="flex items-center justify-between text-[11px] font-mono">
              <span class="text-wood-umber uppercase">Survived</span>
              <strong class="text-wood-espresso">${trial.turns} plies / turns</strong>
            </div>
            <p class="text-xs text-wood-umber leading-relaxed pt-1 border-t border-cream-border/60">
              ${escapeHtml(shortReason)}
            </p>
          </div>
        </div>

        <div class="flex items-center justify-between text-xs font-mono font-semibold text-wood-walnut pt-1">
          <span>Tap to inspect match</span>
          <span class="group-hover:translate-x-1 transition-transform">→</span>
        </div>
      </article>
    `;
  }

  let currentPageSlice = [];

  function renderTrials() {
    const visible = getFilteredTrials();
    renderSummary(visible);

    const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
    if (currentPage >= pageCount) currentPage = pageCount - 1;
    if (currentPage < 0) currentPage = 0;

    const start = currentPage * PAGE_SIZE;
    currentPageSlice = visible.slice(start, start + PAGE_SIZE);

    byId("trial-page-label").textContent = visible.length
      ? `${start + 1}–${Math.min(start + PAGE_SIZE, visible.length)} of ${visible.length} matches`
      : "0 matches";
    if (byId("trial-page-number")) {
      byId("trial-page-number").textContent = `Page ${currentPage + 1} of ${pageCount}`;
    }

    byId("trial-page-previous").disabled = currentPage === 0;
    byId("trial-page-next").disabled = currentPage >= pageCount - 1;

    if (currentPageSlice.length === 0) {
      byId("trial-cards-grid").innerHTML =
        '<div class="col-span-full p-8 text-center text-wood-umber">No trials match your filters.</div>';
      return;
    }

    let cardsHtml = "";
    for (let i = 0; i < currentPageSlice.length; i++) {
      cardsHtml += buildSingleCardHtml(currentPageSlice[i], i);
    }
    byId("trial-cards-grid").innerHTML = cardsHtml;
  }

  const DEFAULT_PROMPTS_BY_GAME = {
    "tic-tac-toe":
      "You are playing tic-tac-toe as {mark}. The board starts empty, with squares numbered 1-9 left-to-right and top-to-bottom. Maintain the game state across this conversation: your prior move replies are your moves, and each new user message gives the opponent's latest mark and square. PRINT OUT BOARD replies only request the current board and do not advance the game. Choose an empty square, or reply exactly PRINT OUT BOARD to request the current board. For a move, reply with exactly one digit from 1 to 9 and no other text.",
    "connect-four":
      "You are playing Connect Four as {color} ({mark}). The board has 7 columns labeled A-G and 6 rows. Discs fall to the lowest empty space in the chosen column. The game may start from a partially filled board provided in your first message. Maintain the game state across this conversation: update your internal board with your own moves and each new user message giving the opponent's latest move. PRINT OUT BOARD replies only request the current board and do not advance the game. Choose a column that is not full. Reply with exactly one column letter from A to G, or reply exactly PRINT OUT BOARD to request the current board. For a move, provide no other text.",
    "uno":
      "You are playing this simplified UNO game. Maintain the game state across this conversation: your prior assistant replies are your actions, and each new user message gives the opponent's latest action and your current hand. Treat the listed hand as authoritative, including any cards drawn by the referee. Play only a card in your hand matching the active discard by color or value; if none matches, draw. Respond with exactly 'PLAY <Color> <Value>' or 'DRAW' and no other text.",
    "checkers":
      "You are playing International Draughts (10x10 checkers). The game starts from the standard initial position. Use numbered dark squares: White men (w) move toward square 1; Black men (b) move toward square 50. Captures are mandatory; choose a complete turn capturing the maximum possible number of opposing pieces. Kings (W/B) fly diagonally. Maintain the game state across this conversation. Reply with exactly one PDN move (for example 31-26 or 31x22x13), or PRINT OUT BOARD."
  };

  let activeOverlayPromptText = "";

  window.toggleOverlayPrompt = function () {
    const box = byId("overlay-prompt-box");
    const btn = byId("overlay-prompt-toggle-btn");
    if (!box || !btn) return;

    const isHidden = box.classList.contains("hidden");
    if (isHidden) {
      box.classList.remove("hidden");
      btn.textContent = "Hide Exact Prompt";
    } else {
      box.classList.add("hidden");
      btn.textContent = "View Exact Prompt";
    }
  };

  window.copyOverlayPrompt = function () {
    if (!activeOverlayPromptText) return;
    navigator.clipboard.writeText(activeOverlayPromptText).then(function () {
      const copyBtn = byId("overlay-prompt-copy-btn");
      if (copyBtn) {
        copyBtn.textContent = "Copied!";
        setTimeout(function () {
          copyBtn.textContent = "Copy Prompt";
        }, 1500);
      }
    });
  };

  window.openReplayOverlay = function (indexOnPage) {
    const trial = currentPageSlice[indexOnPage];
    if (!trial) return;

    byId("overlay-game-pill").textContent = formatGameTitle(trial.game);
    byId("overlay-title").textContent = trial.model + " vs " + trial.opponent_model;
    byId("overlay-subtitle").textContent = trial.short_label;

    let outcomeLabel = "Illegal Move Collapse";
    let outcomeColor = "text-wood-terracotta";
    let logHeaderLabel = "Referee Audit Log / Exact Model Response";

    if (trial.status === "complete") {
      outcomeLabel = "Valid Completion";
      outcomeColor = "text-wood-sage";
      logHeaderLabel = "Match Summary";
    } else if (trial.status === "partial_api_error") {
      outcomeLabel = "Ran Out of Time / API Error";
      outcomeColor = "text-wood-walnut";
      logHeaderLabel = "Truncation / Timeout Diagnostic";
    }

    activeOverlayPromptText =
      trial.exact_prompt || DEFAULT_PROMPTS_BY_GAME[trial.game] || "Prompt not recorded for this trial.";

    byId("overlay-body").innerHTML = `
      <div id="uno-overlay-stage"></div>
      <div id="checkers-overlay-stage"></div>
      <div id="chess-overlay-stage"></div>

      <div class="grid grid-cols-2 gap-3">
        <div class="p-3.5 rounded-xl bg-cream-card border border-cream-border">
          <div class="text-[10px] font-mono uppercase text-wood-umber">Outcome Status</div>
          <div class="font-serif text-lg font-bold ${outcomeColor} mt-0.5">${outcomeLabel}</div>
        </div>
        <div class="p-3.5 rounded-xl bg-cream-card border border-cream-border">
          <div class="text-[10px] font-mono uppercase text-wood-umber">Survival Depth</div>
          <div class="font-serif text-lg font-bold text-wood-espresso mt-0.5">${trial.turns} Plies / Turns</div>
        </div>
      </div>

      <div class="p-4 rounded-xl bg-cream-card border border-cream-border space-y-1.5">
        <div class="text-[11px] font-mono uppercase ${outcomeColor} font-semibold">${logHeaderLabel}</div>
        <p class="text-xs font-mono text-wood-espresso whitespace-pre-wrap leading-relaxed">${escapeHtml(trial.reason)}</p>
      </div>

      <div class="pt-1">
        <div class="flex items-center justify-between gap-2">
          <button id="overlay-prompt-toggle-btn" type="button" onclick="toggleOverlayPrompt()" class="px-3 py-1.5 rounded-lg bg-cream-card hover:bg-cream-hover border border-cream-border text-xs font-mono font-semibold text-wood-walnut transition-colors">
            View Exact Prompt
          </button>
          <button id="overlay-prompt-copy-btn" type="button" onclick="copyOverlayPrompt()" class="px-3 py-1.5 rounded-lg bg-cream-card hover:bg-cream-hover border border-cream-border text-xs font-mono text-wood-umber hover:text-wood-espresso transition-colors">
            Copy Prompt
          </button>
        </div>
        <div id="overlay-prompt-box" class="hidden mt-2.5 p-3.5 rounded-xl bg-wood-espresso text-cream-bg border border-wood-walnut text-xs font-mono whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto">${escapeHtml(activeOverlayPromptText)}</div>
      </div>
    `;

    const dedicatedUrl = REPLAY_URLS[trial.game]
      ? REPLAY_URLS[trial.game] + "?trial_id=" + encodeURIComponent(trial.trial_id)
      : null;

    byId("overlay-footer").innerHTML = dedicatedUrl
      ? `
        <button type="button" onclick="closeReplayOverlay()" class="px-4 py-2.5 rounded-xl bg-cream-bg hover:bg-cream-hover border border-cream-border text-xs font-mono font-semibold text-wood-espresso">
          ✕ Close
        </button>
        <a href="${dedicatedUrl}" class="flex-1 py-2.5 px-4 rounded-xl bg-wood-walnut hover:bg-wood-walnutHover text-cream-bg text-xs font-mono font-semibold text-center transition-colors">
          Explore full ${escapeHtml(formatGameTitle(trial.game))} replay viewer →
        </a>
      `
      : `
        <button type="button" onclick="closeReplayOverlay()" class="w-full py-2.5 px-4 rounded-xl bg-cream-bg hover:bg-cream-hover border border-cream-border text-xs font-mono font-semibold text-wood-espresso">
          ✕ Close Match Record
        </button>
      `;

    byId("replay-overlay").classList.remove("hidden");
    document.body.style.overflow = "hidden";
    byId("overlay-body").scrollTop = 0;
    history.pushState({ overlayOpen: true }, "", "#match");

    if (trial.game === "uno" && typeof loadUnoReplayIntoOverlay === "function") {
      loadUnoReplayIntoOverlay(trial.trial_id);
    } else if (trial.game === "checkers" && typeof loadCheckersReplayIntoOverlay === "function") {
      loadCheckersReplayIntoOverlay(trial.trial_id);
    } else if (trial.game === "chess" && typeof loadChessReplayIntoOverlay === "function") {
      loadChessReplayIntoOverlay(trial.trial_id);
    }
  };

  window.closeReplayOverlay = function () {
    byId("replay-overlay").classList.add("hidden");
    document.body.style.overflow = "";
  };

  window.addEventListener("popstate", function () {
    window.closeReplayOverlay();
  });

  window.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      window.closeReplayOverlay();
    }
  });

  function populateDropdownFilters() {
    const gamesSet = {};
    const modelsSet = {};
    for (let i = 0; i < allTrials.length; i++) {
      gamesSet[allTrials[i].game] = true;
      if (allTrials[i].model) modelsSet[allTrials[i].model] = true;
      if (allTrials[i].opponent_model) modelsSet[allTrials[i].opponent_model] = true;
    }

    const games = Object.keys(gamesSet).sort();
    const models = Object.keys(modelsSet).sort();

    let gameOpts = '<option value="ALL">All Games</option>';
    for (let i = 0; i < games.length; i++) {
      gameOpts += `<option value="${escapeHtml(games[i])}">${escapeHtml(formatGameTitle(games[i]))}</option>`;
    }
    byId("filter-game").innerHTML = gameOpts;

    let modelOpts = '<option value="ALL">All Models</option>';
    for (let i = 0; i < models.length; i++) {
      modelOpts += `<option value="${escapeHtml(models[i])}">${escapeHtml(models[i])}</option>`;
    }
    byId("filter-model").innerHTML = modelOpts;
  }
  function renderHomeTopMetrics(trials) {
    const grid = byId("home-metrics-grid");
    if (!grid || !Array.isArray(trials)) return;

    let illegalMoves = 0;
    let illegalPliesSum = 0;
    let boardHelpRequests = 0;

    for (let i = 0; i < trials.length; i++) {
      const t = trials[i];
      boardHelpRequests += Number(t.board_print_requests || 0);
      if (t.status === "invalid_or_illegal") {
        illegalMoves += 1;
        illegalPliesSum += Number(t.turns || 0);
      }
    }

    const meanCollapse = illegalMoves > 0
      ? "Turn " + (illegalPliesSum / illegalMoves).toFixed(1)
      : "Turn 0.0";

    grid.innerHTML = `
      <div class="bg-cream-card border border-cream-border rounded-2xl p-5 flex items-start justify-between">
        <div>
          <div class="text-[11px] font-mono uppercase tracking-wider text-wood-umber">TOTAL TRIALS LOGGED</div>
          <div class="font-serif text-3xl font-bold text-wood-walnut mt-1">${trials.length}</div>
          <div class="text-xs text-wood-umber mt-1">Across 5 deterministic games</div>
        </div>
        <div class="p-2.5 rounded-xl bg-cream-bg border border-cream-border text-wood-walnut">
          <i data-lucide="swords" class="w-4 h-4"></i>
        </div>
      </div>

      <div class="bg-cream-card border border-cream-border rounded-2xl p-5 flex items-start justify-between">
        <div>
          <div class="text-[11px] font-mono uppercase tracking-wider text-wood-umber">MEAN COLLAPSE HORIZON</div>
          <div class="font-serif text-3xl font-bold text-wood-terracotta mt-1">${meanCollapse}</div>
          <div class="text-xs text-wood-umber mt-1">Onset of coordinate drift</div>
        </div>
        <div class="p-2.5 rounded-xl bg-cream-bg border border-cream-border text-wood-terracotta">
          <i data-lucide="flame" class="w-4 h-4"></i>
        </div>
      </div>

      <div class="bg-cream-card border border-cream-border rounded-2xl p-5 flex items-start justify-between">
        <div>
          <div class="text-[11px] font-mono uppercase tracking-wider text-wood-umber">ILLEGAL MOVES RECORDED</div>
          <div class="font-serif text-3xl font-bold text-wood-walnut mt-1">${illegalMoves}</div>
          <div class="text-xs text-wood-umber mt-1">Phantom spawns &amp; rule breaks</div>
        </div>
        <div class="p-2.5 rounded-xl bg-cream-bg border border-cream-border text-wood-walnut">
          <i data-lucide="alert-triangle" class="w-4 h-4"></i>
        </div>
      </div>

      <div class="bg-cream-card border border-cream-border rounded-2xl p-5 flex items-start justify-between">
        <div>
          <div class="text-[11px] font-mono uppercase tracking-wider text-wood-umber">HOW MANY TIMES AI ASKED FOR HELP</div>
          <div class="font-serif text-3xl font-bold text-wood-walnut mt-1">${boardHelpRequests}</div>
          <div class="text-xs text-wood-umber mt-1">Mid-game board printouts requested</div>
        </div>
        <div class="p-2.5 rounded-xl bg-cream-bg border border-cream-border text-wood-walnut">
          <i data-lucide="help-circle" class="w-4 h-4"></i>
        </div>
      </div>
    `;

    if (window.lucide && typeof window.lucide.createIcons === "function") {
      window.lucide.createIcons();
    }
  }

  async function initCloudTrials() {
    try {
      const cloudRows = await fetchAllCatalogTrials();
      allTrials = [];
      for (let i = 0; i < cloudRows.length; i++) {
        allTrials.push(formatCatalogRow(cloudRows[i]));
      }

      window.liveTrials = allTrials;
      if (typeof window.onLiveTrialsUpdated === "function") {
        renderHomeTopMetrics(allTrials);
        window.onLiveTrialsUpdated(cloudRows);
      }

      byId("nav-trial-count").textContent = String(allTrials.length);
      if (byId("db-status-indicator")) {
        byId("db-status-indicator").innerHTML = `<i data-lucide="cloud" class="w-3 h-3"></i> Research Data: Supabase Cloud (${allTrials.length} trials)`;
      }
      byId("trial-dashboard-status").textContent =
        `Synchronized with Supabase Cloud · ${allTrials.length} verified trials across 5 games.`;

      populateDropdownFilters();
      renderTrials();
    } catch (err) {
      byId("trial-dashboard-status").textContent = "Cloud data error: " + err.message;
    }
  }

  byId("filter-game").addEventListener("change", function () { currentPage = 0; renderTrials(); });
  byId("filter-model").addEventListener("change", function () { currentPage = 0; renderTrials(); });
  byId("filter-search").addEventListener("input", function () { currentPage = 0; renderTrials(); });
  byId("trial-page-previous").addEventListener("click", function () { currentPage -= 1; renderTrials(); });
  byId("trial-page-next").addEventListener("click", function () { currentPage += 1; renderTrials(); });

  initCloudTrials();
})();
