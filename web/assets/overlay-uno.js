// web/assets/overlay-uno.js
// Renders an interactive turn-by-turn UNO card scrubber inside the slide-up overlay.

let activeUnoReplay = null;
let activeUnoTurnIndex = 0;

function getUnoCardStyle(cardText) {
  const lower = String(cardText || "").toLowerCase();
  if (lower.startsWith("red")) {
    return "background-color: #c93b2b; color: #ffffff; border: 2px solid #8f2419;";
  }
  if (lower.startsWith("yellow")) {
    return "background-color: #eab308; color: #2b1d0e; border: 2px solid #a16207;";
  }
  if (lower.startsWith("green")) {
    return "background-color: #2b8a3e; color: #ffffff; border: 2px solid #1b5e20;";
  }
  if (lower.startsWith("blue")) {
    return "background-color: #1d4ed8; color: #ffffff; border: 2px solid #1e3a8a;";
  }
  return "background-color: #3b2a1e; color: #f7f3eb; border: 2px solid #6b4c35;";
}

function renderMiniUnoCard(cardText, isHighlighted) {
  const clean = String(cardText || "—").trim();
  const spaceIdx = clean.indexOf(" ");
  const color = spaceIdx !== -1 ? clean.slice(0, spaceIdx) : "";
  const val = spaceIdx !== -1 ? clean.slice(spaceIdx + 1) : clean;
  const colorStyle = getUnoCardStyle(clean);
  const ringStyle = isHighlighted
    ? "transform: translateY(-3px); box-shadow: 0 6px 12px rgba(0,0,0,0.22);"
    : "box-shadow: 0 2px 4px rgba(0,0,0,0.12);";

  return `
    <div style="${colorStyle} ${ringStyle} width: 64px; height: 88px; border-radius: 10px; padding: 6px; display: inline-flex; flex-direction: column; align-items: center; justify-content: space-between; text-align: center; user-select: none;">
      <span style="font-size: 9px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; opacity: 0.9;">${escapeHTML(color)}</span>
      <span style="font-family: 'Fraunces', serif; font-weight: 700; font-size: 13px; line-height: 1.15;">${escapeHTML(val)}</span>
      <span style="width: 16px; height: 2px; border-radius: 2px; background: currentColor; opacity: 0.4;"></span>
    </div>
  `;
}
function renderUnoHandRow(cardsList) {
  if (!Array.isArray(cardsList) || cardsList.length === 0) {
    return '<span class="text-xs font-mono text-wood-sage font-semibold">0 cards (Empty Hand!)</span>';
  }
  let html = "";
  for (let i = 0; i < cardsList.length; i++) {
    html += renderMiniUnoCard(cardsList[i], "");
  }
  return html;
}

window.stepUnoOverlayTurn = function (delta) {
  if (!activeUnoReplay || !activeUnoReplay.turns) return;
  const nextIdx = activeUnoTurnIndex + delta;
  if (nextIdx < 0 || nextIdx >= activeUnoReplay.turns.length) return;
  activeUnoTurnIndex = nextIdx;
  updateUnoScrubberDom();
};

window.jumpUnoOverlayTurn = function (idxValue) {
  if (!activeUnoReplay || !activeUnoReplay.turns) return;
  activeUnoTurnIndex = Number(idxValue) || 0;
  updateUnoScrubberDom();
};

