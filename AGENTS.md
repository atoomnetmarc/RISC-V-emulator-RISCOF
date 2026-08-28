# Agent Rules Index

## Core Rules

- **Hobby-grade project** - Be gentle with advice. Be honest if the code smells.
- **Update docs on code change** - Check any `.md` file when the code changes.
- **Language** - Write everything in English. Reply in the user's language.
- **No doxing** - Never document absolute paths.
- **Prove calculations** - Validate calculations with Python. Do not reason manually.
- **X-Y problem?** - Ask the user about X. Do not propose a solution Y first.
- **Ask questions** - Asking the user questions is allowed and encouraged. Prefer the `/grill-me` skill when it is available. Present ALL questions with multiple answer options. Use a table with one row per option and these columns: `Answer | Industry standard | Risk | Reward | Fits test-framework | Notes`. Read the relevant documents or code before you ask. Add a final row labeled "From scratch" to propose a custom alternative. After the table, state the recommended answer and explain why.
- **Answer questions, execute commands** - Answer a question and offer follow-up choices when the user asks one. Act only when the user gives an explicit instruction.
- **Concise completions** - State only the final result in `attempt_completion`. Do not re-explain steps, summarize previous outputs, or repeat information the user already saw.
- **No fancy UTF-8 characters** - Use a simple ASCII character when one exists.

## Code Quality Rules

- ASD-STE100
- Readability over cleverness.
- Understand fully before simplifying.
- YAGNI. Do not speculate.
- Use native functionality.
- No dependencies for code that a few lines do.
- DRY.
- Boring over clever.
- One line if possible.
- No scaffolding for later.
- No dead code.
- Deletion over addition.
- Smallest diff.

## Quick Reference

- Run `clang-format -i` on new or modified source files after editing.
- Run `prettier --write` on new or modified markdown files after editing.
- No God-files. Refactor at about 500 lines.
- No historic references in comments or documentation. Do not use "initial", "previously", "no longer", "now", "before", "after", "was", "became", "replaces the old", "the current", or "Fase X" markers. Write in the timeless present tense. Describe the system as it is.
- No changelogs, phase markers, or technical decisions in source comments. Changelogs belong in git commit messages. "Fase X" markers belong nowhere. Technical decisions belong in ADR documents under `docs/adr/`.
- No hard line-wrapping in markdown. Put all sentences of one paragraph on one line.
