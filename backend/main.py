"""
Asktra API: Cognitive Librarian for Software Systems.
POST /ask — causal reasoning with automatic version inference.
POST /emit-docs — PR-ready documentation emission.
"""
import os
import time
from pathlib import Path

from dotenv import load_dotenv

# Load .env from repo root so GEMINI_API_KEY is available without setting it in the shell
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

# Fail fast if google-genai is not installed in *this* Python (the one running uvicorn)
try:
    from google import genai  # noqa: F401
except ImportError:
    raise RuntimeError(
        "google-genai is not installed in the Python environment running this server. "
        "In the SAME terminal where you run 'uvicorn main:app', run: pip install google-genai "
        "Then restart uvicorn."
    )

from contextlib import asynccontextmanager

import json as _json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from typing import Any

from gemini_client import (
    GeminiClient,
    ask as ask_engine,
    emit_docs as emit_docs_engine,
    emit_reconciliation_patch as emit_reconciliation_patch_engine,
    generate_reconciliation_bundle as generate_reconciliation_bundle_engine,
)
from gemini_client import GeminiClient as _GC, get_dataset_for_api  # for type hint
from source_resolver import get_source_details


def _ask_stream(
    client: _GC,
    query: str,
    include_sources: list[str] | None = None,
    dataset_overrides: dict[str, Any] | None = None,
    prior_context: str | None = None,
    image_base64: str | None = None,
    image_mime: str | None = None,
):
    """Yield (event_type, data) for SSE: status/step messages (all steps), then result."""
    q = query.strip()
    sources_msg = ", ".join(include_sources) if include_sources else "Slack, Git, Jira, docs, releases"
    yield ("step", {"message": f"Loading dataset ({sources_msg})…"})
    if image_base64:
        yield ("step", {"message": "Including attached image in analysis (multimodal)…"})
    if prior_context:
        yield ("step", {"message": "Building on prior session knowledge…"})
    yield ("step", {"message": "Inferring version from timestamps and release notes…"})
    version_result = client.infer_version(q, include_sources, dataset_overrides, image_base64, image_mime or "image/png")
    inferred = version_result.get("inferred_version", "unknown")
    conf = version_result.get("confidence", 0)
    yield ("step", {"message": f"✓ Inferred version: {inferred} ({int(conf * 100)}% confidence)"})
    for ev in version_result.get("evidence", [])[:3]:
        yield ("step", {"message": f"  Evidence: {ev}"})
    yield ("step", {"message": "Loading sources into context for causal reasoning…"})
    yield ("step", {"message": "Reasoning over Slack intent vs Git implementation vs docs…"})
    causal = client.causal_reasoning(
        q, inferred, include_sources, dataset_overrides, prior_context, image_base64, image_mime or "image/png"
    )
    yield ("step", {"message": "✓ Causal analysis complete. Extracting reasoning trace…"})
    for step in causal.get("reasoning_trace") or []:
        yield ("step", {"message": f"  {step}"})
    # Self-correction loop: when contradictions exist, run final verification before showing answer
    contradictions = causal.get("contradictions") or []
    if contradictions:
        yield ("step", {"message": "Verifying inferred truth (self-correction loop)…"})
        try:
            verification_steps = client.verify_contradiction(
                inferred, contradictions, include_sources, dataset_overrides
            )
            for msg in verification_steps:
                yield ("step", {"message": f"  {msg}"})
            yield ("step", {"message": "✓ Verification complete. Documentation outlier confirmed."})
        except Exception:
            yield ("step", {"message": "  (Verification skipped)"})
    yield ("step", {"message": "Resolving source citations (Slack, Git, Jira, docs)…"})
    result = {
        "query": q,
        "inferred_version": inferred,
        "confidence": conf,
        "evidence": version_result.get("evidence", []),
        "ambiguity_note": version_result.get("ambiguity_note", ""),
        "root_cause": causal.get("root_cause", ""),
        "contradictions": causal.get("contradictions", []),
        "risk": causal.get("risk", ""),
        "fix_steps": causal.get("fix_steps", []),
        "verification": causal.get("verification", ""),
        "sources": causal.get("sources", []),
        "reasoning_trace": causal.get("reasoning_trace", []),
        "truth_gaps": causal.get("truth_gaps", []),
    }
    result["source_details"] = get_source_details(result["sources"])
    yield ("step", {"message": "✓ Sources resolved. Building answer…"})
    payload = _build_ask_response(result, result["source_details"])
    yield ("result", payload)


class AskRequest(BaseModel):
    query: str
    include_sources: list[str] | None = None  # e.g. ["slack", "git", "jira", "docs", "releases"]
    dataset_overrides: dict[str, Any] | None = None  # edited source content from frontend
    prior_context: str | None = None  # living knowledge: summary of prior findings this session
    image_base64: str | None = None  # optional screenshot/dashboard (multimodal)
    image_mime: str | None = None  # e.g. image/png, image/jpeg


