# Centrifugue Constitution

## Core Principles

### I. Documentation-First Development

Every feature begins with clear, written specification before any code is written. Documentation must:

- Define user scenarios with acceptance criteria (Given/When/Then format)
- Specify functional requirements with clear identifiers (FR-001, FR-002, etc.)
- Include measurable success criteria
- Be independently testable and technology-agnostic
- Mark unclear requirements explicitly (NEEDS CLARIFICATION)

**Rationale**: Clear documentation prevents scope creep, enables parallel development, and serves as a contract between stakeholders. Writing documentation first forces critical thinking about requirements before implementation costs accrue.

### II. Simplicity (YAGNI)

Build only what is needed now. Avoid over-engineering and speculative features.

- Reject complexity that isn't justified by current requirements
- Three similar lines are better than a premature abstraction
- Trust internal code and framework guarantees
- Only validate at system boundaries (user input, external APIs)
- No feature flags or backward-compatibility shims unless required

**Rationale**: Unnecessary complexity increases cognitive load, maintenance burden, and bug surface area. Future requirements are often wrong; building for hypothetical needs wastes time and creates technical debt.

### III. Modularity & Composability

Build features as small, focused, independently testable components.

- Each module/component must have a single, clear purpose
- Components must be self-contained with minimal dependencies
- Interfaces must be well-defined and stable
- Enable independent deployment and testing of user stories
- Prioritize composition over inheritance or complex hierarchies

**Rationale**: Modular systems are easier to understand, test, modify, and scale. Independent components reduce coupling, enable parallel development, and allow incremental feature delivery.

### IV. Observability & Debugging

Systems must be debuggable and transparent in their operation.

- Text-based input/output enables inspection and debugging
- Structured logging for all significant operations
- Clear error messages with actionable context
- Trace data flow through components
- Support JSON and human-readable output formats

**Rationale**: When (not if) things go wrong, observability determines recovery time. Text protocols and structured logs enable quick diagnosis without debuggers or production access.

### V. Atomic Commits & Version Control Discipline

Every commit must have a single, clear responsibility. Commits MUST follow the rules defined in `.claude/rules.md`.

- One logical change per commit (atomic commits)
- Commit messages must be under 100 characters
- Use imperative mood ("Add feature" not "Added feature")
- No AI attribution in commit messages (no "Generated with Claude Code")
- Co-Author tags allowed: "Co-Authored-By: Claude <noreply@anthropic.com>"
- Reference issue/task numbers in commit body, not subject line
- Keep commits focused and independently revertable

**Rationale**: Atomic commits enable precise rollbacks, bisection for debugging, and clear project history. Single-responsibility commits make code review efficient and allow cherry-picking specific changes. Clean commit messages serve as executable documentation of intent.

## Development Workflow

### Feature Development Process

1. **Specification** (`/speckit.specify`): Create feature spec with user stories, requirements, and success criteria
2. **Clarification** (`/speckit.clarify`): Resolve ambiguities before planning
3. **Planning** (`/speckit.plan`): Design implementation approach with constitution compliance check
4. **Task Generation** (`/speckit.tasks`): Break down into independently testable tasks organized by user story
5. **Implementation** (`/speckit.implement`): Execute tasks in priority order (P1 -> P2 -> P3)
6. **Validation**: Verify each user story works independently before moving to next

### Constitution Compliance

Every implementation plan MUST include a Constitution Check section that verifies:

- Documentation-first: Spec complete before planning begins
- Modularity: User stories are independently testable
- Simplicity: Complexity violations documented with justification
- Observability: Logging and error handling included
- Commit discipline: Implementation follows atomic commit guidelines from .claude/rules.md

Plans with unjustified complexity violations MUST NOT proceed to implementation.

## Quality Standards

### Code Review Requirements

- All code changes require review against constitution principles
- Documentation must be updated with code changes
- Complexity additions require explicit justification
- Commits must follow atomic commit discipline (.claude/rules.md)

### Documentation Requirements

- Every feature has a spec with user scenarios and acceptance criteria
- Every implementation has a plan with constitution check
- Every task references exact file paths
- Unclear requirements marked "NEEDS CLARIFICATION"

### Version Control Requirements

- Follow commit rules defined in .claude/rules.md
- One logical change per commit (atomic commits)
- Commit messages under 100 characters
- Imperative mood for commit messages
- No AI attribution in commit messages
- Issue/task references in commit body only

## Governance

### Amendment Process

1. Propose amendment with rationale and impact analysis
2. Update constitution with version bump following semantic versioning:
   - **MAJOR**: Backward-incompatible changes (removing/redefining principles)
   - **MINOR**: New principles or materially expanded guidance
   - **PATCH**: Clarifications, wording fixes, non-semantic refinements
3. Update all dependent templates (plan, spec, tasks)
4. Document changes in Sync Impact Report (HTML comment at top of file)
5. Commit with message: `docs: amend constitution to vX.Y.Z (description)`

### Compliance Review

- Constitution supersedes all other development practices
- All feature plans must pass constitution check before implementation
- Templates must remain aligned with constitutional principles
- Violations require documented justification or rejection

**Version**: 1.0.0 | **Ratified**: 2026-01-06
