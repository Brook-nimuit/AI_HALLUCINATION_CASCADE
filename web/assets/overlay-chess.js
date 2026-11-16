// web/assets/overlay-chess.js
// Renders an interactive 8x8 FEN chessboard scrubber inside the slide-up overlay.

let activeChessReplay = null;
let activeChessPly = 0;

const CHESS_UNICODE = {
  K: "♔", Q: "♕", R: "♖", B: "♗", N: "♘", P: "♙",
  k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟"
};
const START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

function parseFenBoard(fenStr) {
  const boardPart = String(fenStr || START_FEN).split(" ")[0];
  const rows = boardPart.split("/");
  const grid = [];
  for (let r = 0; r < 8; r++) {
    const rowArr = [];
    const rowStr = rows[r] || "";
    for (let i = 0; i < rowStr.length; i++) {
      const ch = rowStr[i];
      if (ch >= "1" && ch <= "8") {
        const emptyCount = Number(ch);
        for (let k = 0; k < emptyCount; k++) rowArr.push(null);
      } else {
        rowArr.push(ch);
      }
    }
    while (rowArr.length < 8) rowArr.push(null);
    grid.push(rowArr);
  }
  return grid;
}

function algebraicToRowCol(sq) {
  if (!sq || typeof sq !== "string" || sq.length !== 2) return null;
  const col = sq.toLowerCase().charCodeAt(0) - 97;
  const row = 8 - Number(sq[1]);
  if (col < 0 || col > 7 || row < 0 || row > 7) return null;
  return { row: row, col: col };
}

function inferChessIllegalSquares(moveObj) {
  if (!moveObj) return [null, null];
  const ill = moveObj.illegal_move;
  if (ill && ill.from_square && ill.to_square) {
    return [ill.from_square, ill.to_square];
  }
  const text = [moveObj.reason, moveObj.raw_response, moveObj.move]
    .filter(Boolean)
    .join(" ");
  const uci = text.match(/\b([a-h][1-8])([a-h][1-8])(?:[qrbn])?\b/i);
  if (uci) return [uci[1].toLowerCase(), uci[2].toLowerCase()];
  const m = text.match(/\b([a-h][1-8])\s*(?:→|->|-|\bto\b)\s*([a-h][1-8])\b/i);
  if (m) return [m[1].toLowerCase(), m[2].toLowerCase()];
  return [null, null];
}

function getFenPieceSquares(fen) {
  const squares = {};
  const rows = String(fen || "").split(" ")[0].split("/");
  for (let row = 0; row < rows.length && row < 8; row++) {
    let col = 0;
    for (const ch of rows[row]) {
      if (ch >= "1" && ch <= "8") {
        col += Number(ch);
      } else if (col < 8) {
        squares[String.fromCharCode(97 + col) + String(8 - row)] = ch;
        col += 1;
      }
    }
  }
  return squares;
}

function inferChessLastMoveSquares(moveObj) {
  if (!moveObj || !moveObj.pre_fen || !moveObj.post_fen) return [null, null];
  const before = getFenPieceSquares(moveObj.pre_fen);
  const after = getFenPieceSquares(moveObj.post_fen);
  const changedFrom = Object.keys(before).filter(square => before[square] && !after[square]);
  const changedTo = Object.keys(after).filter(square => after[square] && before[square] !== after[square]);
  const san = String(moveObj.san || "");
  const piece = san.startsWith("O-O") ? "k" : (/^[KQRBN]/.test(san) ? san[0].toLowerCase() : "p");
  const from = changedFrom.find(square => before[square].toLowerCase() === piece) || changedFrom[0];
  const to = changedTo.find(square => after[square].toLowerCase() === piece) || changedTo[0];
  return [from || null, to || null];
}