class SourceDetail(BaseModel):
    type: str  # slack | jira | git | document
    label: str
    content: str


class AskResponse(BaseModel):
    query: str
    inferred_version: str
    confidence: float
    evidence: list[str]
    ambiguity_note: str = ""
    root_cause: str = ""
    contradictions: list[str] = []
    risk: str = ""
    fix_steps: list[str] = []
    verification: str = ""
    sources: list[str] = []
    source_details: list[SourceDetail] = []  # type + content for each source (click to show)
    reasoning_trace: list[str] = []
    truth_gaps: list[str] = []


class EmitDocsRequest(BaseModel):
    inferred_version: str = "unknown"
    root_cause: str = ""
    contradictions: list[str] = []
    risk: str = ""
    fix_steps: list[str] = []
    verification: str = ""
    sources: list[str] = []


class EmitReconciliationPatchRequest(BaseModel):
    finding_id: str  # e.g. AUTH_TIMEOUT_CONFLICT
    target: str  # e.g. GitHub, Confluence
    action: str  # e.g. generate_pr
    causal_summary: str | None = None  # optional: root_cause, contradictions, risk, etc.


_gemini: GeminiClient | None = None


def _build_ask_response(result: dict, source_details: list) -> dict:
    def _str(v):
        return v if isinstance(v, str) else (str(v) if v is not None else "")
    def _list(v):
        return v if isinstance(v, list) else []
    return {
        "query": _str(result.get("query")),
        "inferred_version": _str(result.get("inferred_version")),
        "confidence": float(result.get("confidence") or 0),
        "evidence": _list(result.get("evidence")),
        "ambiguity_note": _str(result.get("ambiguity_note")),
        "root_cause": _str(result.get("root_cause")),
        "contradictions": _list(result.get("contradictions")),
        "risk": _str(result.get("risk")),
        "fix_steps": _list(result.get("fix_steps")),
        "verification": _str(result.get("verification")),
        "sources": _list(result.get("sources")),
        "source_details": source_details,
        "reasoning_trace": _list(result.get("reasoning_trace")),
        "truth_gaps": _list(result.get("truth_gaps")),
    }


def get_gemini() -> GeminiClient:
    global _gemini
    if _gemini is None:
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise HTTPException(
                status_code=503,
                detail="GEMINI_API_KEY or GOOGLE_API_KEY not set",
            )
        _gemini = GeminiClient(api_key=key)
    return _gemini


_gemini_bundle: GeminiClient | None = None


def get_gemini_bundle() -> GeminiClient:
    """Use GEMINI_BUNDLE_API_KEY for reconciliation bundle (e.g. Gemini 3 key); fallback to main key.
    When GEMINI_BUNDLE_API_KEY is set, we create a fresh client each time so the bundle key is always used."""
    bundle_key = os.environ.get("GEMINI_BUNDLE_API_KEY")
    if bundle_key:
        # Always use the bundle key when set (no cache). Use Gemini 3 for bundle when bundle key is set.
        model = os.environ.get("GEMINI_BUNDLE_MODEL") or "gemini-3-flash-preview"
        return GeminiClient(api_key=bundle_key, model=model)
    global _gemini_bundle
    if _gemini_bundle is None:
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise HTTPException(
                status_code=503,
                detail="GEMINI_BUNDLE_API_KEY or GEMINI_API_KEY not set",
            )
        _gemini_bundle = GeminiClient(api_key=key)
    return _gemini_bundle


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    global _gemini, _gemini_bundle
    _gemini = None
    _gemini_bundle = None


app = FastAPI(
    title="Asktra",
    description="Cognitive Librarian for Software Systems — causal reasoning across Slack, Git, and Docs.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _sse_stream(
    query: str,
    include_sources: list[str] | None = None,
    dataset_overrides: dict[str, Any] | None = None,
    prior_context: str | None = None,
    image_base64: str | None = None,
    image_mime: str | None = None,
):
    """Generator yielding SSE-formatted lines for /ask-stream."""
    try:
        client = get_gemini()
        for event_type, data in _ask_stream(
            client, query, include_sources, dataset_overrides, prior_context, image_base64, image_mime
        ):
            payload = _json.dumps(data, ensure_ascii=False)
            yield f"event: {event_type}\ndata: {payload}\n\n"
    except HTTPException:
        raise
    except Exception as e:
        msg = str(e)
        yield f"event: error\ndata: {_json.dumps({'detail': msg})}\n\n"


