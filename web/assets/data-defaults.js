const ARCHETYPE_LOOKUP = {
  "Chess": {
    "GPT-4o": "Phantom Piece Spawning & Diagonal Teleportation",
    "Claude 3.5 Sonnet": "Pinned Piece Blindness & Quiet State Drift",
    "Llama 3.1 (70B)": "Early Coordinate Desync & Friendly Fire"
  },
  "Connect Four": {
    "GPT-4o": "Missed Diagonal Win / Column Overflow",
    "Claude 3.5 Sonnet": "Rare Row-Height Off-By-One",
    "Llama 3.1 (70B)": "Floating Discs (Ignoring Gravity)"
  },
  "Battleship": {
    "GPT-4o": "Duplicate Coordinate Firing & 6-Tile Carrier",
    "Claude 3.5 Sonnet": "Conservative Quadrant Clustering"
  },
  "Tic-Tac-Toe": {
    "GPT-4o": "Near-Zero Collapse (Solved Horizon)",
    "Claude 3.5 Sonnet": "Deterministic Draw Lock"
  }
};

const DEFAULT_DATA = {
  modelsComparison: [
    {
      game: "Chess",
      description: "High branching factor (35+ legal moves/turn). Extreme sensitivity to coordinate occlusion and piece memory.",
      models: [
        {
          name: "GPT-4o",
          provider: "OpenAI",
          avgCollapseTurn: 21.4,
          archetype: "Phantom Piece Spawning & Diagonal Teleportation",
          validRate: 28,
          collapseRate: 72
        },
        {
          name: "Claude 3.5 Sonnet",
          provider: "Anthropic",
          avgCollapseTurn: 26.8,
          archetype: "Pinned Piece Blindness & Quiet State Drift",
          validRate: 45,
          collapseRate: 55
        },
        {
          name: "Llama 3.1 (70B)",
          provider: "Meta",
          avgCollapseTurn: 13.2,
          archetype: "Early Coordinate Desync & Friendly Fire",
          validRate: 12,
          collapseRate: 88
        }
      ]
    }
    // ...keep your Connect Four, Battleship, Tic-Tac-Toe starter objects here
  ],
  trials: [
    // ...paste your existing DEFAULT_DATA.trials array here
  ],
  sources: [
    // ...paste your existing DEFAULT_DATA.sources array here
  ]
};