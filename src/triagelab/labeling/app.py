"""The labeling app (M5). Run with `triagelab label`, which sets the environment and calls:

    streamlit run src/triagelab/labeling/app.py --server.headless true

Pages: gold labels (blind, then adjudicated with evidence); judge ratings (rubric scores
for triage comments, blind to the system).
"""

import streamlit as st

from triagelab.labeling import gold_page, rating_page

st.set_page_config(page_title="triagelab labeling", layout="wide")
page = st.navigation(
    [
        st.Page(gold_page.render, title="Gold labels", url_path="gold", default=True),
        st.Page(rating_page.render, title="Rate comments", url_path="rate"),
    ]
)
page.run()
