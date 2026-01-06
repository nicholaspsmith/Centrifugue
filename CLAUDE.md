# Claude Code Instructions for Centrifugue

Centrifugue is a Firefox/Zen Browser extension that extracts audio stems from YouTube videos using Demucs AI.

## Project Structure

```text
centrifugue/
├── extension/              # Browser extension (JavaScript)
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
| `extension/background.js` | Progress polling, native messaging bridge |
| `extension/content.js` | YouTube floating UI, status display |
| `extension/popup/popup.html` | Extension popup interface |
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
