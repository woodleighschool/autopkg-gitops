# AutoPkg deployment declarations

This repository turns explicitly declared AutoPkg recipes into pinned, reviewable runs:

- `repositories.json` pins every recipe repository to an exact revision.
- A repository entry with `"gitops": true` is trusted to declare runnable recipes. Within that
  repository, a raw Munki recipe with top-level `GitOps: true` belongs in the generated run set.
- Never honor `GitOps` metadata from a repository without the manifest opt-in.
- `RecipeOverrides` is generated recipe-chain lock data. Inputs, parent, and trust are one immutable
  output projected from those declarations; always regenerate the whole file and never edit or
  partially refresh it.
- Every generated override is run. There is no separate enabled or disabled list.

Renovate updates all repository pins. A source-pin pull request reconciles added, changed, and removed
recipe declarations, refreshes generated trust, and receives a sticky rendered-diff comment even
when no review-required recipe input changed. A pin requires review when it changes recipe
membership or content, a processor used by a selected recipe, or a resource imported by a selected
recipe. Imported resources include relative `PkgCreator` script directories and `%RECIPE_DIR%`
file, directory, or glob references. Recipe changes are rendered as diffs; processor and
imported-resource changes link to their upstream diffs. Repository pins and generated overrides
remain review-owned and are never automatically merged by this repository.

Do not deploy or execute source absent from the pinned revision, bypass the consistency check, edit a
generated override, or invent another promotion mechanism. Actual recipe execution belongs only to
the trusted-main AutoPkg workflow after review. Pull-request work is limited to repository-owned
static checks and lock generation; never run `autopkg run` or a recipe processor.

For local agent work, change only this repository's generic pinning, reconciliation, rendering, or
runner mechanics. Source repositories own their own recipe declarations.
