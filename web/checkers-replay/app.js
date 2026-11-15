(() => {
  "use strict";

  const elements = {
    status: document.getElementById("loadStatus"),
    empty: document.getElementById("emptyState"),
    viewer: document.getElementById("viewer"),
    matchSelect: document.getElementById("matchSelect"),
    matchTitle: document.getElementById("matchTitle"),
    matchSubtitle: document.getElementById("matchSubtitle"),
    resultBadge: document.getElementById("resultBadge"),
    boardHeading: document.getElementById("boardHeading"),
    board: document.getElementById("board"),
    overlay: document.getElementById("moveOverlay"),
    sticker: document.getElementById("illegalSticker"),
    plyCounter: document.getElementById("plyCounter"),
    slider: document.getElementById("turnSlider"),
    first: document.getElementById("firstButton"),
    previous: document.getElementById("previousButton"),
    next: document.getElementById("nextButton"),
    last: document.getElementById("lastButton"),
    turnSummary: document.getElementById("turnSummary"),
    whiteModel: document.getElementById("whiteModel"),
    blackModel: document.getElementById("blackModel"),
    moveCount: document.getElementById("moveCount"),
    runId: document.getElementById("runId"),
    currentMove: document.getElementById("currentMove"),
    pdn: document.getElementById("pdnText"),
    logCount: document.getElementById("logCount"),
    moveRows: document.getElementById("moveRows"),
  };

  let activeAudit = null;
  let selectedPly = 0;

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[character]);
  }

  function squareCoordinate(square) {
    const index = square - 1;
    const row = Math.floor(index / 5);
    const offset = index % 5;
    return { row, column: 2 * offset + (row % 2 === 0 ? 1 : 0) };
  }

  function coordinateSquare(row, column) {
    if (row < 0 || row > 9 || column < 0 || column > 9 || (row + column) % 2 !== 1) {
      return null;
    }
    return row * 5 + Math.floor(column / 2) + 1;
  }

  function pieceName(piece) {
    const color = piece.toLowerCase() === "w" ? "White" : "Black";
    return piece === piece.toUpperCase() ? `${color} king` : `${color} man`;
  }

  function renderMoveOverlay(path, illegal) {
    elements.overlay.innerHTML = "";
    if (!Array.isArray(path) || path.length < 2) return;

    const validPoints = [];
    for (let i = 0; i < path.length; i++) {
      const sq = Number(path[i]);
      if (sq >= 1 && sq <= 50) {
        const { row, column } = squareCoordinate(sq);
        validPoints.push(`${(column + 0.5) * 10},${(row + 0.5) * 10}`);
      }
    }
    if (validPoints.length < 2) return;

    const color = illegal ? "#ee3932" : "#f6c849";
    elements.overlay.innerHTML = `
      <defs>
        <marker id="moveArrowHead" markerWidth="4.5" markerHeight="4.5" refX="3.5" refY="2.25" orient="auto" markerUnits="strokeWidth">
          <path d="M0,0 L4.5,2.25 L0,4.5 z" fill="${color}"></path>
        </marker>
      </defs>
      <polyline class="move-arrow${illegal ? " illegal" : ""}" points="${validPoints.join(" ")}" marker-end="url(#moveArrowHead)"></polyline>`;
  }

  function renderBoard(board, move) {
    const safeBoard = board || {};
    const lastPath = move?.valid ? move.parsed_path : null;
    const invalidPath = move?.valid === false ? move.parsed_path : null;
    const lastSquares = new Set(Array.isArray(lastPath) ? lastPath : []);
    const invalidSquares = new Set(Array.isArray(invalidPath) ? invalidPath : []);
    const cells = [];

    for (let row = 0; row < 10; row += 1) {
      for (let column = 0; column < 10; column += 1) {
        const square = coordinateSquare(row, column);
        const cellClasses = ["square"];
        if (square !== null) cellClasses.push("playable");
        if (lastSquares.has(square)) cellClasses.push("last-move");
        if (invalidSquares.has(square)) cellClasses.push("invalid-square");
        const piece = square === null ? null : safeBoard[String(square)];
        const label = square === null
          ? "Light square"
          : `Square ${square}${piece ? `, ${pieceName(piece)}` : ", empty"}`;
        const number = square === null
          ? ""
          : `<span class="square-number">${square}</span>`;
        const pieceMarkup = piece
          ? `<span class="piece ${piece.toLowerCase() === "w" ? "white-piece" : "black-piece"} ${piece === piece.toUpperCase() ? "king" : ""}" aria-hidden="true"></span>`
          : "";
        cells.push(
          `<div class="${cellClasses.join(" ")}" role="gridcell" aria-label="${label}">${number}${pieceMarkup}</div>`,
        );
      }
    }

    elements.board.innerHTML = cells.join("");
    renderMoveOverlay(invalidPath || lastPath, move?.valid === false);
    elements.sticker.hidden = move?.valid !== false;
  }

  function boardAt(audit, ply) {
    if (ply <= 0) {
      return audit.initial_board || audit.initial_state?.board || {};
    }
    return audit.turns[ply - 1]?.post_board || {};
  }

  function outcome(audit) {
    return audit.result
      || (audit.failed
        ? "Trial failed"
        : audit.winner
          ? `${audit.winner} wins`
          : audit.draw
            ? "Draw"
            : "Match stopped");
  }

  function playerModel(audit, player) {
    return audit.players?.[player] || `Unknown ${player} model`;
  }

  function renderRows(audit) {
    const turns = audit.turns || [];
    elements.moveRows.innerHTML = turns.map((turn, index) => {
      const legal = turn.valid === true;
      const notation = turn.move || (Array.isArray(turn.parsed_path)
        ? turn.parsed_path.join(" → ")
        : turn.raw_response || "No move parsed");
      const reason = turn.reason || (legal ? "Legal move." : "Rejected.");
      return `<tr class="${legal ? "" : "illegal-row"}" data-ply="${index + 1}">
        <td><button class="move-select" type="button" data-ply="${index + 1}">${turn.ply ?? index + 1}</button></td>
        <td>${escapeHtml(turn.player || "?")}</td>
        <td>${escapeHtml(turn.model || playerModel(audit, turn.player))}</td>
        <td>${escapeHtml(notation)}</td>
        <td><span class="status-pill ${legal ? "" : "invalid"}">${legal ? "Legal" : "Illegal"}</span></td>
        <td>${escapeHtml(reason)}</td>
      </tr>`;
    }).join("") || '<tr><td colspan="6">No move records in this audit.</td></tr>';
    elements.logCount.textContent = `${turns.length} ${turns.length === 1 ? "ply" : "plies"}`;
    elements.moveRows.querySelectorAll("[data-ply]").forEach((button) => {
      button.addEventListener("click", () => {
        selectedPly = Number(button.dataset.ply);
        updatePly();
      });
    });
  }

  function updatePly() {
    if (!activeAudit) return;
    const turns = activeAudit.turns || [];
    selectedPly = Math.max(0, Math.min(selectedPly, turns.length));
    const move = selectedPly > 0 ? turns[selectedPly - 1] : null;
    renderBoard(boardAt(activeAudit, selectedPly), move);
    elements.boardHeading.textContent = move
      ? `${move.player || "?"} moved · ply ${move.ply ?? selectedPly}`
      : "Starting position";
    elements.plyCounter.textContent = selectedPly === 0
      ? "Start"
      : `Ply ${selectedPly} / ${turns.length}`;
    elements.slider.value = String(selectedPly);
    elements.first.disabled = selectedPly === 0;
    elements.previous.disabled = selectedPly === 0;
    elements.next.disabled = selectedPly >= turns.length;
    elements.last.disabled = selectedPly >= turns.length;

    if (!move) {
      elements.turnSummary.textContent = "Starting board before either player has moved.";
      elements.currentMove.innerHTML = "<strong>Before the first ply</strong><span>Use the controls or move log to step through the match.</span>";
      elements.currentMove.classList.remove("failure");
      return;
    }

    const legal = move.valid === true;
    const notation = move.move || (Array.isArray(move.parsed_path)
      ? move.parsed_path.join(" → ")
      : move.raw_response || "No move parsed");
    elements.turnSummary.textContent = legal
      ? `${move.player} played ${notation}.`
      : `${move.player}'s attempted move was illegal and was not applied.`;
    elements.currentMove.classList.toggle("failure", !legal);
    elements.currentMove.innerHTML = `<strong>${legal ? "Legal move" : "Illegal move"} · ${escapeHtml(move.player || "?")}</strong><span>${escapeHtml(notation)}</span><span>${escapeHtml(move.reason || (legal ? "Move accepted." : "Rejected by the rules engine."))}</span>`;
  }

  async function selectCloudMatchById(trialId) {
    if (!trialId) return;
    elements.status.textContent = "Loading replay from Supabase Cloud…";
    elements.status.classList.remove("error");

    try {
      const row = await fetchSingleReplay(trialId);
      if (!row || !row.replay_data) {
        throw new Error("Replay payload not found in trial_replays.");
      }

      activeAudit = row.replay_data;
      const turns = activeAudit.turns || [];

      elements.viewer.hidden = false;
      elements.empty.hidden = true;
      elements.matchTitle.textContent = `${activeAudit.players?.White || "White"} vs ${activeAudit.players?.Black || "Black"}`;
      elements.matchSubtitle.textContent = `Trial ${activeAudit.trial_id ?? "?"} · ${activeAudit.variant || "International Draughts (10×10)"}`;
      elements.resultBadge.textContent = outcome(activeAudit);
      elements.resultBadge.classList.toggle("failure", activeAudit.failed === true);
      elements.whiteModel.textContent = playerModel(activeAudit, "White");
      elements.blackModel.textContent = playerModel(activeAudit, "Black");
      elements.moveCount.textContent = String(turns.length);
      elements.runId.textContent = activeAudit.run_id || "—";
      elements.pdn.textContent = activeAudit.pdn || "No PDN record is embedded in this audit.";
      elements.slider.max = String(turns.length);
      elements.slider.disabled = turns.length === 0;

      renderRows(activeAudit);
      selectedPly = turns.length; // Open directly on the final/crash ply
      updatePly();
      elements.status.textContent = `Synchronized with Supabase Cloud · Viewing ${trialId}`;
    } catch (err) {
      elements.status.textContent = `Could not load cloud replay: ${err.message}`;
      elements.status.classList.add("error");
    }
  }

  async function initCloudCheckersViewer() {
    try {
      const allRows = await fetchAllCatalogTrials();
      const checkersRows = allRows.filter(
        (r) => String(r.game || "").toLowerCase() === "checkers"
      );

      if (checkersRows.length === 0) {
        elements.status.textContent = "No Checkers trials found in Supabase.";
        return;
      }

      const params = new URLSearchParams(window.location.search);
      const requestedId = params.get("trial_id");
      let activeId = checkersRows[0].trial_id;

      elements.matchSelect.innerHTML = checkersRows
        .map((r) => {
          if (requestedId && r.trial_id === requestedId) {
            activeId = r.trial_id;
          }
          const parts = String(r.trial_id).split("__");
          const shortTrial = parts.length >= 4 ? parts[3] : r.trial_id;
          const tag = r.status === "completed" ? "Completed" : (r.status === "api_error" ? "Timeout" : "Illegal");
          return `<option value="${escapeHtml(r.trial_id)}">${escapeHtml(r.white_model)} vs ${escapeHtml(r.black_model)} · ${escapeHtml(shortTrial)} (${r.plies_survived} plies · ${tag})</option>`;
        })
        .join("");

      elements.matchSelect.disabled = false;
      elements.matchSelect.value = activeId;
      await selectCloudMatchById(activeId);
    } catch (err) {
      elements.status.textContent = `Supabase connection error: ${err.message}`;
      elements.status.classList.add("error");
    }
  }

  elements.matchSelect.addEventListener("change", () => {
    const nextId = elements.matchSelect.value;
    if (!nextId) return;
    history.replaceState(null, "", `?trial_id=${encodeURIComponent(nextId)}`);
    selectCloudMatchById(nextId);
  });
  elements.first.addEventListener("click", () => { selectedPly = 0; updatePly(); });
  elements.previous.addEventListener("click", () => { selectedPly -= 1; updatePly(); });
  elements.next.addEventListener("click", () => { selectedPly += 1; updatePly(); });
  elements.last.addEventListener("click", () => {
    selectedPly = activeAudit?.turns?.length ?? 0;
    updatePly();
  });
  elements.slider.addEventListener("input", () => {
    selectedPly = Number(elements.slider.value);
    updatePly();
  });

  initCloudCheckersViewer();
})();
