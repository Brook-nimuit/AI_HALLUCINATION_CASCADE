// Controls loading UNO trials, picking a match, and stepping through turns.

let allTrials = [];
let currentTrialIndex = 0;
let currentTurnIndex = 0;

const fileInput = document.getElementById("auditFiles");
const matchSelect = document.getElementById("matchSelect");
const turnSlider = document.getElementById("turnSlider");

// Hide manual file loader on live Vercel site if preloaded data exists
const isLocalhost =
  window.location.hostname === "localhost" ||
  window.location.hostname === "127.0.0.1";

function loadTrialsFromJsonObject(jsonData, sourceName) {
  if (Array.isArray(jsonData.trials)) {
    for (let i = 0; i < jsonData.trials.length; i++) {
      const item = jsonData.trials[i];
      item._sourceFile = sourceName;
      allTrials.push(item);
    }
  } else if (Array.isArray(jsonData.turns)) {
    jsonData._sourceFile = sourceName;
    allTrials.push(jsonData);
  }
}

function populateMatchDropdown() {
  matchSelect.innerHTML = "";
  for (let i = 0; i < allTrials.length; i++) {
    const trial = allTrials[i];
    const option = document.createElement("option");
    option.value = String(i);
    const statusTag = trial.failed ? "❌ FAILED" : "✅ SURVIVED";
    const idLabel = trial.trial_id || "Trial " + (i + 1);
    option.textContent =
      idLabel + " · " + statusTag + " (" + (trial.turns_survived || 0) + " turns)";
    matchSelect.appendChild(option);
  }
}

function selectMatch(index) {
  currentTrialIndex = index;
  const trial = allTrials[currentTrialIndex];
  const turns = trial.turns || [];

  // Default to the final turn so you immediately see the crash or completion
  currentTurnIndex = turns.length > 0 ? turns.length - 1 : 0;

  document.getElementById("emptyState").hidden = true;
  document.getElementById("viewer").hidden = false;

  const modelName = turns.length > 0 ? turns[0].model : (trial.model || "gpt-4o");
  document.getElementById("matchTitle").textContent =
    (trial.trial_id || "Trial " + (index + 1)) + " (" + modelName + ")";
  document.getElementById("matchSubtitle").textContent =
    trial.failure_reason || "Completed";
  document.getElementById("resultBadge").textContent =
    trial.failed ? "Failed: " + trial.failure_reason : "Survived 50 Turns";

  document.getElementById("agentAModel").textContent = modelName;
  document.getElementById("agentBModel").textContent = modelName;
  document.getElementById("moveCount").textContent = String(turns.length);
  document.getElementById("runId").textContent = trial._sourceFile || "Local JSON";

  turnSlider.max = String(Math.max(0, turns.length - 1));
  goToTurn(currentTurnIndex);
}

function goToTurn(turnIdx) {
  const trial = allTrials[currentTrialIndex];
  const turns = trial.turns || [];
  if (turns.length === 0) return;

  if (turnIdx < 0) turnIdx = 0;
  if (turnIdx >= turns.length) turnIdx = turns.length - 1;
  currentTurnIndex = turnIdx;

  turnSlider.value = String(currentTurnIndex);
  renderTurnView(trial, currentTurnIndex);
  renderTurnTable(trial, currentTurnIndex, goToTurn);
}

// 1. Handle selecting local JSON files
fileInput.addEventListener("change", async function (event) {
  const files = event.target.files;
  if (!files || files.length === 0) return;

  allTrials = [];
  for (let i = 0; i < files.length; i++) {
    const text = await files[i].text();
    const parsed = JSON.parse(text);
    loadTrialsFromJsonObject(parsed, files[i].name);
  }

  document.getElementById("loadStatus").textContent =
    "Loaded " + allTrials.length + " UNO trials.";
  populateMatchDropdown();
  if (allTrials.length > 0) selectMatch(0);
});

// 2. Controls & keyboard navigation
matchSelect.addEventListener("change", function () {
  selectMatch(Number(matchSelect.value));
});
turnSlider.addEventListener("input", function () {
  goToTurn(Number(turnSlider.value));
});
document.getElementById("firstButton").addEventListener("click", function () {
  goToTurn(0);
});
document.getElementById("previousButton").addEventListener("click", function () {
  goToTurn(currentTurnIndex - 1);
});
document.getElementById("nextButton").addEventListener("click", function () {
  goToTurn(currentTurnIndex + 1);
});
document.getElementById("lastButton").addEventListener("click", function () {
  const turns = allTrials[currentTrialIndex].turns || [];
  goToTurn(turns.length - 1);
});

// 3. Optional auto-load if /data/uno_trials.json is bundled for Vercel
fetch("/data/uno_trials.json")
  .then(function (res) {
    if (!res.ok) throw new Error("No static bundle yet");
    return res.json();
  })
  .then(function (data) {
    loadTrialsFromJsonObject(data, "uno_trials.json");
    if (allTrials.length > 0) {
      if (!isLocalhost) document.getElementById("localToolbar").hidden = true;
      document.getElementById("loadStatus").textContent =
        "Auto-loaded " + allTrials.length + " UNO trials.";
      populateMatchDropdown();
      selectMatch(0);
    }
  })
  .catch(function () {
    // Normal when running locally before building static bundle
  });