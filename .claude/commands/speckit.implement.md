---
description: Execute the implementation plan by processing and executing all tasks defined in tasks.md
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Outline

1. Run `.specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks` from repo root and parse FEATURE_DIR and AVAILABLE_DOCS list. All paths must be absolute. For single quotes in args like "I'm Groot", use escape syntax: e.g 'I'\''m Groot' (or double-quote if possible: "I'm Groot").

2. **Check checklists status** (if FEATURE_DIR/checklists/ exists):
   - Scan all checklist files in the checklists/ directory
   - For each checklist, count:
     - Total items: All lines matching `- [ ]` or `- [X]` or `- [x]`
     - Completed items: Lines matching `- [X]` or `- [x]`
     - Incomplete items: Lines matching `- [ ]`
   - Create a status table:

     ```text
     | Checklist | Total | Completed | Incomplete | Status |
     |-----------|-------|-----------|------------|--------|
     | ux.md     | 12    | 12        | 0          | ✓ PASS |
     | test.md   | 8     | 5         | 3          | ✗ FAIL |
     | security.md | 6   | 6         | 0          | ✓ PASS |
     ```

   - Calculate overall status:
     - **PASS**: All checklists have 0 incomplete items
     - **FAIL**: One or more checklists have incomplete items

   - **If any checklist is incomplete**:
     - Display the table with incomplete item counts
     - **STOP** and ask: "Some checklists are incomplete. Do you want to proceed with implementation anyway? (yes/no)"
     - Wait for user response before continuing
     - If user says "no" or "wait" or "stop", halt execution
     - If user says "yes" or "proceed" or "continue", proceed to step 3

   - **If all checklists are complete**:
     - Display the table showing all checklists passed
     - Automatically proceed to step 3

3. Load and analyze the implementation context:
   - **REQUIRED**: Read tasks.md for the complete task list and execution plan
   - **REQUIRED**: Read plan.md for tech stack, architecture, and file structure
   - **IF EXISTS**: Read data-model.md for entities and relationships
   - **IF EXISTS**: Read contracts/ for API specifications and test requirements
   - **IF EXISTS**: Read research.md for technical decisions and constraints
   - **IF EXISTS**: Read quickstart.md for integration scenarios

4. **Project Setup Verification**:
   - **REQUIRED**: Create/verify ignore files based on actual project setup:

   **Detection & Creation Logic**:
   - Check if the following command succeeds to determine if the repository is a git repo (create/verify .gitignore if so):

     ```sh
     git rev-parse --git-dir 2>/dev/null
     ```

   - Check if Dockerfile\* exists or Docker in plan.md → create/verify .dockerignore
   - Check if .eslintrc\* exists → create/verify .eslintignore
   - Check if eslint.config.\* exists → ensure the config's `ignores` entries cover required patterns
   - Check if .prettierrc\* exists → create/verify .prettierignore
   - Check if .npmrc or package.json exists → create/verify .npmignore (if publishing)

   **If ignore file already exists**: Verify it contains essential patterns, append missing critical patterns only
   **If ignore file missing**: Create with full pattern set for detected technology

   **Common Patterns by Technology** (from plan.md tech stack):
   - **JavaScript/TypeScript**: `node_modules/`, `dist/`, `build/`, `*.log`, `.env*`
   - **Python**: `__pycache__/`, `*.pyc`, `.venv/`, `venv/`, `dist/`, `*.egg-info/`

5. Parse tasks.md structure and extract:
   - **Task phases**: Setup, Tests, Core, Integration, Polish
   - **Task dependencies**: Sequential vs parallel execution rules
   - **Task details**: ID, description, file paths, parallel markers [P]
   - **Execution flow**: Order and dependency requirements

6. Execute implementation following the task plan:
   - **Phase-by-phase execution**: Complete each phase before moving to the next
   - **Respect dependencies**: Run sequential tasks in order, parallel tasks [P] can run together
   - **File-based coordination**: Tasks affecting the same files must run sequentially
   - **Validation checkpoints**: Verify each phase completion before proceeding

7. Implementation execution rules:
   - **Setup first**: Initialize project structure, dependencies, configuration
   - **Core development**: Implement models, services, CLI commands, endpoints
   - **Integration work**: Database connections, middleware, logging, external services
   - **Polish and validation**: Unit tests, performance optimization, documentation

