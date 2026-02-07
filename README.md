# Asktra

**The World's First Causal, Documentation-Aware Truth Protection Agent**

Not a search engine. Not a churn score. Asktra explains *why* the system behaves the way it does, what contradicts the docs, and what to fix — using Gemini reasoning across Slack, Git, Jira, and documentation.

*"Asktra doesn't predict churn — it decides what is true by reconciling developer intent (Slack), implementation (Git), and stated docs, and flags Truth Gaps."*

---

## What is built (single flow)

**Scenario:** Docs say *"30s timeout"* but production fails. The dev who changed it left. Leadership needs to know:

1. **Why** the system behaves this way (causal explanation)
2. **What** contradicts the documentation (Truth Gaps, contradictions)
3. **What to do** (fix steps, verification, optional PR-ready docs)

**System components:**

### 1. Input layer

| Input | Description |
|-------|-------------|
| **Slack** | Developer intent, discussions (preloaded or paste) |
| **Git** | Commits, tags — technical reality |
| **Jira** | Tickets, timelines |
| **Docs** | Stated behavior (README, internal docs) |
| **Releases** | Version boundaries, release notes |
| **Dataset overrides** | Frontend-edited sources (paste JSON/Markdown) |
| **Prior context** | Living knowledge / Hard Truths from the session |
| **Image** | Optional screenshot or dashboard (multimodal) |

### 2. Gemini = the brain (pipeline)

| Agent | Role | Gemini use |
|-------|------|------------|
| **Version Inferrer** | Infer which release boundary the question belongs to (e.g. v2.4) | `thinkingLevel: HIGH` (optional), structured JSON (version, evidence, confidence) |
| **Causal Reasoner** | Root cause, contradictions, risk, fix steps, sources, reasoning trace, Truth Gaps | Structured JSON, prior context (Hard Truths), multimodal |
| **Self-Correction** | When contradictions exist: verify against sources before final answer | Structured JSON (verification_steps) |
| **Emit Docs** | PR-ready Markdown reflecting *true* behavior | No auto-merge; human review |
| **Reconciliation Patch** | PR body or patch for a finding (e.g. doc drift → GitHub/Confluence) | Action endpoint |
| **Reconciliation Bundle** | post_mortem (Markdown), pr_diff (Markdown), slack_summary (text) | JSON output for team handoff |

**Gemini integration:**

- **Causal reasoning, not generation:** Causal Reasoner fuses Slack, Git, Jira, and docs to explain *why*.
- **Temporal version isolation:** Version Inferrer reasons only within the inferred release boundary.
- **Truth Gap detection:** Contradictions between intent (Slack), implementation (Git), and docs are flagged; Hard Truths correct the user when they contradict established findings.
- **Structured outputs:** `response_mime_type: application/json` + schema for UI-ready data.
- **Thought signatures:** `GEMINI_THINKING_LEVEL=HIGH` for reasoning visibility (Phase 0 / Phase 7).

### 3. Output UI

- **Inferred version** + evidence + confidence
- **"Why this system behaves this way"** (root cause, contradictions, risk)
- **Fix steps** + verification (e.g. curl or test)
- **Reasoning trace** + source citations (click to see raw Slack/Git/Jira/Docs)
- **Truth Gaps** + Hard Truths (Asktra corrects the user from its own investigation)
- **Emitted docs** (Sync Reality) + **Reconciliation Patch** (PR body) + **Reconciliation Bundle** (post_mortem, pr_diff, slack_summary)
- **Thought signatures** (Gemini reasoning per step when thinking level HIGH)

---

## Audit readiness (Compliance & CTO/Legal)

**Asktra isn't just for debugging — it's for Compliance.**

Every finding is grounded in a **specific source** (Slack, Git, Jira, Docs). **Click any source** (e.g. "Slack 2025-09-13") to open a modal with the exact raw JSON/text — proof of retrieval and no hallucination. Auditors can trace from developer intent to documentation. That shifts the project from a "dev tool" to a **business necessity**.

---

## Run locally

### Clone and install

```bash
git clone <repo>
cd Asktra
```

### Backend

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set:

```bash
GEMINI_API_KEY=your_key_here
# Optional: GEMINI_THINKING_LEVEL=HIGH  (Phase 0 / Phase 7 extended reasoning)
# Optional: GEMINI_MODEL=gemini-3-pro-preview  (deeper reasoning)
```

Start the API:

