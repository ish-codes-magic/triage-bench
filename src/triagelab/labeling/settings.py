"""Where the labeling app reads and writes, from environment variables.

Environment rather than CLI arguments because Streamlit's test harness (AppTest) never
sets `sys.argv`; `triagelab label` sets these before launching Streamlit.
"""

import os
from pathlib import Path

from pydantic import BaseModel

from triagelab.data.profile import RepoProfile, load_profile


class AppSettings(BaseModel):
    profile_path: Path
    data_dir: Path
    annotator: str

    @classmethod
    def from_env(cls) -> "AppSettings":
        return cls(
            profile_path=Path(
                os.environ.get("TRIAGELAB_PROFILE", "configs/repos/python__cpython.yaml")
            ),
            data_dir=Path(os.environ.get("TRIAGELAB_DATA_DIR", "data")),
            annotator=os.environ.get("TRIAGELAB_ANNOTATOR", "owner"),
        )

    def profile(self) -> RepoProfile:
        return load_profile(self.profile_path)
