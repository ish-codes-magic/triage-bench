"""The labeling app (M5). Run with `triagelab label`, which sets the environment and calls:

    streamlit run src/triagelab/labeling/app.py --server.headless true

Pages: gold labels (blind, then adjudicated with evidence).
"""

import streamlit as st

from triagelab.labeling import gold_page

st.set_page_config(page_title="triagelab labeling", layout="wide")
page = st.navigation(
    [st.Page(gold_page.render, title="Gold labels", url_path="gold", default=True)]
)
page.run()