```bash
cd backend
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000**.

**Quick test:** Ask *"Why does auth timeout fail?"* — Asktra infers version (e.g. v2.4), shows contradiction (docs 30s vs code 90s), reasoning trace, and sources. Use **Findings** and a follow-up like *"Actually, I think the timeout is 30s"* to see **Hard Truths**: Asktra corrects the user from its own investigation.

---

## Build for production (e.g. Vercel)

- **Backend:** Vercel looks for the FastAPI app in `api/main.py` (see repo). Set `GEMINI_API_KEY` (and optional `GEMINI_THINKING_LEVEL`, `GEMINI_MODEL`) in project environment variables.
- **Frontend:** `cd frontend && npm run build && npm run preview` (or deploy the `dist` output to any static host).

---

## Tech stack

- **Backend:** Python 3, FastAPI, `google-genai` (Gemini 3: `gemini-3-flash-preview` / `gemini-3-pro-preview`)
- **Frontend:** React 18, Vite
- **Data:** Preloaded dataset (`backend/dataset/`: Slack, Git, Jira, docs, releases) + optional overrides and prior context

Deploy on **Vercel** (FastAPI serverless) or run backend with uvicorn behind any reverse proxy.

---

## API overview

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/ask-stream` | Causal reasoning with streaming steps; `prior_context` (Hard Truths), optional image |
| POST | `/ask` | Same, non-streaming |
| POST | `/emit-docs` | Emit PR-ready Markdown from causal analysis (no auto-merge) |
| POST | `/emit-reconciliation-patch` | Generate PR body or patch for a finding (e.g. doc drift → GitHub/Confluence) |
| POST | `/reconciliation-bundle` | post_mortem + pr_diff + slack_summary (uses `GEMINI_BUNDLE_API_KEY` if set) |
| GET | `/dataset` | Current Slack/Git/Jira/Docs/Releases for inspection or override |
| GET | `/health` | Health check |

**Example: Autonomous documentation correction**

```bash
curl -X POST "http://localhost:8000/emit-reconciliation-patch" \
  -H "Content-Type: application/json" \
  -d '{"finding_id": "AUTH_TIMEOUT_CONFLICT", "target": "GitHub", "action": "generate_pr"}'
```

Returns a **PR body** (or patch description) — ready for human review. No auto-merge.

---

## Environment variables

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Required for backend. |
| `GEMINI_MODEL` | Optional. Default: `gemini-3-flash-preview`. Use `gemini-3-pro-preview` for deep reasoning. |
| `GEMINI_THINKING_LEVEL` | Optional. Set to `HIGH` for Phase 0 (Semantic Intent Mapping) and Phase 7 (Causal Reconciliation). |
| `GEMINI_BUNDLE_API_KEY` | Optional. Separate key for Reconciliation Bundle (e.g. Gemini 3). |
| `VITE_API_URL` | Optional. Frontend API base. Default: same origin (Vite proxy). |

---

## Architecture diagram

See **[ARCHITECTURE.md](./ARCHITECTURE.md)** for high-level flow, input layer, Gemini pipeline (Version Inferrer → Causal Reasoner → Self-Correction / Emit Docs / Reconciliation Patch / Bundle), output UI, and Gemini usage per component.

---

## Demo flow (under 3 minutes)

1. **Pain (0:00–0:30):** "Docs say this bug is impossible. The dev who wrote this left."
2. **Input (0:30–1:00):** Show preloaded Slack, Git, README, Jira — no version dropdown.
3. **Win (1:00–2:20):** Ask *"Analyze the v2.4 timeout issue."* Show inferred version, evidence, **Truth Gap** (30s vs 90s), fix steps, reasoning trace. Then the **trap**: *"Actually, I think the timeout is 30s. Why am I seeing errors?"* — Asktra corrects the user: *"We established earlier that Commit 8a2f set it to 90s…"* (Hard Truths).
4. **Close (2:20–3:00):** Click **Sync Reality**; show emitted Markdown. Optional: call `/emit-reconciliation-patch` to show the agent generating a PR for the finding.

---

## Project structure

```
Asktra/
├── api/
│   └── main.py              # Vercel entrypoint (exports backend app)
├── backend/
│   ├── main.py              # FastAPI: /ask, /ask-stream, /emit-docs, /emit-reconciliation-patch, /reconciliation-bundle, /dataset
│   ├── gemini_client.py     # Version inference, causal reasoning, emit_docs, emit_reconciliation_patch, reconciliation_bundle
│   ├── source_resolver.py   # Resolve source details for UI
│   ├── dataset/             # slack.json, git.json, jira.json, docs.md, releases.md
│   └── prompts/             # infer_version, causal_reasoning, emit_docs, emit_reconciliation_patch, verify_contradiction, reconciliation_bundle
├── frontend/
│   └── src/
│       ├── App.jsx
│       └── components/      # QueryBox, AnswerPanel, ReasoningTrace, FindingsSidebar, SourcePanel, DocDiff, ThinkingPanel, ExperimentPanel
├── requirements.txt
├── README.md
└── ARCHITECTURE.md
```

---

## One-liner

**Asktra doesn't answer questions — it protects systems by remembering *why* the code exists, and by refusing to trust the doc when Slack and Git tell a different story.**

---

## License

MIT.
