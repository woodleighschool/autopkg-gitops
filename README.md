# autopkg-gitops

## State

- Repository entries with `"gitops": true` may opt their raw Munki recipes into the run set with
  top-level `GitOps: true`.
- Every generated override in `RecipeOverrides` is run; overrides are reconciled from those markers.
- `RecipeOverrides/` contains generated recipe inputs and parent-trust state. These files say `DO NOT EDIT`; regenerate the whole file with `mise run trust:create` or `mise run trust:update`.
- `repositories.json` pins upstream repository commits.
- Parent trust paths determine which pinned repositories each selected recipe owns. A single-recipe run syncs only that closure.

An already-correct checkout is left alone without fetching. Renovate pull requests reconcile recipe
membership, refresh only affected trust, and maintain a sticky rendered-diff comment, including an
explicit no-change result.

## Local run

Install [Mise](https://mise.jdx.dev/), then:

```bash
cp .env.example .env
mise install
mise run lint
mise run local -- GoogleChrome
```
