// web/assets/api/supabase-client.js
// Simple functions to fetch 25-game pages and individual match replays from Supabase.

function getSupabaseHeaders(extraHeaders) {
  const headers = {
    apikey: APP_CONFIG.SUPABASE_PUBLISHABLE_KEY,
    Accept: "application/json"
  };
  if (extraHeaders) {
    for (const key in extraHeaders) {
      headers[key] = extraHeaders[key];
    }
  }
  return headers;
}

// 1. Fetch one page (25 cards) for the "All Games" tab, plus the total match count
async function fetchCatalogPage(pageNumber, gameFilter, modelFilter) {
  const offset = (pageNumber - 1) * APP_CONFIG.PAGE_SIZE;
  let query =
    "/rest/v1/trials_catalog?select=*&order=page_order.asc" +
    "&offset=" + offset +
    "&limit=" + APP_CONFIG.PAGE_SIZE;

  if (gameFilter && gameFilter !== "all") {
    query += "&game=eq." + encodeURIComponent(gameFilter);
  }

  if (modelFilter && modelFilter !== "all") {
    const cleanModel = encodeURIComponent(modelFilter);
    query += "&or=(white_model.eq." + cleanModel + ",black_model.eq." + cleanModel + ")";
  }

  const response = await fetch(APP_CONFIG.SUPABASE_URL + query, {
    // Prefer: count=exact tells Supabase to include the total row count in the header
    headers: getSupabaseHeaders({ Prefer: "count=exact" })
  });

  if (!response.ok) {
    throw new Error("Supabase catalog fetch failed: " + response.status);
  }

  const rows = await response.json();

  // Read total count from Content-Range header (format: "0-24/369")
  const rangeHeader = response.headers.get("content-range") || "";
  const slashIndex = rangeHeader.indexOf("/");
  const totalCount =
    slashIndex !== -1 ? Number(rangeHeader.slice(slashIndex + 1)) : rows.length;

  return {
    trials: rows,
    totalCount: totalCount
  };
}

// 2. Fetch the turn-by-turn JSON for ONE game when the user clicks a card
async function fetchSingleReplay(trialId) {
  const query =
    "/rest/v1/trial_replays?trial_id=eq." +
    encodeURIComponent(trialId) +
    "&select=game,replay_data";

  const response = await fetch(APP_CONFIG.SUPABASE_URL + query, {
    headers: getSupabaseHeaders()
  });

  if (!response.ok) {
    throw new Error("Supabase replay fetch failed: " + response.status);
  }

  const rows = await response.json();
  if (rows.length === 0) {
    return null;
  }
  return rows[0];
}

// 3. Build the public URL for a .webp board snapshot stored in Supabase Storage
function getSnapshotUrl(relativePath) {
  const cleanPath = relativePath.replace(/^\/+/, "");
  return (
    APP_CONFIG.SUPABASE_URL +
    "/storage/v1/object/public/snapshots/" +
    cleanPath
  );
}
// 4. Fetch all summary rows once for the "AI Models Comparison" page
async function fetchAllCatalogTrials() {
  const query =
    "/rest/v1/trials_catalog?select=trial_id,game,white_model,black_model,status,plies_survived,board_print_requests,failure_reason,exact_prompt&order=page_order.asc&limit=2000";

  const response = await fetch(APP_CONFIG.SUPABASE_URL + query, {
    headers: getSupabaseHeaders()
  });

  if (!response.ok) {
    throw new Error("Supabase comparison fetch failed: " + response.status);
  }

  return await response.json();
}