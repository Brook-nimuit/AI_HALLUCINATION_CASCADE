// web/assets/overlay-checkers.js
// Renders a crisp, fixed-aspect 10x10 International Draughts replay scrubber.

let activeCheckersReplay = null;
let activeCheckersPly = 0;

function checkersCoordToSquare(row, col) {
  if (row < 0 || row > 9 || col < 0 || col > 9 || (row + col) % 2 !== 1) {
    return null;
  }
  return row * 5 + Math.floor(col / 2) + 1;
}

function checkersSquareToCoord(sq) {
  const idx = Number(sq) - 1;
  const row = Math.floor(idx / 5);
  const offset = idx % 5;
  return { row: row, col: 2 * offset + (row % 2 === 0 ? 1 : 0) };
}

function getCheckersBoardAtPly(replay, ply) {
  if (ply <= 0) {
    return replay.initial_board || (replay.initial_state && replay.initial_state.board) || {};
  }
  const turnObj = replay.turns[ply - 1];
  return (turnObj && turnObj.post_board) || {};
}

function buildCheckersArrowSvg(path, isIllegal) {
  if (!Array.isArray(path) || path.length < 2) return "";
  const pts = [];
  for (let i = 0; i < path.length; i++) {
    const num = Number(path[i]);
    if (num >= 1 && num <= 50) {
      const c = checkersSquareToCoord(num);
      pts.push((c.col + 0.5) * 10 + "," + (c.row + 0.5) * 10);
    }
  }
  if (pts.length < 2) return "";

  const strokeColor = isIllegal ? "#dc2626" : "#facc15";
  const dashAttr = isIllegal ? 'stroke-dasharray="2.2 1.4"' : "";

  return `
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" style="position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; z-index: 5;">
      <defs>
        <marker id="chkArrow" markerWidth="4.5" markerHeight="4.5" refX="3.5" refY="2.25" orient="auto">
          <path d="M0,0 L4.5,2.25 L0,4.5 z" fill="${strokeColor}"></path>
        </marker>
      </defs>
      <polyline points="${pts.join(" ")}" fill="none" stroke="${strokeColor}" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" ${dashAttr} marker-end="url(#chkArrow)"></polyline>
    </svg>
  `;
}

function buildCheckersGridHtml(board, moveObj) {
  const path = (moveObj && Array.isArray(moveObj.parsed_path)) ? moveObj.parsed_path : [];
  const isIllegal = moveObj && moveObj.valid === false;
  const pathSet = {};
  for (let i = 0; i < path.length; i++) {
    pathSet[path[i]] = true;
  }

  let cellsHtml = "";
  for (let r = 0; r < 10; r++) {
    for (let c = 0; c < 10; c++) {
      const sq = checkersCoordToSquare(r, c);
      const isPlayable = sq !== null;
      const inPath = isPlayable && pathSet[sq];

      let bg = "#ebe3d5"; // light square
      if (isPlayable) {
        bg = "#6e8555"; // classic draughts green
        if (inPath) {
          bg = isIllegal ? "#c25246" : "#b8a65c";
        }
      }

      const piece = isPlayable ? board[String(sq)] : null;
      let pieceHtml = "";
      if (piece) {
        const isWhite = piece.toLowerCase() === "w";
        const isKing = piece === "W" || piece === "B";
        const pBg = isWhite
          ? "radial-gradient(circle at 32% 28%, #fffef9, #d9d1c0 75%)"
          : "radial-gradient(circle at 32% 28%, #6e675f, #26231e 78%)";
        const pBorder = isWhite ? "#cfc5b0" : "#171512";
        const pColor = isWhite ? "#6b4c35" : "#f5d78e";

        pieceHtml = `
          <span style="width: 74%; height: 74%; border-radius: 50%; background: ${pBg}; border: 2px solid ${pBorder}; box-shadow: 0 2px 4px rgba(0,0,0,0.35); display: flex; align-items: center; justify-content: center; font-size: 13px; line-height: 1; color: ${pColor}; font-weight: 800; z-index: 2;">
            ${isKing ? "♛" : ""}
          </span>
        `;
      }

      const numHtml = isPlayable
        ? `<span style="position: absolute; top: 2px; left: 3px; font-size: 8px; font-family: 'JetBrains Mono', monospace; color: rgba(255,255,255,0.75); line-height: 1;">${sq}</span>`
        : "";

      cellsHtml += `
        <div style="position: relative; aspect-ratio: 1 / 1; background: ${bg}; display: flex; align-items: center; justify-content: center; overflow: hidden;">
          ${numHtml}${pieceHtml}
        </div>
      `;
    }
  }

  return `
    <div style="max-width: 360px; width: 100%; margin: 0 auto; padding: 8px; border-radius: 12px; background: linear-gradient(145deg, #493724, #2b1d0e); box-shadow: 0 8px 20px rgba(43,29,14,0.22);">
      <div style="position: relative; width: 100%; aspect-ratio: 1 / 1; display: grid; grid-template-columns: repeat(10, 1fr); grid-template-rows: repeat(10, 1fr); border: 2px solid #2b1d0e; border-radius: 4px; overflow: hidden;">
        ${cellsHtml}
        ${buildCheckersArrowSvg(path, isIllegal)}
      </div>
    </div>
  `;
}

