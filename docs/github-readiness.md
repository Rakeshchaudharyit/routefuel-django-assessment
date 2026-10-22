# GitHub publication — manual steps after review

Suggested repository name: **routefuel-django-assessment**.

The local code and submission materials are prepared. No GitHub repository has been created,
no files uploaded, and no push performed by this preparation task. The current branch is
`main`. Its `origin` is a local filesystem remote from earlier development, not a GitHub URL.
The commands below are instructions to execute only after reviewing the repository.

## Review the local repository

From the repository root:

```bash
git status --short
git log --oneline -10
git ls-files
```

M7 is preserved in `d44d473`, following M6 `49b4c19` and M5 `13fac92`. M8 submission preparation
is a separate local commit. Review the README, environment examples, collection, dataset sources,
[QA report](m7-final-qa-report.md), [Loom script](loom-demo-script.md) and
[submission checklist](submission-checklist.md).

Real `.env` files, SQLite databases and sidecars, virtual environments, `node_modules`, `.next`
and TypeScript build info are ignored. Only public example environment values belong in Git.
Required CSV/reference files are intentionally tracked. Reference checksums are recorded in
`backend/data/reference/SOURCE.md`; no screenshots or video files are required in the repository.
Targeted current-file and reachable-history credential scans found no token/private-key matches;
that review is not a guarantee of an exhaustive secret scanner or dependency advisory audit.

## Fuel-price CSV redistribution — decide before publishing

`backend/data/fuel-prices-for-be-assessment.csv` was supplied by the employer. Its terms for
public redistribution are not documented. It has been tracked since commit `b830597` (M1), so it
is in the Git history, not just the current tree. The Census and Natural Earth reference files
are public domain (see `backend/data/reference/SOURCE.md`).

* **Publishing as-is** publishes the CSV and its history. Do this only if you are comfortable
  that redistribution is allowed, for example because the employer expects it in submissions.
* **Not publishing the CSV:** removing the file in a new commit still leaves it in earlier
  commits. Fully excluding it means rewriting history or publishing a fresh repository
  created from a reviewed export. Both need your explicit decision; neither was done here.
  Alternatively, make the repository private and share access with the reviewer.
* The README explains how to supply the CSV locally (`backend/data/` or `--file`). The test
  suite does not depend on the full CSV.

## Create an empty public repository

1. Sign in to your intended GitHub account and choose **New repository**.
2. Name it `routefuel-django-assessment`; select **Public**.
3. Description: `Django route and fuel-cost optimization API with a Next.js dashboard.`
4. Leave initialization with README, .gitignore and license unchecked: this local repository
   already has its history and files. Do not create a competing initial commit.
5. Create the repository and copy its HTTPS Git URL.

## Connect and push manually

Replace `YOUR_GITHUB_USERNAME` with the actual owner. Run these commands from the local root
only after approving publication:

```bash
git remote -v
git remote set-url origin https://github.com/YOUR_GITHUB_USERNAME/routefuel-django-assessment.git
git remote -v
git push -u origin main
```

This replaces the existing local remote URL; it does not rewrite commits. If there is no
`origin` in a different checkout, use `git remote add origin <the-copied-HTTPS-URL>` instead.
Authenticate through your normal GitHub Git credential flow; do not put a token in a URL,
source file or environment example. No force push is needed. If GitHub is not empty and the
push is rejected, stop and inspect rather than overwriting remote history.

## Check the reviewer experience

Open the public repository while signed out or in a private browser window. Confirm README,
source, CSV/reference data and Postman files are accessible. Clone into a new directory and
follow the README setup with a new virtual environment/database and `npm ci`. The M8 audit
already checked migrations and repeated imports in a disposable database; a fresh external
clone and installation remain a post-publication manual check.

Record the actual repository URL in the checklist. Record Loom manually using the 4:50 script,
check playback and sharing while signed out, and add the real Loom URL. Submit only after
both links have been verified. Do not claim publication, recording or submission is complete
while those checklist entries remain unchecked.
