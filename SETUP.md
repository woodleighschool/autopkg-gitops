# Setup

The runner boundary is the organization runner group, not branch protection.

1. Create the organization runner group `autopkg`.
2. Allow only `woodleighschool/autopkg-gitops` to use it.
3. Allow only `woodleighschool/autopkg-gitops/.github/workflows/autopkg.yml@refs/heads/main` to target it.
4. Put the macOS runner in that group and remove it from unrestricted groups.

The current runner contract is AutoPkg v3 plus Munki's `/usr/local/munki/makepkginfo`. A later reusable setup action can install or upsert those tools so the same workflow can target a local Mac or a cloud macOS runner without changing its run steps.

Provision the generated age identity on the runner and set `SOPS_AGE_KEY_FILE` in the runner service environment. Runtime inputs live in the tracked `secrets.sops.env`; GitHub variables and secrets are not part of the AutoPkg runtime contract. The production workflow has read-only repository permissions and only runs from `main`; branch protection is still useful for controlling changes, but it is additional to the runner group's exact workflow restriction.

Use GitHub-hosted runners for pull-request validation. Do not expose the self-hosted runner or repository secrets to pull-request workflows.
