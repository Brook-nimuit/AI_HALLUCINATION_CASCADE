function checkAdminAccess() {
    const host = window.location.hostname;
    const isLocal = (host === "localhost" || host === "127.0.0.1" || simulatedAdmin);
    
    const adminTabBtn = document.getElementById("nav-admin");
    const hostDisplay = document.getElementById("hostname-display");
    
    hostDisplay.textContent = `Host: ${host || 'preview-sandbox'} ${isLocal ? '(Admin Active)' : '(Public Read-Only)'}`;
    
    if (isLocal) {
    adminTabBtn.classList.remove("hidden");
    adminTabBtn.classList.add("flex");
    } else {
    adminTabBtn.classList.add("hidden");
    adminTabBtn.classList.remove("flex");
    }
}

function toggleSimulatedAdmin() {
    simulatedAdmin = !simulatedAdmin;
    checkAdminAccess();
    if (simulatedAdmin) {
    switchTab("admin");
    showToast("Localhost Admin Console unlocked!");
    } else {
    switchTab("home");
    showToast("Switched to Audience Public View.");
    }
}
// --- 9. ADMIN CONSOLE HANDLERS ---
function handleAddTrial(e) {
    e.preventDefault();
    const newId = `TRIAL-${101 + appData.trials.length}`;
    const game = document.getElementById("admin-trial-game").value;
    const model = document.getElementById("admin-trial-model").value.trim();
    const temperature = parseFloat(document.getElementById("admin-trial-temp").value);
    const maxTokens = parseInt(document.getElementById("admin-trial-tokens").value, 10);
    const creditsBurned = parseFloat(document.getElementById("admin-trial-credits").value);
    const collapseTurn = parseInt(document.getElementById("admin-trial-collapse").value, 10);
    const illegalMovesCount = parseInt(document.getElementById("admin-trial-illegal").value, 10);
    const archetype = document.getElementById("admin-trial-archetype").value.trim();
    const outcome = document.getElementById("admin-trial-outcome").value;
    const promptUsed = document.getElementById("admin-trial-prompt").value.trim();
    const pgnLog = document.getElementById("admin-trial-pgn").value.trim();

    const newTrial = {
    id: newId,
    game,
    model,
    temperature,
    maxTokens,
    creditsBurned,
    collapseTurn,
    illegalMovesCount,
    archetype,
    outcome,
    promptUsed,
    pgnLog,
    steps: [
        { turn: "Turn 1", move: "Opening Sequence", status: "VALID", note: "Deterministic initialization." },
        { turn: `Turn ${collapseTurn} (COLLAPSE)`, move: "See PGN Transcript", status: "ILLEGAL", note: archetype }
    ]
    };

    appData.trials.unshift(newTrial);
    activeTrialId = newId;
    saveAppData();
    e.target.reset();
    showToast(`Saved ${newId} (${model}) to database!`);
    switchTab("trials");
}

function handleAddSource(e) {
    e.preventDefault();
    const category = document.getElementById("admin-src-category").value;
    const title = document.getElementById("admin-src-title").value.trim();
    const url = document.getElementById("admin-src-url").value.trim();
    const badge = document.getElementById("admin-src-badge").value.trim();
    const notes = document.getElementById("admin-src-notes").value.trim();

    appData.sources.unshift({
    id: `SRC-${Date.now()}`,
    category,
    title,
    url,
    badge,
    notes
    });

    saveAppData();
    e.target.reset();
    showToast("Added new entry to Sources & Media!");
    switchTab("sources");
}

function exportMasterJSON() {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(appData, null, 2));
    const dlAnchor = document.createElement("a");
    dlAnchor.setAttribute("href", dataStr);
    dlAnchor.setAttribute("download", "hallucination_cascade_dataset.json");
    document.body.appendChild(dlAnchor);
    dlAnchor.click();
    dlAnchor.remove();
    showToast("Exported master JSON dataset!");
}

function importMasterJSON(event) {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = function(e) {
    try {
        const parsed = JSON.parse(e.target.result);
        if (parsed.trials && parsed.sources) {
        appData = parsed;
        saveAppData();
        showToast("Imported master JSON dataset successfully!");
        } else {
        showToast("Invalid JSON structure: missing trials or sources.");
        }
    } catch (err) {
        showToast("Error parsing JSON file.");
    }
    };
    reader.readAsText(file);
}

function resetToDefaultData() {
    localStorage.removeItem(STORAGE_KEY);
    appData = JSON.parse(JSON.stringify(DEFAULT_DATA));
    activeTrialId = appData.trials[0].id;
    refreshAllViews();
    showToast("Restored default starter dataset.");
}