function updateUnoScrubberDom() {
  const container = document.getElementById("uno-overlay-stage");
  if (!container || !activeUnoReplay) return;

  const turns = activeUnoReplay.turns || [];
  if (turns.length === 0) {
    container.innerHTML = '<p class="text-xs text-wood-umber">No turn records available.</p>';
    return;
  }

  const t = turns[activeUnoTurnIndex];
  const hands = t.hands_before || {};
  const handA = hands.Agent_A || [];
  const handB = hands.Agent_B || [];
  const isInvalid = !t.valid;

  const statusBadge = isInvalid
    ? `<span class="px-2 py-0.5 rounded bg-wood-terracotta text-cream-bg font-mono text-[10px] font-bold">HALLUCINATED / ILLEGAL</span>`
    : `<span class="px-2 py-0.5 rounded bg-wood-sage/20 text-wood-sage font-mono text-[10px] font-bold">LEGAL ACTION</span>`;

  container.innerHTML = `
    <div class="p-4 rounded-2xl bg-cream-card border border-cream-border space-y-4">
      <!-- Scrubber Controls -->
      <div class="flex items-center justify-between gap-2 pb-3 border-b border-cream-border">
        <div class="flex items-center gap-1.5">
          <button type="button" onclick="jumpUnoOverlayTurn(0)" ${activeUnoTurnIndex === 0 ? "disabled" : ""} class="px-2 py-1 rounded border border-cream-border bg-cream-bg text-xs font-mono disabled:opacity-40">|&lt;</button>
          <button type="button" onclick="stepUnoOverlayTurn(-1)" ${activeUnoTurnIndex === 0 ? "disabled" : ""} class="px-2.5 py-1 rounded border border-cream-border bg-cream-bg text-xs font-mono font-bold disabled:opacity-40">← Prev</button>
          <button type="button" onclick="stepUnoOverlayTurn(1)" ${activeUnoTurnIndex >= turns.length - 1 ? "disabled" : ""} class="px-2.5 py-1 rounded border border-cream-border bg-cream-bg text-xs font-mono font-bold disabled:opacity-40">Next →</button>
          <button type="button" onclick="jumpUnoOverlayTurn(${turns.length - 1})" ${activeUnoTurnIndex >= turns.length - 1 ? "disabled" : ""} class="px-2 py-1 rounded border border-cream-border bg-cream-bg text-xs font-mono disabled:opacity-40">&gt;|</button>
        </div>
        <span class="font-mono text-xs font-semibold text-wood-espresso">
          Turn ${t.turn} (${activeUnoTurnIndex + 1} / ${turns.length})
        </span>
      </div>

      <input type="range" min="0" max="${turns.length - 1}" value="${activeUnoTurnIndex}" oninput="jumpUnoOverlayTurn(this.value)" style="accent-color: #6b4c35;" class="w-full cursor-pointer" />

      <!-- Discard + Active Action Row -->
      <div class="grid grid-cols-2 gap-3 p-3 rounded-xl bg-cream-bg border border-cream-border items-center">
        <div class="flex flex-col items-center gap-1">
          <span class="text-[10px] font-mono uppercase text-wood-umber">Top Discard</span>
          ${renderMiniUnoCard(t.top_card_before, "")}
        </div>
        <div class="space-y-1.5">
          <div class="flex items-center justify-between gap-1">
            <span class="text-[10px] font-mono uppercase text-wood-umber">${escapeHTML(t.player)} Move</span>
            ${statusBadge}
          </div>
          <div class="font-mono text-xs font-bold text-wood-espresso p-2 rounded bg-cream-card border border-cream-border">
            ${escapeHTML(t.raw_response || t.action)}
          </div>
          <p class="text-[11px] text-wood-umber leading-snug">${escapeHTML(t.reason)}</p>
        </div>
      </div>

      <!-- Both Agent Hands -->
      <div class="space-y-3">
        <div>
          <div class="text-[10px] font-mono uppercase text-wood-umber mb-1.5">
            Agent_A Hand (${handA.length}) ${t.player === "Agent_A" ? "· ACTIVE TURN" : ""}
          </div>
          <div class="flex flex-wrap gap-1.5">${renderUnoHandRow(handA)}</div>
        </div>
        <div class="pt-2 border-t border-cream-border/60">
          <div class="text-[10px] font-mono uppercase text-wood-umber mb-1.5">
            Agent_B Hand (${handB.length}) ${t.player === "Agent_B" ? "· ACTIVE TURN" : ""}
          </div>
          <div class="flex flex-wrap gap-1.5">${renderUnoHandRow(handB)}</div>
        </div>
      </div>
    </div>
  `;
}

async function loadUnoReplayIntoOverlay(trialId) {
  const stage = document.getElementById("uno-overlay-stage");
  if (!stage) return;
  stage.innerHTML = '<div class="p-4 text-center font-mono text-xs text-wood-umber">Loading turn-by-turn UNO cards from Supabase…</div>';

  try {
    const row = await fetchSingleReplay(trialId);
    if (!row || !row.replay_data || !Array.isArray(row.replay_data.turns)) {
      stage.innerHTML = '<div class="p-3 text-xs text-wood-umber">No turn-by-turn card log stored for this trial.</div>';
      return;
    }
    activeUnoReplay = row.replay_data;
    // Open directly on the final turn (the crash / winning move)
    activeUnoTurnIndex = Math.max(0, activeUnoReplay.turns.length - 1);
    updateUnoScrubberDom();
  } catch (err) {
    stage.innerHTML = `<div class="p-3 text-xs text-wood-terracotta">Could not load replay: ${escapeHTML(err.message)}</div>`;
  }
}