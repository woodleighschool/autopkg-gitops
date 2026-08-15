# autopkg-gitops

## State

- `recipes.plist` enables recipe overrides.
- `RecipeOverrides/` contains generated parent-trust state. These files say `DO NOT EDIT`; regenerate them with `mise run trust:create` or `mise run trust:update`.
- `repositories.json` pins upstream repository commits.
- Parent trust paths determine which pinned repositories each selected recipe owns. A single-recipe run syncs only that closure.

An already-correct checkout is left alone without fetching. Updating one pin does not refresh unrelated repositories or AutoPkg download caches. Pull requests that change pins report the changed files that are actually referenced by enabled recipe chains.

## Local run

Install [Mise](https://mise.jdx.dev/), then:

```bash
cp .env.example .env
mise install
mise run lint
mise run local -- GoogleChrome
```
