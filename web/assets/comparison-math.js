// web/assets/comparison-math.js
// Plain loops that calculate survival rate and average collapse turn per model.

function createEmptyModelStat(modelName) {
  return {
    name: modelName,
    provider: inferProvider(modelName),
    totalGames: 0,
    validGames: 0,
    collapseGames: 0,
    collapseTurnSum: 0,
    collapseTurnCount: 0,
    archetypeCounts: {}
  };
}

function getMostFrequentArchetype(countsObj, gameSlug, collapseGames) {
  if (collapseGames === 0) {
    return "Zero Mistakes Recorded";
  }

  let bestLabel = ARCHETYPE_FALLBACKS[gameSlug] || "State Tracking Drift";
  let bestCount = 0;

  for (const label in countsObj) {
    if (countsObj[label] > bestCount) {
      bestCount = countsObj[label];
      bestLabel = label;
    }
  }
  return bestLabel;
}

function buildComparisonFromTrials(rawTrials) {
  const statsByGame = {};

  for (let i = 0; i < rawTrials.length; i++) {
    const trial = normalizeTrialRecord(rawTrials[i]);
    if (!trial.game || trial.isApiError) continue;

    if (!statsByGame[trial.game]) {
      statsByGame[trial.game] = {};
    }
    const gameModels = statsByGame[trial.game];

    // Collect 1 or 2 unique models in this match (skip "Random" baselines)
    const participants = [];
    if (trial.modelA && !trial.modelA.toLowerCase().includes("random")) {
      participants.push(trial.modelA);
    }
    if (
      trial.modelB &&
      trial.modelB !== trial.modelA &&
      !trial.modelB.toLowerCase().includes("random")
    ) {
      participants.push(trial.modelB);
    }

    const culprit = trial.isIllegal ? identifyCulpritModel(trial) : null;
    const archetype = trial.isIllegal ? extractArchetypeFromReason(trial.reason) : null;

    for (let j = 0; j < participants.length; j++) {
      const modelName = participants[j];
      if (!gameModels[modelName]) {
        gameModels[modelName] = createEmptyModelStat(modelName);
      }

      const stat = gameModels[modelName];
      stat.totalGames += 1;

      if (trial.isIllegal && culprit === modelName) {
        stat.collapseGames += 1;
        if (trial.turns > 0) {
          stat.collapseTurnSum += trial.turns;
          stat.collapseTurnCount += 1;
        }
        if (archetype) {
          stat.archetypeCounts[archetype] = (stat.archetypeCounts[archetype] || 0) + 1;
        }
      } else {
        stat.validGames += 1;
      }
    }
  }

  // Turn the grouped objects into the sorted array for the UI
  const gameSlugs = Object.keys(statsByGame).sort();
  const result = [];

  for (let i = 0; i < gameSlugs.length; i++) {
    const slug = gameSlugs[i];
    const gameModels = statsByGame[slug];
    const modelNames = Object.keys(gameModels);
    const modelsList = [];

    for (let j = 0; j < modelNames.length; j++) {
      const stat = gameModels[modelNames[j]];
      const validRate =
        stat.totalGames > 0 ? Math.round((stat.validGames / stat.totalGames) * 100) : 0;
      const collapseRate = 100 - validRate;

      let avgCollapseTurn = null;
      if (stat.collapseTurnCount > 0) {
        avgCollapseTurn = (stat.collapseTurnSum / stat.collapseTurnCount).toFixed(1);
      }

      modelsList.push({
        name: stat.name,
        provider: stat.provider,
        totalGames: stat.totalGames,
        avgCollapseTurn: avgCollapseTurn,
        archetype: getMostFrequentArchetype(stat.archetypeCounts, slug, stat.collapseGames),
        validRate: validRate,
        collapseRate: collapseRate
      });
    }

    modelsList.sort(function (a, b) {
      if (b.validRate !== a.validRate) return b.validRate - a.validRate;
      return b.totalGames - a.totalGames;
    });

    result.push({
      gameSlug: slug,
      game: formatGameTitle(slug),
      description:
        GAME_DESCRIPTIONS[slug] || "Deterministic multi-turn state tracking evaluation.",
      models: modelsList
    });
  }

  return result;
}