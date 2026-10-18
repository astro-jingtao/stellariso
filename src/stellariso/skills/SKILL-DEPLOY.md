<!-- Deployment guide for the Claude Agent Skill shipped inside the
     stellariso package. Rewritten for the installed-package context from
     the skill-forge reference template; written to stand alone — the
     reader is assumed to have stellariso installed and no other skill
     tooling. -->

# Deploying the Skill Shipped in This Package

stellariso ships one Claude Agent Skill — a usage guide for coding
agents — inside the package itself. Installing the package installs the
skill's files as ordinary package data and deploys nothing anywhere:
making the skill visible to Claude Code is an explicit, separate step.
This guide is that step.

## Where the skill lives

Locate the skill from the package, never by guessing a site-packages
path:

```bash
python -c "import stellariso; print(stellariso.skill_directory())"
```

The printed directory is the skill proper — `SKILL.md` plus
`references/` and `CHANGELOG.md`. One level up sits `meta.yaml`
(external metadata — read it before linking; it is never deployed);
one level above that sits this guide (`SKILL-DEPLOY.md`).

## Deployment is a directory link

Make the skill visible to Claude Code by linking that directory into a
skills directory:

| target | link path | points at |
| ------ | --------- | --------- |
| user level (every project) | `~/.claude/skills/stellariso` | the printed directory |
| project level (one project) | `<project>/.claude/skills/stellariso` | the printed directory |

Prefer a link over a copy — the link reflects the installed stellariso
version as it changes (upgrades included); a copy drifts from the
moment either side changes.

Linux / macOS:

```bash
ln -s "<printed-directory>" ~/.claude/skills/stellariso
```

Windows (PowerShell):

```powershell
New-Item -ItemType SymbolicLink -Path "$HOME\.claude\skills\stellariso" -Target "<printed-directory>"
```

Windows requires Developer Mode or the "Create symbolic links" account
right to create a symlink; a failure mentioning privilege or WinError
1314 means neither is present — enable one, or fall back to a copy
(and re-copy after every stellariso upgrade):

```powershell
Copy-Item -Recurse "<printed-directory>" "$HOME\.claude\skills\stellariso"
```

Create a directory symlink, never a Windows junction: recursive
removers (`git worktree remove`, `git clean`) walk through a junction
into its target and can delete the package's content, while a symlink
is removed as the link itself.

## Before linking: read meta.yaml

`meta.yaml`, beside the skill directory, declares what the skill
expects from its environment:

- `requires` — here one entry, the `stellariso` package itself. Verify
  it in the environment the link will be used from
  (`python -c "import stellariso"` must succeed in that environment).
- `notes` — informational; they record the upgrade and
  virtual-environment semantics summarized below.

An unsatisfied requirement is a report to the user — the user fixes
the gap or consciously continues; never a silent skip.

## Environment and upgrade semantics

- The link target lives inside one Python environment's site-packages.
  Using the skill from a different environment (another conda env,
  another virtualenv) needs either stellariso installed there too or
  the link re-pointed — verify with `python -c "import stellariso"`
  in the environment Claude Code's Python runs from.
- Removing or rebuilding that environment dangles the link; re-run the
  locate command and re-create the link.
- `pip install --upgrade stellariso` keeps the path stable, so a link
  continues to serve the new version; a copied deployment must be
  re-copied after every upgrade.

## Safety rules

- Show the plan first — which link, pointing where — before creating
  anything.
- A real directory or file already sitting at the link destination is
  a conflict: report it, never delete it. The most you may do, with
  the user's knowledge, is rename it aside
  (`stellariso.bak.<timestamp>`).
- The procedure is idempotent — re-running it leaves an existing
  correct link alone.

## After linking

- Verify: `~/.claude/skills/stellariso/SKILL.md` is reachable through
  the link, and the frontmatter `name:` equals `stellariso`.
- To remove a deployment, remove the link itself — on Windows, confirm
  first that it is a symlink rather than a junction:
  `Get-Item <path> | Select-Object LinkType` should show
  `SymbolicLink`.