function buildChessOverlayBoardHtml(fen, moveObj, highlightLastMove) {
  const grid = parseFenBoard(fen);
  const moveStatus = String(moveObj && moveObj.status || "").toUpperCase();
  const isIllegal = Boolean(moveObj && moveStatus && moveStatus !== "LEGAL");
  const [fromSquare, toSquare] = isIllegal
    ? inferChessIllegalSquares(moveObj)
    : (highlightLastMove ? inferChessLastMoveSquares(moveObj) : [null, null]);
  const fromCoord = algebraicToRowCol(fromSquare);
  const toCoord = algebraicToRowCol(toSquare);
  const arrowColor = isIllegal ? "#dc2626" : "#facc15";
  const dashAttr = isIllegal ? 'stroke-dasharray="2.5 1.5"' : "";

  let cellsHtml = "";
  for (let r = 0; r < 8; r++) {
    for (let c = 0; c < 8; c++) {
      const sqName = String.fromCharCode(97 + c) + String(8 - r);
      const isLight = (r + c) % 2 === 0;
      let bg = isLight ? "#eeeed2" : "#769656";
      if (sqName === toSquare) bg = isIllegal ? "#e05246" : "#e6c35c";
      else if (sqName === fromSquare) bg = "#e6c35c";

      const piece = grid[r][c];
      const isWhitePiece = piece && piece === piece.toUpperCase();
      const pieceHtml = piece
        ? `<span style="font-size: 26px; line-height: 1; color: ${isWhitePiece ? "#ffffff" : "#18181b"}; text-shadow: ${isWhitePiece ? "0 1px 3px rgba(0,0,0,0.85)" : "0 1px 2px rgba(255,255,255,0.4)"}; user-select: none;">${CHESS_UNICODE[piece] || ""}</span>`
        : "";

      const rankLabel = c === 0
        ? `<span style="position: absolute; top: 2px; left: 3px; font-size: 8px; font-family: 'JetBrains Mono', monospace; font-weight: 700; color: ${isLight ? "#769656" : "#eeeed2"};">${8 - r}</span>`
        : "";
      const fileLabel = r === 7
        ? `<span style="position: absolute; bottom: 1px; right: 3px; font-size: 8px; font-family: 'JetBrains Mono', monospace; font-weight: 700; color: ${isLight ? "#769656" : "#eeeed2"};">${String.fromCharCode(97 + c)}</span>`
        : "";
      const blunderBadge = isIllegal && sqName === toSquare
        ? `<span style="position: absolute; top: 2px; right: 2px; background: #d71920; color: #fff; font-size: 8px; font-weight: 900; padding: 1px 3px; border-radius: 99px; border: 1px solid #fff;">?!</span>`
        : "";

      cellsHtml += `
        <div style="position: relative; aspect-ratio: 1 / 1; background: ${bg}; display: flex; align-items: center; justify-content: center;">
          ${rankLabel}${fileLabel}${pieceHtml}${blunderBadge}
        </div>
      `;
    }
  }

  let arrowSvg = "";
  if (fromCoord && toCoord) {
    const x1 = (fromCoord.col + 0.5) * 12.5;
    const y1 = (fromCoord.row + 0.5) * 12.5;
    const x2 = (toCoord.col + 0.5) * 12.5;
    const y2 = (toCoord.row + 0.5) * 12.5;
    arrowSvg = `
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" style="position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; z-index: 5;">
        <defs>
          <marker id="chessLastMoveArrow" markerWidth="4.5" markerHeight="4.5" refX="3.5" refY="2.25" orient="auto">
            <path d="M0,0 L4.5,2.25 L0,4.5 z" fill="${arrowColor}"></path>
          </marker>
        </defs>
        <line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${arrowColor}" stroke-width="1.8" ${dashAttr} marker-end="url(#chessLastMoveArrow)"></line>
      </svg>
    `;
  }

  return `
    <div style="max-width: 340px; width: 100%; margin: 0 auto; padding: 8px; border-radius: 12px; background: linear-gradient(145deg, #3b2a1e, #24180e); box-shadow: 0 8px 20px rgba(43,29,14,0.22);">
      <div style="position: relative; width: 100%; aspect-ratio: 1 / 1; display: grid; grid-template-columns: repeat(8, 1fr); grid-template-rows: repeat(8, 1fr); border: 2px solid #24180e; border-radius: 4px; overflow: hidden;">
        ${cellsHtml}
        ${arrowSvg}
      </div>
    </div>
  `;
}

window.stepChessOverlayPly = function (delta) {
  if (!activeChessReplay || !activeChessReplay.moves) return;
  const next = activeChessPly + delta;
  if (next < 0 || next > activeChessReplay.moves.length) return;
  activeChessPly = next;
  updateChessScrubberDom();
};

window.jumpChessOverlayPly = function (val) {
  if (!activeChessReplay || !activeChessReplay.moves) return;
  activeChessPly = Math.max(0, Math.min(Number(val) || 0, activeChessReplay.moves.length));
  updateChessScrubberDom();
};

