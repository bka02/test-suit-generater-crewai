# QACrew — Agent Workflow

This diagram shows how the CrewAI **`TestSuiteFlow`** orchestrates the **`QACrew`**
(5 agents / 5 tasks, `Process.sequential`) to turn a single user story into a
schema-validated JSON test suite.

## Flow + Crew overview

```mermaid
flowchart TD
    subgraph FLOW["TestSuiteFlow (CrewAI Flow)"]
        direction LR
        A["@start<br/>ingest_story<br/><i>validate story</i>"]
        B["@listen(ingest_story)<br/>generate_suite<br/><i>runs QACrew</i>"]
        C["@listen(generate_suite)<br/>save_suite<br/><i>writes output/test_suite.json</i>"]
        A -->|user_story| B -->|raw json| C
    end

    B --> CREW

    subgraph CREW["QACrew — Process.sequential"]
        direction TB
        SA["story_analyst<br/><b>analyse_story_task</b><br/>extract actors, rules,<br/>acceptance criteria"]
        HP["happy_path_designer<br/><b>happy_path_task</b><br/>positive flows"]
        EC["edge_case_designer<br/><b>edge_case_task</b><br/>limits, expiry, concurrency"]
        SEC["security_designer<br/><b>security_task</b><br/>injection, XSS, CSRF, rate-limit"]
        QR["qa_reviewer<br/><b>assemble_suite_task</b><br/>dedupe + review<br/>output_pydantic=AssembledSuite"]

        SA -->|context| HP
        SA -->|context| EC
        SA -->|context| SEC
        SA -->|context| QR
        HP -->|context| QR
        EC -->|context| QR
        SEC -->|context| QR
    end

    QR --> OUT["AssembledSuite<br/>{ story_summary, test_cases[] }"]
```

## How to read it

- **Flow layer** — three sequential steps wired with `@start` / `@listen`.
  Only these appear in CrewAI's native `plot()` output
  (`test_suite_flow.html`).
- **Crew layer** — the five agents that execute inside `generate_suite`:
  1. `story_analyst` runs first; its analysis becomes the `context` for every
     downstream task.
  2. `happy_path_designer`, `edge_case_designer`, and `security_designer` each
     produce their category of test cases.
  3. `qa_reviewer` consumes **all four** prior outputs, removes duplicates, and
     emits the final schema-validated `AssembledSuite`
     (enforced via `output_pydantic`).

## Categories produced

| Agent | Task | `TestCategory` |
|-------|------|----------------|
| `happy_path_designer` | `happy_path_task` | `happy_path` |
| `edge_case_designer` | `edge_case_task` | `boundary_edge_case` |
| `security_designer` | `security_task` | `security_validation` |
