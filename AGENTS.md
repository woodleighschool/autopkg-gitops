# AutoPkg deployment declarations

This repository declares exactly which reviewed AutoPkg source may run:

- `repositories.json` pins every recipe repository to an exact revision.
- Every override in `RecipeOverrides` is run. Repository membership is the declaration; there is no
  separate enabled or disabled list.
- Only recipes suitable for unattended recurring checks belong here. Recipes with fixed versions or
  payloads copied from `Assets`, `/Applications`, or another local folder stay in the source
  repository for on-demand use and must not have an override here. Local icons do not make an
  otherwise dynamic recipe on-demand.
- `RecipeOverrides` is generated recipe-chain lock data. Inputs, parent, and trust are one immutable
  output; always regenerate the whole file and never edit or partially refresh it.

Application additions start with a source pull request in `woodleighschool/autopkg`. A paired GitOps
pull request is needed only when the recipe requires a new upstream repository pin. It must leave the
Woodleigh AutoPkg source revision unchanged because that revision is Renovate-owned.

After the source pull request merges, Renovate updates the Woodleigh pin and refreshes the generated
trust data. The source PR and its review must make clear whether a new recurring override belongs in
GitOps; static and local-payload recipes are intentionally absent.

Do not deploy or execute source absent from the pinned revision, bypass the consistency check, edit a
generated override, or invent another promotion mechanism. Actual recipe execution belongs only to
the trusted-main AutoPkg workflow after review. Pull-request work is limited to repository-owned
static checks and lock generation; never run `autopkg run` or a recipe processor.

For local agent work, make the source change in `woodleighschool/autopkg`, make the paired declaration
change here, run the safe static checks, and open linked pull requests with the same ancestry
and verification evidence requested by the source repository's `AGENTS.md`.
