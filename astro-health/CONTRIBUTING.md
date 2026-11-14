# Working in four branches without merge pain

1. One person per lane (see `.github/CODEOWNERS`). Edit only your own folders.
2. Folders may READ each other's files (schemas, fixtures, rule files). They never import each other's code, with two exceptions: `backend/` reads `data/schemas/`, and `evidence/` imports `backend/`.
3. `data/schemas/` is the contract. Freeze v0.1 together in hour one. After that: additive changes only (new optional fields), in a tiny PR that merges within the hour. Everyone rebases afterwards.
4. No shared registry files. Pipelines are discovered by folder, scenarios and red-team cases are one file each, Streamlit pages are one file each.
5. Branch names: `a/<topic>`, `b/<topic>`, `c/<topic>`, `d/<topic>`. Merge to `main` at least twice a day. Rebase before opening a PR.
6. Never commit generated output except `evidence/results/` (final tables) and `data/nasa/*/processed/` (small processed files).
7. Root files (README, Makefile, pytest.ini, CODEOWNERS) are frozen after the first commit. Only their owner edits them.
8. Frontend talks to backend over HTTP only (`BACKEND_URL`), or runs offline with `MOCK_MODE=1` reading `data/fixtures/`.
9. Windows: the Makefile is a convenience; every target is one line you can run by hand.
