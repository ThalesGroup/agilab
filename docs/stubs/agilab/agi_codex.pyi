import traceback
import streamlit as st

df = st.session_state.loaded_df

snippet_file = st.session_state.snippet_file

st.session_state.data = df