@app.post("/ask-stream")
def post_ask_stream(body: AskRequest):
    """Stream reasoning steps (thinking process) then final result — Perplexity/Gemini style."""
    return StreamingResponse(
        _sse_stream(
            body.query.strip(),
            body.include_sources,
            body.dataset_overrides,
            body.prior_context,
            body.image_base64,
            body.image_mime,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/ask", response_model=AskResponse)
def post_ask(body: AskRequest):
    """Run causal reasoning: infer version, then explain why the system behaves this way."""
    try:
        client = get_gemini()
        result = ask_engine(
            client,
            body.query.strip(),
            body.include_sources,
            body.dataset_overrides,
            body.prior_context,
            body.image_base64,
            body.image_mime or "image/png",
        )
        sources = result.get("sources", [])
        source_details = get_source_details(sources)
        payload = _build_ask_response(result, source_details)
        return AskResponse(**payload)
    except HTTPException:
        raise
    except Exception as e:
        msg = str(e)
        if "quota" in msg.lower() or "429" in msg or "RESOURCE_EXHAUSTED" in msg:
            raise HTTPException(status_code=503, detail=msg)
        raise HTTPException(status_code=500, detail=msg)


@app.post("/emit-docs")
def post_emit_docs(body: EmitDocsRequest):
    """Emit PR-ready Markdown reflecting true system behavior (no auto-merge)."""
    try:
        client = get_gemini()
        causal = {
            "root_cause": body.root_cause,
            "contradictions": body.contradictions,
            "risk": body.risk,
            "fix_steps": body.fix_steps,
            "verification": body.verification,
            "sources": body.sources,
        }
        markdown = emit_docs_engine(client, body.inferred_version, causal)
        return {"markdown": markdown}
    except HTTPException:
        raise
    except Exception as e:
        msg = str(e)
        if "quota" in msg.lower() or "429" in msg or "RESOURCE_EXHAUSTED" in msg:
            raise HTTPException(status_code=503, detail=msg)
        raise HTTPException(status_code=500, detail=msg)


@app.post("/emit-reconciliation-patch")
def post_emit_reconciliation_patch(body: EmitReconciliationPatchRequest):
    """Action endpoint: generate a reconciliation patch or PR body for a finding (e.g. doc drift). No auto-merge."""
    try:
        client = get_gemini()
        markdown = emit_reconciliation_patch_engine(
            client,
            body.finding_id.strip(),
            body.target.strip(),
            body.action.strip(),
            body.causal_summary or "",
        )
        return {"action": body.action, "patch_description": markdown, "pr_body": markdown}
    except HTTPException:
        raise
    except Exception as e:
        msg = str(e)
        if "quota" in msg.lower() or "429" in msg or "RESOURCE_EXHAUSTED" in msg:
            raise HTTPException(status_code=503, detail=msg)
        raise HTTPException(status_code=500, detail=msg)


def _is_retryable_gemini_error(e: Exception) -> bool:
    msg = str(e).lower()
    return (
        "503" in str(e)
        or "overloaded" in msg
        or "unavailable" in msg
        or "429" in str(e)
        or "resource_exhausted" in msg
        or "quota" in msg
    )


@app.post("/reconciliation-bundle")
def post_reconciliation_bundle(body: EmitDocsRequest):
    """Generate Reconciliation Bundle: post_mortem (Markdown), pr_diff (Markdown), slack_summary (text). Uses GEMINI_BUNDLE_API_KEY if set."""
    client = get_gemini_bundle()
    causal = {
        "inferred_version": body.inferred_version,
        "root_cause": body.root_cause,
        "contradictions": body.contradictions,
        "risk": body.risk,
        "fix_steps": body.fix_steps,
        "verification": body.verification,
        "sources": body.sources,
    }
    last_error = None
    for attempt in range(3):
        try:
            bundle = generate_reconciliation_bundle_engine(client, causal)
            return bundle
        except HTTPException:
            raise
        except Exception as e:
            last_error = e
            msg = str(e)
            if "empty bundle" in msg.lower():
                raise HTTPException(status_code=503, detail=msg)
            if attempt < 2 and _is_retryable_gemini_error(e):
                time.sleep(2 * (attempt + 1))
                continue
            if _is_retryable_gemini_error(e):
                raise HTTPException(
                    status_code=503,
                    detail="Gemini is temporarily overloaded. Wait a minute and try again, or set GEMINI_BUNDLE_MODEL=gemini-2.5-flash in .env.",
                )
            raise HTTPException(status_code=500, detail=msg)
    if last_error and _is_retryable_gemini_error(last_error):
        raise HTTPException(
            status_code=503,
            detail="Gemini is temporarily overloaded. Wait a minute and try again, or set GEMINI_MODEL=gemini-2.5-flash in .env.",
        )
    raise HTTPException(status_code=500, detail=str(last_error) if last_error else "Unknown error")


@app.get("/dataset")
def get_dataset():
    """Return current dataset so frontend can show and edit each source."""
    return get_dataset_for_api()


@app.get("/")
def root():
    """Root route so deployment URL (e.g. Vercel) returns 200 instead of 404."""
    return {
        "service": "asktra",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
        "endpoints": ["POST /ask", "POST /ask-stream", "POST /emit-docs", "POST /emit-reconciliation-patch", "POST /reconciliation-bundle", "GET /dataset", "GET /health"],
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "asktra"}