8. Progress tracking and error handling:
   - Report progress after each completed task
   - Halt execution if any non-parallel task fails
   - For parallel tasks [P], continue with successful tasks, report failed ones
   - Provide clear error messages with context for debugging
   - Suggest next steps if implementation cannot proceed
   - **IMPORTANT** For completed tasks, make sure to mark the task off as [X] in the tasks file.

9. Completion validation:
   - Verify all required tasks are completed
   - Check that implemented features match the original specification
   - Validate that tests pass and coverage meets requirements
   - Confirm the implementation follows the technical plan
   - Report final status with summary of completed work

10. **Automatic PR Creation Offer**: After all tasks are complete, offer to create a pull request:

a. **Detect completion status**:

- Parse tasks.md to count total tasks vs completed tasks
- Check if all tasks marked with `- [x]` or `- [X]`
- If any tasks remain incomplete (`- [ ]`), skip PR creation offer and proceed to Next Steps

b. **Offer PR creation** (only if 100% tasks complete):

- Use AskUserQuestion: "All tasks complete! Would you like to create a pull request now?"
- Options: "Yes, create PR" / "No, I'll create it manually later"
- If user selects "No", proceed to Next Steps

c. **Gather PR metadata** (if user accepts):

- Get current branch: `git rev-parse --abbrev-ref HEAD`
- Validate branch name matches pattern `^[0-9]{3}-[a-z0-9-]+$` (reject if invalid)
- Parse branch format `NNN-short-name` to extract feature number
- Get feature directory from check-prerequisites.sh output (FEATURE_DIR)
- Read spec.md for feature summary/description
- Find associated GitHub issue number:
  - Run `gh issue list --search "in:title [NNN]" --state open --json number,title`
  - Extract issue number from results (should match `[NNN]` format)
  - If no issue found, warn user but continue (PR will still be created)

d. **Generate PR content**:

- Title format: `[NNN] Feature Short Name` (from branch name)
- Body format:

  ```markdown
  ## Summary

  [Brief description from spec.md Overview or Summary section]

  ## Changes

  - Completed [count] tasks from implementation plan
  - [List key deliverables from completed tasks]

  ## Documentation

  - **Specification**: [`specs/NNN-short-name/spec.md`](./specs/NNN-short-name/spec.md)
  - **Implementation Plan**: [`specs/NNN-short-name/plan.md`](./specs/NNN-short-name/plan.md)
  - **Tasks**: [`specs/NNN-short-name/tasks.md`](./specs/NNN-short-name/tasks.md)

  ## Task Completion

  ✅ All X tasks completed

  Closes #[issue-number]
  ```

e. **Create PR**:

- Create temporary file in /tmp: `PR_BODY_FILE=$(mktemp /tmp/pr-body-XXXXXX.md)`
- Set restrictive permissions: `chmod 600 "$PR_BODY_FILE"`
- Set up cleanup trap: `trap 'rm -f "$PR_BODY_FILE"' EXIT INT TERM`
- Write PR body to temporary file
- Run: `gh pr create --title "[title]" --body-file "$PR_BODY_FILE" --base main`
- If successful: Display PR URL and number
- If failed: Show error and manual fallback instructions
- Temporary file automatically cleaned up by trap on all exit paths

f. **Error handling (non-blocking)**:

- GitHub remote check: Skip if not a GitHub repo
- Auth failure: Show manual PR creation instructions
- API errors: Provide fallback command with pre-filled title/body
- Manual fallback template:
  ```bash
  # Create PR manually:
  gh pr create --title "[NNN] Feature Name" --body-file "FEATURE_DIR/pr-body.md" --base main
  ```

g. **Success message**:

- Display PR URL: `Created PR #123: https://github.com/owner/repo/pull/123`
- Note that merging will automatically close the linked issue
- Remind about CI checks that need to pass

Note: This command assumes a complete task breakdown exists in tasks.md. If tasks are incomplete or missing, suggest running `/speckit.tasks` first to regenerate the task list.

## Next Steps

After completing all tasks (or after stopping at a checkpoint), use AskUserQuestion:

**Question**: "Implementation tasks complete! What would you like to do next?"

**Options**:

- **Create Pull Request**: I'll help create a PR with the changes
- **Run Final Tests**: Execute the complete test suite
- **Review Changes**: I'll review the implementation myself
- **Continue with Remaining Tasks**: There are more tasks to complete
- **Exit**: I'm done for now

- Execute the selected action if applicable
