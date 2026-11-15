// web/assets/comparison-helpers.js
// Constants and simple text helpers for the AI Models Comparison page.

const GAME_DESCRIPTIONS = {
  "chess": "High branching factor (35+ legal moves/turn). Extreme sensitivity to coordinate occlusion and piece memory.",
  "checkers": "10x10 International Draughts. Mandatory maximum-capture chains across deep diagonal trajectories.",
  "uno": "Non-spatial hand inventory management. Tests color/value matching and hidden card tracking.",
  "connect-four": "Vertical gravity constraint (7x6 grid). Tests column stacking and diagonal threat detection.",
  "tic-tac-toe": "3x3 baseline control benchmark verifying basic board occupancy memory."
};

const ARCHETYPE_FALLBACKS = {
  "chess": "Coordinate Desync & Illegal Trajectory",
  "checkers": "Mandatory Max-Capture Violation",
  "uno": "Hallucinated Card Not in Hand",
  "connect-four": "Gravity / Column Overflow Drift",
  "tic-tac-toe": "Occupied Square Overwrite"
};

function formatGameTitle(slug) {
  const clean = String(slug || "").toLowerCase().trim();
  if (clean === "uno") return "UNO";
  if (clean === "tic-tac-toe") return "Tic-Tac-Toe";
  if (clean === "connect-four") return "Connect Four";

  const words = clean.replaceAll("-", " ").split(" ");
  for (let i = 0; i < words.length; i++) {
    if (words[i].length > 0) {
      words[i] = words[i][0].toUpperCase() + words[i].slice(1);
    }
  }
  return words.join(" ");
}

function inferProvider(modelName) {
  const lower = String(modelName || "").toLowerCase();
  if (lower.includes("gpt") || lower.includes("o1") || lower.includes("o3")) return "OpenAI";
  if (lower.includes("claude")) return "Anthropic";
  if (lower.includes("gemini")) return "Google";
  if (lower.includes("llama")) return "Meta";
  if (lower.includes("deepseek")) return "DeepSeek";
  if (lower.includes("qwen")) return "Alibaba";
  if (lower.includes("mistral")) return "Mistral";
  return "LLM Agent";
}

// Makes Supabase rows (white_model/plies_survived) and local rows (model/turns) look identical
function normalizeTrialRecord(raw) {
  const statusRaw = String(raw.status || "").toLowerCase();
  const isApiError = statusRaw === "api_error" || statusRaw === "partial_api_error";
  const isIllegal = statusRaw === "illegal_move" || statusRaw === "invalid_or_illegal";

  return {
    game: String(raw.game || "").toLowerCase().trim(),
    modelA: String(raw.white_model || raw.model || "").trim(),
    modelB: String(raw.black_model || raw.opponent_model || "").trim(),
    isApiError: isApiError,
    isIllegal: isIllegal,
    turns: Number(raw.plies_survived ?? raw.turns ?? 0) || 0,
    reason: String(raw.failure_reason || raw.reason || "")
  };
}

// Checks which model caused the illegal move
function identifyCulpritModel(trial) {
  const reason = trial.reason;
  const lowerReason = reason.toLowerCase();
  const m1 = trial.modelA;
  const m2 = trial.modelB;

  // 1. Check bracket prefix like "[White / gpt-6.1-terra]"
  const closeBracket = reason.indexOf("]");
  if (reason.startsWith("[") && closeBracket !== -1) {
    const inside = reason.slice(1, closeBracket).toLowerCase();
    if (m1 && inside.includes(m1.toLowerCase())) return m1;
    if (m2 && inside.includes(m2.toLowerCase())) return m2;
  }

  // 2. Check if only one model name appears in the failure text
  const m1InReason = m1 && lowerReason.includes(m1.toLowerCase());
  const m2InReason = m2 && lowerReason.includes(m2.toLowerCase());
  if (m1InReason && !m2InReason) return m1;
  if (m2InReason && !m1InReason) return m2;

  // 3. If a model played against itself (or single-model log), blame m1
  if (m1 && (m1 === m2 || !m2)) return m1;

  return m1 || null;
}

// Pulls out a short failure label from the reason text
function extractArchetypeFromReason(reason) {
  const text = String(reason || "").split("[Snapshot:")[0].trim();
  if (!text) return null;

  // Look for text inside parentheses like "(Overwrote 'R')"
  const openParen = text.indexOf("(");
  const closeParen = text.indexOf(")", openParen + 1);
  if (openParen !== -1 && closeParen !== -1) {
    const inside = text.slice(openParen + 1, closeParen).trim();
    if (inside && !inside.toLowerCase().startsWith("ambiguous san")) {
      return inside;
    }
  }

  if (text.length <= 48 && text.toLowerCase() !== "completed") {
    return text;
  }
  return null;
}