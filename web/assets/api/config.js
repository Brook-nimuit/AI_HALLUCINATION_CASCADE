// web/assets/api/config.js
// Central configuration for cloud connection and environment detection.

const APP_CONFIG = {
  // Paste your Project URL and Publishable Key from Supabase -> Project Settings -> API Keys
  SUPABASE_URL: "https://fzbjasivwabnsxxzisbd.supabase.co",
  SUPABASE_PUBLISHABLE_KEY: "sb_publishable_WkRjzfhjlKjeoA-bBxGh7Q_P34ITa2O",

  // Number of match cards to load per page on "All Games"
  PAGE_SIZE: 25,

  // True when running local_website.py, False when live on Vercel
  isLocalhost:
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1"
};

// Allow local toggling between "dev" and "audience" mode; lock to "audience" on Vercel
function getAppMode() {
  if (!APP_CONFIG.isLocalhost) {
    return "audience";
  }
  return localStorage.getItem("weird_index_mode") || "dev";
}