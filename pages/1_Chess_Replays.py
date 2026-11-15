import streamlit as st

from streamlit_dashboard import render_replay_page


st.set_page_config(page_title="Chess replays", page_icon="♟", layout="wide")
render_replay_page("chess")
