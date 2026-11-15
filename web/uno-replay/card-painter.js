// Simple helper functions to read turn data and build UNO card HTML.

function parseTurnInfo(turn) {
  let discardCard = "Unknown";
  let handCards = [];
  const promptText = turn.user_prompt || "";

  // 1. Read Active Discard Card from prompt lines
  const lines = promptText.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();

    if (line.startsWith("Active Discard Card:")) {
      discardCard = line.replace("Active Discard Card:", "").trim();
    }

    if (line.startsWith("Cards Currently In Your Hand:")) {
      const bracketStart = line.indexOf("[");
      const bracketEnd = line.indexOf("]");
      if (bracketStart !== -1 && bracketEnd !== -1) {
        const inside = line.slice(bracketStart + 1, bracketEnd).trim();
        if (inside.length > 0) {
          const rawList = inside.split(",");
          for (let j = 0; j < rawList.length; j++) {
            handCards.push(rawList[j].trim());
          }
        }
      }
    }
  }

  // 2. Read what the AI tried to do ("PLAY Yellow 4" or "DRAW")
  const rawAction = (turn.raw_response || turn.action || "").trim();
  let playedCard = "";
  if (rawAction.toUpperCase().startsWith("PLAY ")) {
    playedCard = rawAction.slice(5).trim();
  }

  return {
    discardCard: discardCard,
    handCards: handCards,
    rawAction: rawAction,
    playedCard: playedCard,
    isValid: Boolean(turn.valid),
    reason: turn.reason || ""
  };
}

function createCardHtml(cardName, extraClass) {
  const cleanName = (cardName || "Unknown").trim();
  const words = cleanName.split(" ");
  const firstWord = words[0];

  let colorClass = "uno-neutral";
  if (firstWord === "Red") colorClass = "uno-red";
  else if (firstWord === "Yellow") colorClass = "uno-yellow";
  else if (firstWord === "Green") colorClass = "uno-green";
  else if (firstWord === "Blue") colorClass = "uno-blue";

  let valueText = cleanName;
  if (words.length > 1) {
    valueText = words.slice(1).join(" ");
  }

  const bonusClass = extraClass ? " " + extraClass : "";

  return (
    '<div class="uno-card ' + colorClass + bonusClass + '">' +
      '<span class="uno-card-color">' + firstWord + '</span>' +
      '<span class="uno-card-value">' + valueText + '</span>' +
    '</div>'
  );
}