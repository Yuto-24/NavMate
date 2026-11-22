# NavMate agent guide

## Coordination and review

- GPT-6 Astra and GPT-6.1 Sol are both used in this project. The model selected for the task performs investigation, implementation, and testing directly. Preserve the user's model and reasoning-effort selection; do not delegate other work unless the user explicitly requests it.
- Review repository changes in a separate, read-only context with the other model: GPT-6.1 Sol reviews Astra's changes, and GPT-6 Astra reviews Sol's changes. Explicitly select the reviewer model; a separate agent or `/review` alone does not establish model independence. If the other model is unavailable, report the review as blocked. Self-review alone is not sufficient. See `docs/agent_workflow.md` for the review handoff and configuration boundaries.
- Before substantive work, inspect the repository documentation, Issues/PRs, prior decisions, and analogous code relevant to the task. Keep the inspection proportional to the change. Reuse prior knowledge only after checking it against the current code, specification, and dependencies.
- Keep reusable, non-obvious findings in the appropriate external documentation. Do not turn AGENTS.md into a work log or duplicate detailed evidence.
- For human-facing documentation, normally have Gemini draft the prose through an available CLI (including agy), then have GPT-6.1 Sol or GPT-6.1 Terra check it against the code for omissions and consistency. Use a separate read-only reviewer when needed; this check does not replace the independent review required above. Preserve user intent and verify the final text after edits. If Gemini or an appropriate reviewer is unavailable, report the limitation rather than claiming the workflow was completed. See [the documentation workflow](docs/agent_workflow.md#人間向け文書の作成と確認).
- When adding, changing, moving, or reusing user-facing UI copy, follow [the UI copy workflow](docs/ui_copy_review.md). Ask Gemini through an available CLI (including agy) for user-centered wording suggestions and concerns, then use your own judgment to select or refine the final copy against actual behavior and user intent. Retain the response, decision reasons, and final source match. User-provided intent takes precedence. If Gemini or evidence is unavailable, report the limitation in the PR and completion message.

## Scope and simplicity

- Make the smallest coherent change that satisfies the task's Goal, Acceptance Criteria, and required correctness, security, and compatibility constraints. Prefer fixing a verified root cause over a superficial workaround; allow only the structural changes necessary to do so.
- Treat task requirements and Non-goals as the scope boundary. Include supporting changes only when necessary for the requested behavior or its safety, compatibility, or regression prevention. Do not fix unrelated discovered problems without authorization, even when serious; report them and hold merge if the risk or required gates warrant it.
- Prefer existing implementations, standard APIs, libraries, and established repository patterns. Do not add abstractions, dependencies, configuration, compatibility layers, or future extensibility without a concrete need in the current task.
- Do not bundle incidental refactoring, cleanup, optimization, or unrelated tests and documentation. Report worthwhile out-of-scope findings separately; propose follow-up work only when justified.
- Choose focused verification during implementation. Before opening or updating a PR, complete the applicable local CI checks and confirm no failures remain. When the Python suite is selected for local validation, run the complete pytest suite and shared checks in the supported Docker test environment, not only targeted tests. The default `scripts/run_ci_checks.sh` runs both; CI assigns shared checks to shard 1 and requires both shards. Follow [the pre-PR local validation procedure](docs/agent_workflow.md#pr提出前のローカル検証). Preserve mandatory CI, independent review, and safety checks; do not rerun passed checks without a specific reason.
- Retrieve evidence incrementally, batch related fixes before expensive validation, and avoid repeatedly inspecting unchanged CI/review state. Follow [the investigation, validation, and waiting procedure](docs/agent_workflow.md#調査検証待機の進め方); efficiency does not waive required gates.
- Do not wait for or continuously monitor CI or external reviews unless the user explicitly requests monitoring. After push/PR updates, report pending checks and end the turn; fixes and new commits do not authorize restarting monitoring. A request to check results permits one snapshot only. This stop rule takes precedence over the default completion workflow; see the linked procedure for details.
- Before completion, audit the diff for scope expansion and unnecessary complexity. Remove or separate changes not justified by the task.

## Product constraints

- Avoid unnecessary secondary labels and descriptions. Let the layout do the explaining.

- Route creation/re-edit and flight planning use one map and one operation pane. Above 700 px, keep the map on the left and the aligned operation pane on the right; only the operation contents scroll. At 700 px and below, place the map before the operation pane without pinning it over inputs. Keep readiness and calculation at the operation footer, with NAV LOG and its guidance below the workspace. Preserve calculation, persistence, and the NAV LOG table itself.
- Any layout change needs browser coverage around 1,100 px and above 1,240 px, asserting workflow-region order/position rather than visibility alone. See `docs/web-design/README.md` for the UI reference.
- For release-management, version metadata, documentation, or CI changes without user-facing behavior or layout changes, skip browser automation, screenshots, and visual checks unless the user explicitly requests them. Use only applicable focused source, build, or health checks.
- Docker Compose is the supported local/Legacy runtime; the production delivery path is Static Web as described in `README.md` and `docs/static_production.md`. Local Compose health does not establish Static Web production acceptance. Preserve the `autonavlog-data` volume: routine updates and stops must not use `docker compose down -v`. Follow `README.md` and `docs/cloudflare_tunnel.md` for environment-specific startup and exposure rules.
- Ordinary feature/fix PRs use `Release: not-required` with a `Reason:` and keep root `VERSION` and `CHANGELOG.md` unchanged. Record pending release notes in the PR body under `## Pending release notes`, or explicitly state `None` when there are none. Only an explicit release-preparation PR uses `Release: required`, increments `VERSION`, and adds the finalized `CHANGELOG.md` section; do not rewrite published release notes. This applies to both `main` and `release/1.x`. `VERSION` is the sole NavMate version source; do not place it in web package manifests or README. Run `python scripts/validate_release.py`, `pytest tests/unit/test_version.py`, and `npm --prefix web run typecheck`. Do not change the separately managed `src/autonavlog/version.py` or `jma-msm-wind` version.

## Codex worktrees

- In Codex worktrees, run `scripts/codex/setup_worktree.sh` before Docker Compose work. The generated environment isolates the Compose project, image, host port, and named volume; do not target or reuse the primary `autonavlog` runtime from a worktree.
- Do not assume port 8123 in a Codex worktree. Read `AUTONAVLOG_HOST_PORT` from the generated `.env` or use the URL printed by the setup script.
- The only exception to the volume-preservation rule is `scripts/codex/cleanup_worktree.sh`, and only for generated projects whose `COMPOSE_PROJECT_NAME` matches `autonavlog-wt-*`. Never run `docker compose down -v` manually against the primary NavMate runtime.
- At task completion, account for task-owned worktrees and Docker resources using [the completion cleanup procedure](docs/development_worktrees.md#作業終了時の整理). Dispose only of completed environments after checking task/process ownership and uncommitted changes; retain active, unfinished, or uncertain environments and record the reason. Do not assume the Codex disposal hook ran successfully or use global Docker prune.

## Change and delivery safety

- Preserve unrelated user changes; stage and modify only the requested paths. Do not use destructive commands such as `git reset --hard`, `git checkout --`, broad recursive deletion, or volume deletion unless the user explicitly authorizes the exact target.
- Before creating a temporary development backup, record its purpose, exact scope, and disposal condition in the private operation record. At completion, remove only task-owned temporary backups whose restoration need has ended; document why and until when others remain. Protect production backups, live data, and unfinished work. See [development backup retention](docs/development_worktrees.md#開発用バックアップの保持条件); age or size alone is not a deletion decision.
- Unless the user explicitly limits scope, completing requested repository edits includes applicable required checks and independent review; committing scoped changes, pushing the branch, and creating or updating the task PR. Update and health-check local Docker Compose only when the change affects that runtime or its integration and the validation is necessary; preserve its data volume. Do not seek separate confirmation for these default completion actions; report whether runtime validation was performed or not applicable, the commit, PR URL, hosted CI, and any blocked stage accurately. Merges, remote production deploys, and external publishing outside a PR still require explicit authorization.
- If GitHub Actions cannot run or complete because of GitHub-hosted billing, spending, or usage limits, treat the current workflow definitions as the source of truth and reproduce the applicable CI checks locally as closely as practical. Post to the PR which hosted checks were blocked, the GitHub-side blocking reason, the local commands or checks run, and their results. Do not report hosted CI as passed; state that it was blocked and locally reproduced. If any hosted-only check cannot be reproduced locally, identify it explicitly and leave that gate unresolved.
- Before an explicitly authorized merge, independently confirm CI, reviews (including CodeRabbit), unresolved threads, `reviewDecision`, `mergeable`, and `mergeStateStatus`; all must be in an acceptable final state. Report any unresolved or stale gate rather than merging.

## Review findings and scope

- Apply the same scope boundary to CodeRabbit, independent reviews, and other external findings. Treat findings as evidence to assess, not authorization to expand the PR; a severity label alone does not establish that a change belongs in scope.
- Fix technically valid findings required for the requested behavior, correctness, security, compatibility, or regression prevention, including necessary root-cause fixes. Do not implement optional refactoring, architectural improvements, optimizations, speculative safeguards, or unrelated pre-existing fixes solely because a reviewer suggests them.
- Explain deferred or rejected findings with reasons and evidence in the original review thread. Report serious out-of-scope problems without modifying unrelated code, and pause merge if an unresolved risk or required review/check prevents it. Do not dismiss or resolve blocking findings merely to bypass a merge gate.
- Independent review must also identify unnecessary changes and scope expansion, not just missing fixes. Apply the same necessity test to the independent reviewer's suggestions.

## CodeRabbit reviews

- An explicit release-preparation PR limited to VERSION, CHANGELOG and associated UI-copy evidence does not require a CodeRabbit review. Other PRs require an initial automatic CodeRabbit review; if it does not start or cannot complete, report the unresolved review rather than treating it as complete.
- Never request a CodeRabbit review manually, including retries or re-reviews. Do not post review commands, request reviewers, or use another manual trigger. Do not change paid plans to obtain reviews.
- Assess any automatically submitted findings against the current diff and scope. Record necessary fixes and verification in the PR or original threads. An older review does not cover newer changes without checking the intervening diff.
- Assess substantive review completion separately from GitHub merge eligibility. Check the current `reviewDecision`, unresolved threads, required checks, and actual protection rules; report any concrete unresolved gate. Do not dismiss reviews, weaken protection, or mark unreviewed work as approved to bypass a gate.
- Preserve independent review and all actual repository gates. Required latest-commit approval, required checks, unresolved conversations, and effective change requests still apply to release-preparation PRs. Merge and deployment require their existing authorization.

When a repository's documentation and its existing code disagree, follow the conventions used in the existing code, and in your final reply point out each inconsistency you found between the documentation and the code

## Reusable knowledge

Before work, consult [the shared knowledge index](docs/knowledge/INDEX.md) and only the entries relevant to the task; follow [the knowledge workflow](docs/knowledge/README.md) to verify applicability and preserve non-obvious findings with evidence through incremental updates. Keep detailed lessons out of this file, reuse existing canonical documents, and do not create an entry when nothing reusable was learned.

## Reader-facing writing

Before creating or updating PR bodies, Issue bodies, comments, ROADMAPs, work reports, or final replies for this project, read and follow [the writing standard](docs/writing-style.md). This applies to GitHub and chat messages as well as repository files. Run its submission checklist before sending or publishing. Keep the standard canonical rather than duplicating its detailed rules here. Writing rules do not authorize changes, publication, or additional notifications.
