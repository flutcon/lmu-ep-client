from __future__ import annotations

import os
import tempfile

from lmu_ep_client.logging_setup import LOG_DIR_ENV


def pytest_configure(config) -> None:
    if not os.environ.get(LOG_DIR_ENV):
        os.environ[LOG_DIR_ENV] = tempfile.mkdtemp(prefix="lmu-ep-client-test-logs-")
