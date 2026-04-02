# IMECE Agent Development Guide

This guide tells future agents how to analyze IMECE results and which document to update.

Read [`implementation.md`](./implementation.md) first.
That file is the normative source of truth for study scope, task definitions, condition boundaries, success criteria, and phase meaning.

## 1. Document Ownership Map

Use the IMECE docs this way:

| File | What belongs there |
| --- | --- |
| [`implementation.md`](./implementation.md) | normative study design, paper flow, code map, success criteria, fixed phase rules |
| [`experiment-record.md`](./experiment-record.md) | preserved batches, results, analysis, caveats, paper-safe claims |
| [`runbook.md`](./runbook.md) | commands, execution steps, runner arguments, operational checks |
| [`agent-development-guide.md`](./agent-development-guide.md) | how agents should inspect artifacts, analyze outcomes, and update docs |
| [`design-rationale.md`](./design-rationale.md) | legacy redirect only; do not treat as the primary rationale document |

If a fact is about intended methodology, it belongs in `implementation.md`.
If a fact is about what actually ran or what the preserved evidence shows, it belongs in `experiment-record.md`.
If a fact is about how to execute commands, it belongs in `runbook.md`.

## 2. Default Workflow for Result Analysis

When asked to analyze new IMECE results:

1. read [`implementation.md`](./implementation.md)
2. read the relevant sections of [`experiment-record.md`](./experiment-record.md)
3. inspect the target batch directory
4. read `batch_state.json`, `analysis.json`, and `audit.json`
5. inspect representative `metrics.json`, `metadata.json`, `prompt.txt`, and `gemini.jsonl`
6. compare the batch outcome against the current normative task definitions
7. update the correct document with evidence-qualified language

Do not jump directly from one `metrics.json` file to paper claims.
Always go through the batch summaries and caveat files first.

## 3. Required Analysis Discipline

### Preserve the distinction between intended and preserved

- `implementation.md` says what the study is supposed to mean
- `experiment-record.md` says what is actually preserved

If they diverge, do not silently flatten the difference.
Record the divergence explicitly.

### Preserve the distinction between stored and current scoring

Do not assume old `task_success` fields still match the current task rules.

Always check:

- current scoring in [`ros_mcp/imece/scoring.py`](../../ros_mcp/imece/scoring.py)
- `audit.json.current_task_success_by_condition_task`
- `audit.json.stored_vs_current_task_success_mismatches`

### Preserve the distinction between failure evidence and interface drift

If `audit.json` or `analysis.py` indicates historical interface mismatch, do not present contaminated failure counts as clean evidence of agent reasoning failure.

### Preserve the distinction between preserved evidence and planned work

Do not write future phases as if they have already happened.
`official_sim` and `official_real` must remain pending until preserved artifacts exist.

## 4. What to Update After Each Kind of Change

### If the study specification changes

Update:

- [`implementation.md`](./implementation.md)

Examples:

- task definitions
- success criteria
- real-flight task scope
- allowed helper boundary
- fixed phase counts

### If a new preserved batch is added

Update:

- [`experiment-record.md`](./experiment-record.md)

Include:

- exact batch ID
- phase meaning
- what was held fixed
- what changed
- results from `batch_state.json`, `analysis.json`, and `audit.json`
- for educational batches, the exact `prompt_level` ladder, the `prompt_variant` sibling IDs, and whether `T4` was excluded
- newly supported claims
- still unsupported claims

### If runner usage or argument meaning changes

Update:

- [`runbook.md`](./runbook.md)

Include:

- exact command shape
- exact argument meaning
- any changed prerequisites
- any changed artifact expectations

### If the documentation workflow changes

Update:

- [`agent-development-guide.md`](./agent-development-guide.md)

Examples:

- new analysis rules
- new doc ownership rules
- new caveat handling

## 5. How to Analyze a Batch Correctly

### Minimum read set

For every serious analysis pass, inspect:

- `batch_state.json`
- `analysis.json`
- `audit.json`
- at least one representative successful `metrics.json`
- at least one representative failed `metrics.json`
- at least one corresponding `prompt.txt`
- at least one corresponding `metadata.json`

### Minimum questions to answer

- What phase is this batch supposed to represent?
- Is it preserved evidence or a scratch run?
- What was fixed across the batch?
- If it is an educational batch, which `prompt_level` ladder and which `prompt_variant` sibling IDs were crossed, and was only the first-turn prompt varied?
- What changed relative to the previous preserved state?
- What do `analysis.json` and `audit.json` say under current scoring?
- Which paper claims become stronger, and which still remain unsupported?

### Minimum evidence language

Preferred wording:

- `the preserved discovery batch shows ...`
- `under the current classifier ...`
- `the current audit reports ...`
- `this supports the narrow claim that ...`

Avoid wording like:

- `the system proves ...`
- `generic ROS control works ...`
- `the model learned ...`
- `sim-to-real transfer was demonstrated ...`

unless preserved evidence explicitly supports that statement.

## 6. Paper-claim Guardrails

Never claim any of the following unless new preserved evidence exists:

- full `C2` validation across `T1-T4`
- real-flight transfer results
- repeated frame/sign failures as a frozen-helper driver
- a clean numeric prompt-only success improvement uncontaminated by interface drift

Safe current claims are narrower:

- discovery justifies a frozen minimal `C2` subset
- prompt-only guidance improves reasoning but does not reliably remove transport/timing and safety failures
- targeted `C2:T3` validation closes the remaining preserved square-pattern gap

## 7. Documentation Style Rules for Agents

- keep `implementation.md` normative and stable
- keep `experiment-record.md` evidence-driven and explicit about caveats
- keep `runbook.md` operational and command-oriented
- keep this guide procedural and meta-level
- use exact batch IDs, task IDs, and condition IDs
- avoid vague references such as `latest run` or `current result` without naming the batch

## 8. Commit Rule

Treat these IMECE docs like any other repo artifact.
Do not commit or publish changes to them unless the user explicitly asks for that.

If asked to modify them without a commit request:

- make the minimum proportional change
- leave the edits uncommitted
- state clearly in the final response what was edited

## 9. Completion Checklist for Agent Documentation Work

Before finishing a documentation task, confirm:

- each edited file was necessary
- the updated file matches its intended ownership
- preserved evidence and intended methodology are not mixed together carelessly
- unsupported claims are still marked as unsupported
- commands and argument meanings in `runbook.md` match the current CLI
