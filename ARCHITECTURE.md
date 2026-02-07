# Asktra — Architecture

## High-level flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           USER / ENGINEER / CTO                               │
│  "Why does auth timeout fail?" / "Analyze the v2.4 timeout issue."           │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  INPUT LAYER                                                                  │
│  • Slack (intent)   • Git (implementation)   • Jira (tickets)                │
│  • Docs (stated behavior)   • Releases (version boundaries)                   │
│  • Optional: dataset overrides (paste), prior_context (Hard Truths), image   │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  GEMINI — CAUSAL RECONCILIATION PIPELINE                                      │
│                                                                               │
│  ┌──────────────────────┐    ┌──────────────────────┐    ┌─────────────────┐ │
│  │ VERSION INFERRER     │───▶│ CAUSAL REASONER      │───▶│ SELF-CORRECTION │ │
│  │ (Gemini 3)           │    │ (Gemini 3)           │    │ (optional)      │ │
│  │                      │    │                      │    │                 │ │
│  │ • Infer release      │    │ • Root cause         │    │ • Verify        │ │
│  │   boundary (e.g.v2.4)│    │ • Contradictions     │    │   contradictions│ │
│  │ • Evidence + conf.   │    │ • Risk, fix_steps    │    │ • Truth Gaps    │ │
│  │ • responseSchema     │    │ • reasoning_trace    │    │                 │ │
│  │ • thinkingLevel HIGH │    │ • sources, truth_gaps│    │                 │ │
│  └──────────────────────┘    └──────────────────────┘    └─────────────────┘ │
│           │                              │                          │         │
│           └──────────────────────────────┼──────────────────────────┘         │
│                                          ▼                                    │
│  ┌──────────────────────┐    ┌──────────────────────┐    ┌─────────────────┐ │
│  │ EMIT DOCS            │    │ RECONCILIATION      │    │ RECONCILIATION  │ │
│  │ (PR-ready Markdown)  │    │ PATCH (PR body)     │    │ BUNDLE          │ │
│  │ • True system state  │    │ • finding_id →      │    │ • post_mortem   │ │
│  │ • No auto-merge      │    │   GitHub/Confluence │    │ • pr_diff       │ │
│  └──────────────────────┘    └──────────────────────┘ │ • slack_summary │ │
│                                                          └─────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  OUTPUT UI                                                                   │
│  • Inferred version + evidence   • Root cause, contradictions, risk         │
│  • Fix steps, verification       • Reasoning trace, source citations        │
│  • Truth Gaps, Hard Truths       • Emitted docs, reconciliation patch/bundle │
│  • Thought signatures (Gemini reasoning when GEMINI_THINKING_LEVEL=HIGH)    │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Input layer

| Input | Description |
|-------|-------------|
| **Slack** | Developer intent, discussions (JSON). |
| **Git** | Commits, tags, implementation reality (JSON). |
| **Jira** | Tickets, timelines (JSON). |
| **Docs** | Stated behavior (Markdown). |
| **Releases** | Version boundaries, release notes (Markdown). |
| **Dataset overrides** | Frontend-edited sources (paste). |
| **Prior context** | Living knowledge / Hard Truths from the session. |
| **Image** | Optional screenshot or dashboard (multimodal). |

## Gemini pipeline (technical)

| Phase | Name | Activity | Tech |
|-------|------|----------|------|
| **0** | **Semantic Intent Mapping** | (Optional) Extract latent intent/risk from Slack/Jira before answering. | `GEMINI_THINKING_LEVEL=HIGH`, `thinking_level: HIGH` |
| 1 | **Version Inferrer** | Infer release boundary (e.g. v2.4) from timestamps and evidence. | `infer_version` prompt, `response_mime_type: application/json` |
| 2 | **Causal Reasoner** | Root cause, contradictions, risk, fix steps, sources, reasoning_trace, truth_gaps. | `causal_reasoning` prompt, prior_context (Hard Truths), JSON out |
| 3 | **Self-Correction** | When contradictions exist: verify against sources before final answer. | `verify_contradiction` prompt |
| 4 | **Emit Docs** | PR-ready Markdown reflecting *true* behavior (no auto-merge). | `emit_docs` prompt |
| 5 | **Reconciliation Patch** | PR body or patch for a finding (e.g. doc drift → GitHub/Confluence). | `emit_reconciliation_patch` prompt |
| 6 | **Reconciliation Bundle** | post_mortem (Markdown), pr_diff (Markdown), slack_summary (text). | `reconciliation_bundle` prompt, JSON (post_mortem, pr_diff, slack_summary) |
| **7** | **Causal Reconciliation (Closer)** | Validate generated answer against Git/sources; thought signatures. | Thought chain when thinking level HIGH |

## Gemini usage (per component)

| Component | Model | Config / behavior |
|-----------|--------|-------------------|
| Version Inferrer | `GEMINI_MODEL` (default `gemini-3-flash-preview`) | `response_mime_type: application/json`, optional `ThinkingConfig(thinking_level="HIGH")` when `GEMINI_THINKING_LEVEL=HIGH`. |
| Causal Reasoner | Same | JSON schema (root_cause, contradictions, risk, fix_steps, verification, sources, reasoning_trace, truth_gaps). Prior context for Hard Truths. |
| Verify Contradiction | Same | JSON (verification_steps). Used when contradictions exist. |
| Emit Docs | Same | Plain Markdown; no JSON. |
| Reconciliation Patch | Same | Plain Markdown (PR body / patch description). |
| Reconciliation Bundle | Same or `GEMINI_BUNDLE_MODEL` | JSON (post_mortem, pr_diff, slack_summary). Uses `GEMINI_BUNDLE_API_KEY` if set. |

All agents use **Gemini 3** by default (`gemini-3-flash-preview`); set `GEMINI_MODEL` (e.g. `gemini-3-pro-preview`) for deeper reasoning. Structured outputs feed the UI; thought signatures are visible when `GEMINI_THINKING_LEVEL=HIGH`.

## Data flow (single ask)

1. **User** asks a question (e.g. "Why does auth timeout fail?").
2. **Version Inferrer** reads Slack, Git, Jira, Docs, Releases → infers version (e.g. v2.4) + evidence + confidence.
3. **Causal Reasoner** reasons only within that version: intent (Slack) vs implementation (Git) vs docs → root_cause, contradictions, risk, fix_steps, sources, reasoning_trace, truth_gaps. Uses prior_context (Hard Truths) if present.
4. **Self-Correction** (if contradictions): verify_contradiction → verification steps before final answer.
5. **Output** returned to UI: inferred version, causal summary, reasoning trace, source details (click to see raw JSON/text).
6. **Optional**: User requests **Emit Docs** → PR-ready Markdown; or **Reconciliation Patch** (finding_id, target, action) → PR body; or **Reconciliation Bundle** → post_mortem + pr_diff + slack_summary.

## Audit & compliance

Every finding is grounded in a **specific source** (Slack, Git, Jira, Docs). The UI exposes **source details** (raw JSON/text) so auditors can trace from developer intent to documentation. No hallucination: citations and Truth Gaps are explicit.
