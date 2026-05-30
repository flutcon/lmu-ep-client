# lmu-ep-client

## Shared Memory Data

When working with LMU shared memory fields, always check [vendor/pyLMUSharedMemory/lmu_data.py](vendor/pyLMUSharedMemory/lmu_data.py) to verify the correct field names, types, and documented values/enums before reading or interpreting any data from shared memory.

## Versioning & auto-update

`src/lmu_ep_client/__init__.py` `__version__` is the single source of truth (pyproject reads it dynamically; tufup reads it when publishing). Bump it for every release.

The packaged exe self-updates on startup via tufup (TUF-signed). Client logic is in [src/lmu_ep_client/updater.py](src/lmu_ep_client/updater.py) (`maybe_update` + the pure `_decide` policy); maintainer tooling is in [packaging/](packaging/). Update policy must always **fail open** — never block launch on an update error. The apply step exits the process and must run on the main thread (see the module docstring). See the README "Releasing updates" section for the publish workflow.
