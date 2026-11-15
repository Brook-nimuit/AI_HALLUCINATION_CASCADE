"""Local Streamlit dashboard for gameplay-backed experiment results."""

import streamlit as st

from streamlit_dashboard import DATA_DIR, load_trials


st.set_page_config(
    page_title="Hallucination Cascade · All Games",
    page_icon="♟",
    layout="wide",
)

trials = load_trials()
st.title("The Hallucination Cascade")
st.caption("Research trials and replay records saved under data/local/")

if not trials:
    st.warning(
        "No gameplay-backed trials were found. Run an experiment and save its "
        "results under data/local/results/."
    )
    st.stop()

games = sorted({row["game"] for row in trials})
st.header("All games")

total, invalid, partial, games_count = st.columns(4)
total.metric("Trials with gameplay", len(trials))
invalid.metric(
    "With invalid/illegal moves",
    sum(row["trial_status"] == "invalid_or_illegal" for row in trials),
)
partial.metric(
    "Partial after API/provider error",
    sum(row["trial_status"] == "partial_api_error" for row in trials),
)
games_count.metric("Games represented", len(games))

st.caption(
    "A trial counts once a model attempts a move/action. Illegal moves remain "
    "research data. Attempts that fail before gameplay are omitted."
)

selected_game = st.selectbox("Filter by game", ["All games", *games])
selected_model = st.selectbox(
    "Filter by model",
    ["All models", *sorted({row["model"] for row in trials})],
)
visible = [
    row
    for row in trials
    if (selected_game == "All games" or row["game"] == selected_game)
    and (selected_model == "All models" or row["model"] == selected_model)
]

st.subheader("Open a replay")
for game, page in (("chess", "pages/1_Chess_Replays.py"), ("checkers", "pages/2_Checkers_Replays.py")):
    game_trials = [row for row in visible if row["game"] == game]
    if not game_trials:
        continue
    label = f"Open {game.title()} replays · {len(game_trials)} trials"
    if st.button(label, key=f"open-{game}"):
        st.session_state["selected_game"] = game
        st.switch_page(page)

if selected_game in {"chess", "checkers"}:
    game_rows = [row for row in visible if row["game"] == selected_game]
    if game_rows:
        st.caption(
            "Choose a trial below, then open its replay. The replay page can also "
            "be opened from the Streamlit page list."
        )
        labels = {
            f"{row['run_id']} · Trial {row['trial_id']} · {row['model']} vs "
            f"{row['opponent_model']}": row
            for row in game_rows
        }
        selected_label = st.selectbox(
            "Replay trial",
            list(labels),
            key=f"{selected_game}-trial-choice",
        )
        selected = labels[selected_label]
        st.session_state["selected_trial_key"] = selected["trial_key"]
        if st.button(f"Replay selected {selected_game.title()} trial"):
            st.session_state["selected_game"] = selected_game
            page = (
                "pages/1_Chess_Replays.py"
                if selected_game == "chess"
                else "pages/2_Checkers_Replays.py"
            )
            st.switch_page(page)

st.subheader(f"Trials ({len(visible)})")
st.dataframe(
    [
        {
            "Game": row["game"].replace("-", " ").title(),
            "Run": row["run_id"],
            "Trial": row["trial_id"],
            "Model": row["model"],
            "Opponent": row["opponent_model"],
            "Result": row["display_result"],
            "Status": row["trial_status"],
            "Turns / plies": row["turns"],
            "Reason / notes": row["reason"],
            "Wrong response": row.get("wrong_response") or "",
        }
        for row in visible
    ],
    hide_index=True,
    use_container_width=True,
)

st.subheader("Game totals")
counts = {game: sum(row["game"] == game for row in trials) for game in games}
for game in games:
    columns = st.columns([1, 5, 2])
    columns[0].metric(game.title(), counts[game])
    columns[1].write(
        f"{sum(row['trial_status'] == 'invalid_or_illegal' for row in trials if row['game'] == game)} "
        "invalid/illegal · "
        f"{sum(row['trial_status'] == 'partial_api_error' for row in trials if row['game'] == game)} "
        "partial API-stop"
    )
    if game in {"chess", "checkers"} and columns[2].button(
        f"View {game}", key=f"game-link-{game}"
    ):
        st.session_state["selected_game"] = game
        st.switch_page(
            "pages/1_Chess_Replays.py"
            if game == "chess"
            else "pages/2_Checkers_Replays.py"
        )
    elif game not in {"chess", "checkers"}:
        columns[2].write("Results shown above")

image_only = sum(
    1
    for folder in (DATA_DIR / "replays").glob("trial_*")
    if folder.is_dir() and not (folder / "match_audit.json").exists()
)
if image_only:
    st.info(
        f"{image_only} legacy Chess replay folders contain images without match "
        "audits; they are not included in trial totals because their model and "
        "outcomes cannot be verified."
    )
