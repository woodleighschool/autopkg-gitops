# autopkg-gitops

[![CI](https://github.com/woodleighschool/autopkg-gitops/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/woodleighschool/autopkg-gitops/actions/workflows/ci.yaml)
[![License](https://img.shields.io/github/license/woodleighschool/autopkg-gitops)](https://github.com/woodleighschool/autopkg-gitops/blob/main/LICENSE)

- `RecipeOverrides/` is the run set. Edit `Input`;
  `ParentRecipeTrustInfo` is refreshed with `mise run trust:update`.
- `repositories.json` pins recipe repositories by URL, branch, and commit.
- `Recipes/` may contain local recipes.
- `secrets.sops.env` supplies encrypted `AUTOPKG_*` inputs.

Pinned repositories sync to `~/Library/AutoPkg/RecipeRepos` before the v3 recipe map is rebuilt.

`mise run trust:create <recipe>` creates an override. Keep only `Input` values you want to override.
`mise run trust:update <override>` and `mise run trust:update-all` refresh trust info;
`mise run trust:verify` inspects changes.

Renovate advances pinned revisions. Its pull request checks existing trust against the new
revisions, refreshes failed overrides, and posts the trust diff with repository compare links.

## Runs

[Mise](https://mise.jdx.dev/) provides the local and remote entry points:

```bash
mise install
mise run secrets:edit
mise run local -- GoogleChrome
# or
mise run remote -- GoogleChrome
```

The age identity remains outside Git in `age.key`; the self-hosted runner provides its path through
`SOPS_AGE_KEY_FILE`.
