# archive/root_shared

Files moved here from the repository root during the fleet refactor (August 2026).

## Contents

- `data_models.py` — shared Pydantic/dataclass stubs written early in the project.
  Never imported by the robot server. Superseded by `SimpleNamespace` config in
  `robots/shared/config/loader.py`.

- `firebase_utils.py` — shared Firebase helper stubs. Never called at runtime.
  Firebase upload is out of scope for the current robot server; the uploader
  subpackage (`robots/shared/uploader/`) is a placeholder for future use.

- `types/` — empty directory that was a planned location for shared type stubs.
  No files were ever written here; the directory disappeared naturally after the
  git moves.

All three items were at the repository root (`robots/shared/` at the time it was
a flat stub, not the Python package it became). They are preserved here for
history rather than deleted.
