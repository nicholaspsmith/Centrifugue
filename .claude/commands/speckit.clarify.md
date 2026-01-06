---
description: Identify underspecified areas in the current feature spec by asking up to 5 highly targeted clarification questions and encoding answers back into the spec.
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Outline

Goal: Detect and reduce ambiguity or missing decision points in the active feature specification and record the clarifications directly in the spec file.

Note: This clarification workflow is expected to run (and be completed) BEFORE invoking `/speckit.plan`. If the user explicitly states they are skipping clarification (e.g., exploratory spike), you may proceed, but must warn that downstream rework risk increases.

Execution steps:

1. Run `.specify/scripts/bash/check-prerequisites.sh --json --paths-only` from repo root **once**. Parse minimal JSON payload fields:
   - `FEATURE_DIR`
   - `FEATURE_SPEC`
   - If JSON parsing fails, abort and instruct user to re-run `/speckit.specify` or verify feature branch environment.

2. Load the current spec file. Perform a structured ambiguity & coverage scan using this taxonomy. For each category, mark status: Clear / Partial / Missing.

   Categories to scan:
   - Functional Scope & Behavior
   - Domain & Data Model
   - Interaction & UX Flow
   - Non-Functional Quality Attributes
   - Integration & External Dependencies
   - Edge Cases & Failure Handling
   - Constraints & Tradeoffs
   - Terminology & Consistency
   - Completion Signals

3. Generate (internally) a prioritized queue of candidate clarification questions (maximum 5). Apply these constraints:
   - Maximum of 10 total questions across the whole session.
   - Each question must be answerable with EITHER:
     - A short multiple-choice selection (2-5 distinct, mutually exclusive options), OR
     - A one-word / short-phrase answer (<=5 words).
   - Only include questions whose answers materially impact architecture, data modeling, task decomposition, test design, UX behavior, operational readiness, or compliance validation.

4. Sequential questioning loop (interactive):
   - Present EXACTLY ONE question at a time.
   - For multiple-choice questions: provide recommendation with reasoning, then present options as table.
   - After the user answers: validate and record in working memory.
   - Stop asking when: all critical ambiguities resolved, user signals completion, or 5 questions reached.

5. Integration after EACH accepted answer:
   - Ensure a `## Clarifications` section exists
   - Append bullet: `- Q: <question> → A: <final answer>`
   - Apply clarification to appropriate spec section
   - Save the spec file AFTER each integration

6. Validation after EACH write plus final pass.

7. Write the updated spec back to `FEATURE_SPEC`.

8. Report completion:
   - Number of questions asked & answered
   - Path to updated spec
   - Sections touched
   - Coverage summary
   - Suggested next command

Behavior rules:

- If no meaningful ambiguities found, respond: "No critical ambiguities detected worth formal clarification."
- If spec file missing, instruct user to run `/speckit.specify` first
- Never exceed 5 total asked questions
- Respect user early termination signals ("stop", "done", "proceed")