window.stepCheckersOverlayPly = function (delta) {
  if (!activeCheckersReplay || !activeCheckersReplay.turns) return;
  const next = activeCheckersPly + delta;
  if (next < 0 || next > activeCheckersReplay.turns.length) return;
  activeCheckersPly = next;
  updateCheckersScrubberDom();
};

window.jumpCheckersOverlayPly = function (val) {
  if (!activeCheckersReplay || !activeCheckersReplay.turns) return;
  activeCheckersPly = Math.max(0, Math.min(Number(val) || 0, activeCheckersReplay.turns.length));
  updateCheckersScrubberDom();
};

function updateCheckersScrubberDom() {
  const stage = document.getElementById("checkers-overlay-stage");
  if (!stage || !activeCheckersReplay) return;

  const turns = activeCheckersReplay.turns || [];
  const move = activeCheckersPly > 0 ? turns[activeCheckersPly - 1] : null;
  const board = getCheckersBoardAtPly(activeCheckersReplay, activeCheckersPly);
  const isIllegal = move && move.valid === false;

  const moveLabel = move
    ? `${move.player} (${move.model || ""}): ${move.move || move.raw_response || "—"}`
    : "Starting Position (Ply 0)";
  const statusBadge = !move
    ? `<span class="px-2 py-0.5 rounded bg-cream-bg border border-cream-border font-mono text-[10px]">START</span>`
    : isIllegal
      ? `<span class="px-2 py-0.5 rounded bg-wood-terracotta text-cream-bg font-mono text-[10px] font-bold">ILLEGAL / REJECTED</span>`
      : `<span class="px-2 py-0.5 rounded bg-wood-sage/20 text-wood-sage font-mono text-[10px] font-bold">LEGAL MOVE</span>`;

  stage.innerHTML = `
    <div class="p-4 rounded-2xl bg-cream-card border border-cream-border space-y-3">
      <div class="flex items-center justify-between gap-2 pb-2 border-b border-cream-border">
        <div class="flex items-center gap-1.5">
          <button type="button" onclick="jumpCheckersOverlayPly(0)" ${activeCheckersPly === 0 ? "disabled" : ""} class="px-2 py-1 rounded border border-cream-border bg-cream-bg text-xs font-mono disabled:opacity-40">|&lt;</button>
          <button type="button" onclick="stepCheckersOverlayPly(-1)" ${activeCheckersPly === 0 ? "disabled" : ""} class="px-2.5 py-1 rounded border border-cream-border bg-cream-bg text-xs font-mono font-bold disabled:opacity-40">← Prev</button>
          <button type="button" onclick="stepCheckersOverlayPly(1)" ${activeCheckersPly >= turns.length ? "disabled" : ""} class="px-2.5 py-1 rounded border border-cream-border bg-cream-bg text-xs font-mono font-bold disabled:opacity-40">Next →</button>
          <button type="button" onclick="jumpCheckersOverlayPly(${turns.length})" ${activeCheckersPly >= turns.length ? "disabled" : ""} class="px-2 py-1 rounded border border-cream-border bg-cream-bg text-xs font-mono disabled:opacity-40">&gt;|</button>
        </div>
        <span class="font-mono text-xs font-semibold text-wood-espresso">Ply ${activeCheckersPly} / ${turns.length}</span>
      </div>

      <input type="range" min="0" max="${turns.length}" value="${activeCheckersPly}" oninput="jumpCheckersOverlayPly(this.value)" style="accent-color: #6b4c35;" class="w-full cursor-pointer" />

      ${buildCheckersGridHtml(board, move)}

      <div class="p-3 rounded-xl bg-cream-bg border border-cream-border space-y-1">
        <div class="flex items-center justify-between gap-2">
          <span class="font-mono text-xs font-bold text-wood-espresso">${escapeHTML(moveLabel)}</span>
          ${statusBadge}
        </div>
        ${move ? `<p class="text-[11px] text-wood-umber">${escapeHTML(move.reason || "")}</p>` : ""}
      </div>
    </div>
  `;
}

async function loadCheckersReplayIntoOverlay(trialId) {
  const stage = document.getElementById("checkers-overlay-stage");
  if (!stage) return;
  stage.innerHTML = '<div class="p-4 text-center font-mono text-xs text-wood-umber">Loading 10×10 Draughts board from Supabase…</div>';

  try {
    const row = await fetchSingleReplay(trialId);
    if (!row || !row.replay_data || !Array.isArray(row.replay_data.turns)) {
      stage.innerHTML = '<div class="p-3 text-xs text-wood-umber">No turn-by-turn board log stored for this trial.</div>';
      return;
    }
    activeCheckersReplay = row.replay_data;
    activeCheckersPly = activeCheckersReplay.turns.length; // Jump straight to final/crash ply
    updateCheckersScrubberDom();
  } catch (err) {
    stage.innerHTML = `<div class="p-3 text-xs text-wood-terracotta">Could not load replay: ${escapeHTML(err.message)}</div>`;
  }
}