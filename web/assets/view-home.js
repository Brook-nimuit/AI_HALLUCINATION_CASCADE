function renderHomeMetrics() {
  const totalTrials = appData.trials.length;
  const avgCollapse = (appData.trials.reduce((acc, t) => acc + Number(t.collapseTurn || 0), 0) / (totalTrials || 1)).toFixed(1);
  const totalIllegal = appData.trials.reduce((acc, t) => acc + Number(t.illegalMovesCount || 0), 0);
  const boardHelpRequests = appData.trials.reduce(
    (acc, t) => acc + Number(t.board_print_requests || 0),
    0
  );

  const metrics = [
    { label: "Total Trials Logged", value: totalTrials, sub: "Across 4 games", icon: "swords", accent: "text-wood-walnut" },
    { label: "WI", value: `Turn ${avgCollapse}`, sub: "wierd idx", icon: "flame", accent: "text-wood-terracotta" },
    { label: "Illegal Moves Recorded", value: totalIllegal, sub: "Phantom spawns & teleports", icon: "alert-triangle", accent: "text-wood-amber" },
    { label: "How Many Times AI Asked for Help", value: boardHelpRequests, sub: "Mid-game board printouts requested", icon: "help-circle", accent: "text-wood-walnut" }
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

const TICKER_INTERVAL_MS = 7000;
let tickerSlideIndex = 0;
let tickerTimer = null;
let featuredTickerSignature = null;
let featuredGamesRequestKey = null;
let featuredGameSlideCache = [];
let featuredVideoSlideContent = "";

function getModelBrand(modelName) {
  const lower = String(modelName || "").toLowerCase();
  if (/claude|anthropic/.test(lower)) return { label: "Anthropic", logoUrl: "https://claude.com/favicon.svg" };
  if (/gpt|openai/.test(lower)) return { label: "OpenAI", logoUrl: "https://openai.com/favicon.ico" };
  if (/random/.test(lower)) return { label: "Random legal bot", logoUrl: "" };
  return { label: "AI model", logoUrl: "" };
}

function renderModelLogo(modelName, className) {
  const brand = getModelBrand(modelName);
  const logo = brand.logoUrl
    ? `<img src="${brand.logoUrl}" alt="${brand.label} official logo" decoding="async" onerror="this.parentElement.remove()">`
    : "";
  return logo ? `<span class="${className}">${logo}</span>` : "";
}

function getFeaturedPlayerStats(rows) {
  const counts = new Map();
  for (const row of rows) {
    const participants = new Set([
      row.white_model || row.model,
      row.black_model || row.opponent_model
    ].map(name => String(name || "").trim()).filter(name => name && !/random|baseline/i.test(name)));
    for (const modelName of participants) {
      counts.set(modelName, (counts.get(modelName) || 0) + 1);
    }
  }
  return [...counts.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([name, trials]) => ({ name: name, trials: trials }));
}

function buildFeaturedPlayerSlide(players) {
  const cards = players.map(player => {
    const brand = getModelBrand(player.name);
    return `
      <article class="bg-cream-card border border-cream-border rounded-2xl p-5 sm:p-7 flex flex-col sm:flex-row items-center gap-5 shadow-lg">
        ${renderModelLogo(player.name, "featured-player-logo-large")}
        <div class="min-w-0 text-center sm:text-left space-y-2">
          <div class="font-mono text-[11px] uppercase tracking-widest text-wood-umber">${brand.label}</div>
          <h3 class="font-serif text-xl sm:text-2xl font-bold text-wood-espresso break-all">${escapeHTML(player.name)}</h3>
          <p class="text-sm text-wood-umber">${player.trials} archived ${player.trials === 1 ? "trial" : "trials"}</p>
        </div>
      </article>
    `;
  }).join("");
  return `
    <div class="w-full max-w-4xl mx-auto space-y-6">
      <div>
        <span class="inline-flex items-center px-3 py-1 rounded-full bg-wood-walnut/10 border border-cream-border text-wood-walnut text-xs font-mono font-semibold">MODELS IN THE STUDY</span>
        <h2 class="font-serif text-2xl sm:text-3xl font-bold text-wood-espresso mt-3">Evaluated models</h2>
        <p class="text-sm text-wood-umber mt-1">Two models per slide, with an official provider logo beside each exact model name.</p>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">${cards}</div>
    </div>
  `;
}

function isFeaturedMatch(row) {
  const game = String(row.game || "").toLowerCase();
  const status = String(row.status || "").toLowerCase();
  const white = String(row.white_model || row.model || "");
  const black = String(row.black_model || row.opponent_model || "");
  const isGpt = model => /gpt|openai/i.test(model);
  const isClaude = model => /claude|anthropic/i.test(model);
  const eligiblePair =
    (isGpt(white) && isClaude(black)) ||
    (isClaude(white) && isGpt(black)) ||
    (isClaude(white) && isClaude(black));

  const usable = status !== "api_error" && status !== "partial_api_error";
  if (game === "checkers") {
    return usable && Number(row.plies_survived ?? row.turns ?? 0) >= 50;
  }
  return game === "chess" && eligiblePair && usable;
}

function chooseFeaturedMatches(rows) {
  const bestByGame = {};
  for (const row of rows) {
    if (!isFeaturedMatch(row)) continue;
    const game = String(row.game).toLowerCase();
    const plies = Number(row.plies_survived ?? row.turns ?? 0) || 0;
    const currentPlies = bestByGame[game]
      ? Number(bestByGame[game].plies_survived ?? bestByGame[game].turns ?? 0) || 0
      : -1;
    if (plies > currentPlies) bestByGame[game] = row;
  }
  return [bestByGame.chess, bestByGame.checkers].filter(Boolean);
}

function inferLastMoveIsIllegal(row, lastMove, game) {
  const trialStatus = String(row.status || "").toLowerCase();
  const moveStatus = String(lastMove && lastMove.status || "").toUpperCase();
  if (trialStatus === "illegal_move" || trialStatus === "invalid_or_illegal") return true;
  if (moveStatus === "ILLEGAL" || moveStatus === "INVALID") return true;
  return game === "checkers" && Boolean(lastMove && lastMove.valid === false);
}

async function buildFeaturedGameCard(row) {
  const replayRow = await fetchSingleReplay(row.trial_id);
  const replay = replayRow && replayRow.replay_data;
  const game = String(row.game).toLowerCase();
  const plies = Number(row.plies_survived ?? row.turns ?? 0) || 0;
  const isComplete = ["complete", "completed"].includes(String(row.status || "").toLowerCase());
  const moves = replay && (Array.isArray(replay.moves) ? replay.moves : replay.turns) || [];
  const lastMove = moves.length ? moves[moves.length - 1] : null;
  const isIllegal = inferLastMoveIsIllegal(row, lastMove, game);
  const moveText = game === "chess"
    ? (lastMove && (lastMove.san || lastMove.raw_response))
    : (lastMove && (lastMove.move || lastMove.raw_response));
  const actor = game === "chess"
    ? (lastMove && (lastMove.actor || lastMove.bot))
    : (lastMove && (lastMove.player || lastMove.model));
  let boardHtml = "";

  if (lastMove && game === "chess" && typeof buildChessOverlayBoardHtml === "function") {
    const fen = lastMove.status === "LEGAL"
      ? (lastMove.post_fen || lastMove.pre_fen)
      : (lastMove.pre_fen || lastMove.post_fen);
    boardHtml = buildChessOverlayBoardHtml(fen, lastMove, true);
  } else if (game === "checkers" && typeof buildCheckersGridHtml === "function") {
    const board = lastMove && lastMove.post_board
      ? lastMove.post_board
      : (replay && (replay.initial_board || (replay.initial_state && replay.initial_state.board))) || {};
    boardHtml = buildCheckersGridHtml(board, lastMove);
  }

  const gameLabel = game === "chess" ? "Chess" : "Checkers";
  const replayUrl = `/${game}-replay/?trial_id=${encodeURIComponent(row.trial_id)}`;
  const statusLabel = isComplete ? "Completed" : "Failed / illegal move";

  return `
    <article class="bg-cream-card border border-cream-border rounded-2xl p-4 sm:p-6 space-y-4 shadow-lg">
      <div class="flex items-center justify-between gap-2">
        <span class="font-mono text-[10px] uppercase tracking-wider text-wood-walnut">${gameLabel}</span>
        <span class="font-mono text-[10px] ${isComplete ? "text-wood-sage" : "text-wood-terracotta"}">${statusLabel} · ${plies} plies (${plies} moves)</span>
      </div>
      <div class="grid grid-cols-2 gap-2">
        <div class="flex items-center gap-2 min-w-0 p-2 rounded-lg bg-cream-bg border border-cream-border">
          ${renderModelLogo(row.white_model || row.model || "Unknown", "featured-model-logo")}
          <div class="min-w-0"><div class="font-mono text-[9px] uppercase text-wood-umber">White bot</div><div class="text-[11px] font-semibold text-wood-espresso break-all">${escapeHTML(row.white_model || row.model || "Unknown")}</div></div>
        </div>
        <div class="flex items-center gap-2 min-w-0 p-2 rounded-lg bg-cream-bg border border-cream-border">
          ${renderModelLogo(row.black_model || row.opponent_model || "Unknown", "featured-model-logo")}
          <div class="min-w-0"><div class="font-mono text-[9px] uppercase text-wood-umber">Black bot</div><div class="text-[11px] font-semibold text-wood-espresso break-all">${escapeHTML(row.black_model || row.opponent_model || "Unknown")}</div></div>
        </div>
      </div>
      ${boardHtml ? `<div class="featured-game-board">${boardHtml}${isIllegal ? '<span class="featured-blunder-badge" aria-label="Illegal move: question mark exclamation mark">?!</span>' : ""}</div>` : ""}
      <div class="p-3 rounded-xl bg-cream-bg border border-cream-border">
        <div class="font-mono text-[10px] uppercase text-wood-umber">Last move${isIllegal ? " · HALLUCINATION" : ""}</div>
        <div class="text-sm font-bold text-wood-espresso mt-1">${escapeHTML(actor || "Unknown bot")} · ${escapeHTML(moveText || "Move unavailable")}</div>
      </div>
      <a href="${replayUrl}" class="inline-flex text-xs font-mono font-semibold text-wood-walnut hover:underline">Open full ${gameLabel} replay →</a>
    </article>
  `;
}

function buildFeaturedGameSlide(game, cardHtml) {
  const gameLabel = game === "chess" ? "Chess" : "Checkers";
  const description = game === "checkers"
    ? "A Checkers replay with at least 50 moves."
    : "The longest eligible GPT–Claude or Claude–Claude Chess match.";
  return `
    <div class="w-full max-w-4xl mx-auto space-y-5">
      <div>
        <span class="inline-flex items-center px-3 py-1 rounded-full bg-wood-walnut/10 border border-cream-border text-wood-walnut text-xs font-mono font-semibold">SELECTED MATCH</span>
        <h2 class="font-serif text-2xl sm:text-3xl font-bold text-wood-espresso mt-3">${gameLabel} · longest eligible matchup</h2>
        <p class="text-sm text-wood-umber mt-1">${description}</p>
      </div>
      ${cardHtml}
    </div>
  `;
}

async function getFeaturedGameSlides(rows) {
  const selected = chooseFeaturedMatches(rows);
  const requestKey = selected.map(row => row.trial_id).join("|");
  if (requestKey === featuredGamesRequestKey) return featuredGameSlideCache;
  featuredGamesRequestKey = requestKey;

  if (selected.length === 0) {
    featuredGameSlideCache = [
      '<div class="w-full flex items-center justify-center text-sm text-wood-umber">No eligible Chess or Checkers matches are available yet.</div>'
    ];
    return featuredGameSlideCache;
  }

  const cards = await Promise.all(selected.map(buildFeaturedGameCard));
  if (featuredGamesRequestKey !== requestKey) return [];
  featuredGameSlideCache = selected.map((row, index) =>
    buildFeaturedGameSlide(String(row.game).toLowerCase(), cards[index])
  );
  return featuredGameSlideCache;
}

function getFeaturedVideoSlideContent() {
  if (!featuredVideoSlideContent) {
    const videoSlide = document.querySelector("#ticker-slides .trending-slide[data-slide='2']");
    if (videoSlide) featuredVideoSlideContent = videoSlide.innerHTML;
  }
  return featuredVideoSlideContent || '<div class="w-full text-center text-sm text-wood-umber">Featured videos are unavailable.</div>';
}

function renderTickerSlides(slideContents) {
  const container = document.getElementById("ticker-slides");
  const dots = document.getElementById("ticker-dots");
  if (!container || !dots || slideContents.length === 0) return;

  container.innerHTML = slideContents.map((content, index) =>
    `<div class="trending-slide${index === 0 ? " active-slide" : ""}" data-slide="${index}">${content}</div>`
  ).join("");
  dots.innerHTML = slideContents.map((_, index) =>
    `<button type="button" onclick="goToTickerSlide(${index})" class="ticker-dot${index === 0 ? " active-dot" : ""}" aria-label="Show featured slide ${index + 1}" title="Featured slide ${index + 1}"></button>`
  ).join("");
  tickerSlideIndex = 0;
  window.goToTickerSlide(0);
  if (window.lucide && typeof window.lucide.createIcons === "function") window.lucide.createIcons();
}

window.renderFeaturedHighlights = async function (rows) {
  if (!Array.isArray(rows)) return;
  const firstId = rows.length ? String(rows[0].trial_id || "") : "";
  const lastId = rows.length ? String(rows[rows.length - 1].trial_id || "") : "";
  const signature = `${rows.length}:${firstId}:${lastId}`;
  if (signature === featuredTickerSignature) return;
  featuredTickerSignature = signature;

  const players = getFeaturedPlayerStats(rows);
  const playerPages = [];
  for (let index = 0; index < players.length; index += 2) {
    playerPages.push(players.slice(index, index + 2));
  }
  const playerSlides = playerPages.map(page => buildFeaturedPlayerSlide(page));
  if (playerSlides.length === 0) playerSlides.push('<div class="w-full text-center text-sm text-wood-umber">No model records are available.</div>');

  try {
    const gameSlides = await getFeaturedGameSlides(rows);
    renderTickerSlides([...playerSlides, ...gameSlides, getFeaturedVideoSlideContent()]);
  } catch (error) {
    const errorSlide = `<div class="w-full text-center text-sm text-wood-terracotta">Could not load featured games: ${escapeHTML(error.message)}</div>`;
    renderTickerSlides([...playerSlides, errorSlide, getFeaturedVideoSlideContent()]);
  }
};

window.goToTickerSlide = function (slideIndex) {
  const slides = Array.from(document.querySelectorAll("#ticker-slides .trending-slide"));
  const dots = Array.from(document.querySelectorAll("#ticker-dots .ticker-dot"));
  if (slides.length === 0) return;

  tickerSlideIndex = (Number(slideIndex) + slides.length) % slides.length;
  slides.forEach((slide, index) => slide.classList.toggle("active-slide", index === tickerSlideIndex));
  dots.forEach((dot, index) => dot.classList.toggle("active-dot", index === tickerSlideIndex));
  const label = document.getElementById("ticker-step-label");
  if (label) label.textContent = `// ${String(tickerSlideIndex + 1).padStart(2, "0")} OF ${String(slides.length).padStart(2, "0")}`;
};

window.stepTicker = function (delta) {
  window.goToTickerSlide(tickerSlideIndex + Number(delta || 0));
};

document.addEventListener("DOMContentLoaded", function () {
  window.goToTickerSlide(0);
  tickerTimer = window.setInterval(function () {
    window.stepTicker(1);
  }, TICKER_INTERVAL_MS);

  const carousel = document.querySelector(".trending-shell");
  if (!carousel) return;

  let touchStartX = null;
  let touchStartY = null;
  let suppressClickUntil = 0;

  carousel.addEventListener("touchstart", function (event) {
    const touch = event.changedTouches[0];
    if (!touch) return;
    touchStartX = touch.clientX;
    touchStartY = touch.clientY;
  }, { passive: true });

  carousel.addEventListener("touchend", function (event) {
    const touch = event.changedTouches[0];
    if (!touch || touchStartX === null || touchStartY === null) return;

    const deltaX = touch.clientX - touchStartX;
    const deltaY = touch.clientY - touchStartY;
    touchStartX = null;
    touchStartY = null;

    if (Math.abs(deltaX) < 48 || Math.abs(deltaX) < Math.abs(deltaY) * 1.2) return;
    if (event.cancelable) event.preventDefault();
    suppressClickUntil = Date.now() + 500;
    window.stepTicker(deltaX < 0 ? 1 : -1);
  }, { passive: false });

  carousel.addEventListener("touchcancel", function () {
    touchStartX = null;
    touchStartY = null;
  }, { passive: true });

  carousel.addEventListener("click", function (event) {
    if (Date.now() < suppressClickUntil) {
      event.preventDefault();
      event.stopPropagation();
    }
  }, true);
});
