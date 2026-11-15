// Updates the screen for the selected match and turn.

function renderTurnView(trial, turnIndex) {
  const turns = trial.turns || [];
  if (turns.length === 0) return;

  const turn = turns[turnIndex];
  const info = parseTurnInfo(turn);

  // 1. Headings and counters
  document.getElementById("boardHeading").textContent =
    turn.player + " (" + turn.model + ")";
  document.getElementById("plyCounter").textContent =
    "Turn " + turn.turn + " of " + turns.length;

  // 2. Center Discard Pile
  document.getElementById("discardSlot").innerHTML = createCardHtml(info.discardCard, "");

  // 3. Agent Action Slot (Card played, DRAW, or Illegal Attempt)
  const actionSlot = document.getElementById("actionSlot");
  if (info.rawAction.toUpperCase() === "DRAW") {
    actionSlot.innerHTML = createCardHtml("Deck DRAW", info.isValid ? "" : "uno-card-illegal");
  } else if (info.playedCard) {
    const statusClass = info.isValid ? "uno-card-played" : "uno-card-illegal";
    actionSlot.innerHTML = createCardHtml(info.playedCard, statusClass);
  } else {
    actionSlot.innerHTML = createCardHtml(info.rawAction || "Empty", "uno-card-illegal");
  }

  // 4. Active Player's Hand
  document.getElementById("handLabel").textContent =
    turn.player + " Hand (" + info.handCards.length + " cards)";

  let handHtml = "";
  let highlightedOnce = false;
  for (let i = 0; i < info.handCards.length; i++) {
    const card = info.handCards[i];
    let extra = "";
    if (!highlightedOnce && info.playedCard && card === info.playedCard) {
      extra = "uno-card-played";
      highlightedOnce = true;
    }
    handHtml += createCardHtml(card, extra);
  }
  document.getElementById("activeHandSlot").innerHTML = handHtml;

  // 5. Summary line & Right-side Move Inspector
  const statusWord = info.isValid ? "VALID" : "ILLEGAL / HALLUCINATION";
  document.getElementById("turnSummary").textContent =
    "Turn " + turn.turn + ": " + turn.player + " responded '" + info.rawAction + "' (" + info.reason + ")";

  document.getElementById("currentMove").innerHTML =
    "<strong>Status:</strong> " + statusWord + "<br>" +
    "<strong>Referee Reason:</strong> " + info.reason + "<br>" +
    "<strong>Raw Model Output:</strong> <code>" + info.rawAction + "</code>" +
    '<div class="prompt-preview">' + (turn.user_prompt || "") + "</div>";
}

function renderTurnTable(trial, activeIndex, onRowClick) {
  const tbody = document.getElementById("moveRows");
  tbody.innerHTML = "";
  const turns = trial.turns || [];
  document.getElementById("logCount").textContent = turns.length + " turns";

  for (let i = 0; i < turns.length; i++) {
    const t = turns[i];
    const info = parseTurnInfo(t);
    const tr = document.createElement("tr");
    if (i === activeIndex) {
      tr.style.fontWeight = "700";
    }
    tr.style.cursor = "pointer";
    tr.innerHTML =
      "<td>" + t.turn + "</td>" +
      "<td>" + t.player + "</td>" +
      "<td>" + info.discardCard + "</td>" +
      "<td><code>" + info.rawAction + "</code></td>" +
      "<td>" + (info.isValid ? "✅ " : "❌ ") + info.reason + "</td>";

    tr.addEventListener("click", function () {
      onRowClick(i);
    });
    tbody.appendChild(tr);
  }
}