function updateChessScrubberDom() {
  const stage = document.getElementById("chess-overlay-stage");
  if (!stage || !activeChessReplay) return;

  const moves = activeChessReplay.moves || [];
  const move = activeChessPly > 0 ? moves[activeChessPly - 1] : null;
  const fen = !move
    ? START_FEN
    : (move.status === "LEGAL" ? (move.post_fen || START_FEN) : (move.pre_fen || START_FEN));
  const isIllegal = move && move.status !== "LEGAL";

  const moveLabel = move
    ? `${move.actor || "?"} (${move.bot || ""}): ${move.san || move.raw_response || "—"}`
    : "Starting Position (Ply 0)";
  const statusBadge = !move
    ? `<span class="px-2 py-0.5 rounded bg-cream-bg border border-cream-border font-mono text-[10px]">START</span>`
    : isIllegal
      ? `<span class="px-2 py-0.5 rounded bg-wood-terracotta text-cream-bg font-mono text-[10px] font-bold">ILLEGAL / REJECTED</span>`
      : `<span class="px-2 py-0.5 rounded bg-wood-sage/20 text-wood-sage font-mono text-[10px] font-bold">LEGAL SAN</span>`;

  stage.innerHTML = `
    <div class="p-4 rounded-2xl bg-cream-card border border-cream-border space-y-3">
      <div class="flex items-center justify-between gap-2 pb-2 border-b border-cream-border">
        <div class="flex items-center gap-1.5">
          <button type="button" onclick="jumpChessOverlayPly(0)" ${activeChessPly === 0 ? "disabled" : ""} class="px-2 py-1 rounded border border-cream-border bg-cream-bg text-xs font-mono disabled:opacity-40">|&lt;</button>
          <button type="button" onclick="stepChessOverlayPly(-1)" ${activeChessPly === 0 ? "disabled" : ""} class="px-2.5 py-1 rounded border border-cream-border bg-cream-bg text-xs font-mono font-bold disabled:opacity-40">← Prev</button>
          <button type="button" onclick="stepChessOverlayPly(1)" ${activeChessPly >= moves.length ? "disabled" : ""} class="px-2.5 py-1 rounded border border-cream-border bg-cream-bg text-xs font-mono font-bold disabled:opacity-40">Next →</button>
          <button type="button" onclick="jumpChessOverlayPly(${moves.length})" ${activeChessPly >= moves.length ? "disabled" : ""} class="px-2 py-1 rounded border border-cream-border bg-cream-bg text-xs font-mono disabled:opacity-40">&gt;|</button>
        </div>
        <span class="font-mono text-xs font-semibold text-wood-espresso">Ply ${activeChessPly} / ${moves.length}</span>
      </div>

      <input type="range" min="0" max="${moves.length}" value="${activeChessPly}" oninput="jumpChessOverlayPly(this.value)" style="accent-color: #6b4c35;" class="w-full cursor-pointer" />

      ${buildChessOverlayBoardHtml(fen, move)}

      <div class="p-3 rounded-xl bg-cream-bg border border-cream-border space-y-1">
        <div class="flex items-center justify-between gap-2">
          <span class="font-mono text-xs font-bold text-wood-espresso">${escapeHTML(moveLabel)}</span>
          ${statusBadge}
        </div>
        ${move && move.reason ? `<p class="text-[11px] text-wood-umber">${escapeHTML(move.reason)}</p>` : ""}
      </div>
    </div>
  `;
}

async function loadChessReplayIntoOverlay(trialId) {
  const stage = document.getElementById("chess-overlay-stage");
  if (!stage) return;
  stage.innerHTML = `
    <div class="p-8 rounded-2xl bg-cream-card border border-cream-border flex flex-col items-center justify-center gap-3 text-center">
      <div class="fetching-match-spinner"></div>
      <div class="font-mono text-xs font-bold tracking-widest uppercase text-wood-walnut">FETCHING MATCH</div>
      <p class="text-[11px] text-wood-umber">Streaming turn-by-turn state log from Supabase Cloud…</p>
    </div>
  `;

  try {
    const row = await fetchSingleReplay(trialId);
    if (!row || !row.replay_data || !Array.isArray(row.replay_data.moves)) {
      stage.innerHTML = '<div class="p-3 text-xs text-wood-umber">No turn-by-turn chess log stored for this trial.</div>';
      return;
    }
    activeChessReplay = row.replay_data;
    activeChessPly = activeChessReplay.moves.length; // Open directly on the final/crash ply
    updateChessScrubberDom();
  } catch (err) {
    stage.innerHTML = `<div class="p-3 text-xs text-wood-terracotta">Could not load chess replay: ${escapeHTML(err.message)}</div>`;
  }
}
