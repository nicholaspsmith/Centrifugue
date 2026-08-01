# Claude Code Instructions for Centrifugue

Centrifugue is a Firefox/Zen Browser extension that extracts audio stems from YouTube videos using Demucs AI.

## Project Structure

```text
centrifugue/
├── extension-firefox/      # Firefox/Zen extension (Manifest V2)
│   ├── manifest.json       # Extension configuration
│   ├── background.js       # Native messaging & progress polling
│   ├── content.js          # Floating UI on YouTube pages
│   └── popup/              # Extension popup UI
├── native-host/            # Native messaging host (Python)
│   └── centrifugue_host.py  # Python backend for stem separation
├── venv-demucs/            # Python venv (created by install.sh)
├── specs/                  # Feature specifications (speckit workflow)
├── .claude/                # Claude Code configuration
│   ├── rules.md            # Git commit rules
│   └── commands/           # Speckit slash commands
├── .specify/               # Speckit workflow templates
│   ├── memory/             # Constitution and project memory
│   ├── scripts/            # Workflow scripts
│   └── templates/          # Spec/plan/task templates
└── install.sh              # Installation script
```

## Technology Stack

### Browser Extension (JavaScript)
- Firefox WebExtensions API
- Native messaging protocol
- Content scripts for YouTube DOM manipulation

### Native Host (Python)
- Python 3.9+
- Demucs (Meta's audio source separation)
- yt-dlp (YouTube audio download)
- FFmpeg (audio processing)
- MPS GPU acceleration on Apple Silicon

## Feature-Specific Context

When working on a feature branch (e.g., `001-add-quality-presets`), check for a matching
specs directory at `specs/[branch-name]/`. If it exists, read these files for feature context:

- `specs/[branch-name]/spec.md` - Feature specification and requirements
- `specs/[branch-name]/plan.md` - Implementation plan and technical decisions
- `specs/[branch-name]/tasks.md` - Task breakdown and progress tracking

## Speckit Workflow

This project uses speckit for feature specification and task tracking.

### Available Commands

- `/speckit.specify` - Create or update feature specifications
- `/speckit.clarify` - Resolve specification ambiguities
- `/speckit.plan` - Create implementation plans
- `/speckit.plan.validate` - Validate plans for completeness
- `/speckit.tasks` - Generate task breakdowns
- `/speckit.implement` - Execute implementation tasks
- `/speckit.checklist` - Generate requirements quality checklists
- `/speckit.analyze` - Cross-artifact consistency check

### Workflow

When working on features:

1. Review the feature spec at `specs/[feature-name]/spec.md`
2. Check the implementation plan at `specs/[feature-name]/plan.md`
3. Work through tasks in `specs/[feature-name]/tasks.md` in order
4. Mark tasks as complete by changing `[ ]` to `[x]`
5. Commit changes following rules in `.claude/rules.md`

## Issue Tracking (beads)

This repo tracks bugs and tasks with [beads](https://github.com/steveyegge/beads)
(`bd` CLI, issue prefix `cf-`, data in `.beads/`):

- `bd ready` — list actionable issues; `bd list` — all issues
- `bd show cf-<id>` — full description (root cause and suggested fix are kept there)
- `bd create "title" -t bug|task|chore -p 0-4 -d "..."` — file new findings
- `bd close cf-<id>` when fixed; issues export to `.beads/issues.jsonl` (committed)

When you discover a bug you aren't fixing immediately, file it with `bd create`
rather than leaving it in conversation.

## Constitution

Follow the project principles defined in `.specify/memory/constitution.md`:

- Documentation-First Development
- Simplicity (YAGNI)
- Modularity & Composability
- Observability & Debugging
- Atomic Commits & Version Control Discipline

## Key Files

| File | Purpose |
|------|---------|
| `native-host/centrifugue_host.py` | Core stem separation logic, native messaging |
| `extension-firefox/background.js` | Progress polling, native messaging bridge |
| `extension-firefox/content.js` | YouTube floating UI, status display |
| `extension-firefox/popup/popup.html` | Extension popup interface |
| `install.sh` | Setup script (venv, dependencies, native messaging) |

## Development Notes

### Native Messaging Architecture

The extension communicates with a Python native messaging host:
1. Extension sends messages via `browser.runtime.sendNativeMessage()`
2. Native host spawns independent worker subprocess for long-running tasks
3. Worker writes progress to JSON files (`~/.centrifugue_progress.json`)
4. Extension polls for progress updates every 2 seconds

### Important Patterns

- **Worker subprocess**: Use `start_new_session=True` for detached processing
- **Progress files**: JSON-based state stored in user home directory
- **Path resolution**: All paths relative to `SCRIPT_DIR` and `PROJECT_ROOT`

### Testing

Manual testing workflow:
1. Run `./install.sh` to set up the environment
2. Load extension in Firefox via `about:debugging`
3. Navigate to a YouTube video
4. Use the floating button or extension popup to test

### Common Issues

- **"Demucs not found"**: Run `./install.sh` to create venv
- **Native messaging fails**: Check `~/Library/Application Support/Mozilla/NativeMessagingHosts/`
- **Job interrupted**: Ensure worker subprocess is properly detached


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:6cd5cc61 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->
