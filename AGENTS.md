# AGENTS.md

Guidance for agents and humans working in this repository. This file is self-contained. Check the
scripts, Mise configuration, Lefthook configuration, workflows, recipe overrides, and repository
manifest for facts that can vary instead of copying versions or commands from another project.

## Working here

- Read the relevant scripts, configuration, tests, and nearby examples before editing. Existing code
  and reference implementations are evidence; understand the invariant and ownership boundary before
  choosing a solution.
- Target current supported behaviour. Prefer the simplest design that reduces state and machinery,
  and bring the affected path into conformance when existing code disagrees with this baseline.
- Preserve unrelated work. Keep changes focused, remove artifacts orphaned by the change, and keep
  generated outputs with their source change.
- Verify dependency APIs, flags, and defaults from the pinned source or primary documentation.
- Keep secrets, credentials, real identities, production data, and local environment files out of
  source, fixtures, logs, and commits.

## Baseline

- Write idiomatic, modern code for the versions pinned by this repository.
- Keep operations idempotent. Re-running a command, synchronizer, or recipe run with identical input
  shouldn't accumulate side effects.
- Stay DRY and minimal without premature abstraction. Three similar call sites are fine; add an
  abstraction when real callers need the variance it provides.
- Comments explain non-obvious constraints, invariants, and external requirements. Names and
  structure carry the ordinary narrative.
- Do not add file banners, author or date headers, or comment-based change logs. Git owns provenance
  and history.
- Write prose from the repository's point of view. Use `we` and `our` for the organisation, and
  `the workflow`, `the runner`, or direct wording for this repository. Omit organisation and product
  names when context already identifies them; keep names that are identifiers or distinguish an
  external system.
- Keep tracked documentation durable and present-tense. Omit migration history, temporary setup
  state, and inventories of absent features.
- Tests protect behaviour and contracts at the lowest useful boundary. Use realistic synthetic
  inputs and add regression coverage for plausible failures rather than implementation shape.

## Repository tooling

- Mise owns tools and commands. Run `mise tasks` and read `.mise/config.toml` before choosing task
  names or invoking bare tools.
- Lefthook extends the shared organisation configuration. Read `.lefthook.toml` and use
  `lefthook dump` when merged hook behaviour matters; local hooks contain only repository-specific
  additions.
- Run focused checks while working, then `mise run check` and any other relevant repository-owned
  static checks before calling the work complete.
- Only the main AutoPkg workflow executes recipes. Pull requests may run checks and refresh trust;
  never run `autopkg run` or a recipe processor while preparing or reviewing a change.

## Repository contract

- `RecipeOverrides` is the run set. The operator owns `Identifier`, `ParentRecipe`, and `Input`.
  AutoPkg owns `ParentRecipeTrustInfo`; refresh it with `mise run trust:update`, never by regenerating
  the override.
- `RecipeOverrides` is the only run-set declaration. Do not add another selector or dependency graph.
- `repositories.json` locks repository URLs, refs, and revisions. Names follow AutoPkg's `RecipeRepos`
  convention and are derived from the URLs.
- Sync pinned revisions to `~/Library/AutoPkg/RecipeRepos` before rebuilding the recipe map.
  `Recipes/` may contain local recipes.
- SOPS provides environment inputs. Keep tenant values encrypted in `secrets.sops.env` and
  credentials out of recipes and overrides.
- Renovate pin pull requests use `verify-trust-info -vv` for review and `update-trust-info` for trust
  changes.

## Git and completion

- Use focused Conventional Commits.
- Commit, push, publish, deploy, contact live systems, or perform destructive operations only when
  explicitly requested.
- Report the checks run, behaviour changed, generated outputs refreshed, and any verification that
  couldn't be completed.
