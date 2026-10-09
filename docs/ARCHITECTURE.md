# Research Lab

**Multi-agent system that finds, reads and vets teaching material, then drafts a lecture and an assignment.**

A teacher enters a topic; nine agents search ten sources,
download the openly available documents, extract their text, score every source, write a lecture and a
learning assignment from the approved sources only, and have a separate agent review the result. Every
agent step, tool call and model call is logged and shown live in the web interface. Why a team of agents
and not one: see the project report (`Research_Lab_report.docx`) and section 2.

```
POST /api/v1/research-lab/runs/ {"topic": "Python basics: Loops", "education_level": "UNDERGRADUATE", ...}

 BOSS (script, no LLM: plan, order, limits, cancel)
   │
   ├──► WEB RESEARCH ───────┐        Bright Data · Wikipedia · YouTube
   └──► ACADEMIC RESEARCH ──┤        OpenAlex · CORE · Semantic Scholar · Crossref · arXiv ·
                            │        Google Books · Open Library
                            ▼
                    DOCUMENT RETRIEVAL      metadata dedup → download originals (HTTP, SSRF-safe)
                            ▼
                    DOCUMENT ANALYSIS       extract text (PDF/PPTX/DOCX/HTML/TXT) → content dedup
                            ▼
                    SOURCE VALIDATOR (LLM)  scores sources in batches of 4 → accept / review / reject
                            ▼
              ┌── LECTURE BUILDER (LLM) ──┐
              └── ASSIGNMENT GENERATOR (LLM) ──┤   built only from approved sources
                                           ▼
                    FINAL REVIEWER (LLM, independent)  ──► needs_revision → back to the author (≤ 2×)
                            │ approved
                            ▼
                COMPLETED / PARTIAL / FAILED / CANCELLED
```

State lives in the database — SQLite (`ResearchRun`, sources, documents + files, lectures, assignment) and is
mirrored as a persisted event stream (`ResearchEvent`) pushed to the browser over WebSocket.
A full architecture diagram is in `architecture.png`.

---

## 1. How it runs

```
backend/
  core/          settings, URLs, ASGI (HTTP + WebSocket), shared helpers
  accounts/      e-mail login, roles (ADMIN / TEACHER / STUDENT), JWT
  llm/           LLM providers (OpenAI, Anthropic, local OpenAI-compatible), prompts, call journal
  research_lab/  the module: agents, search providers, services, API, WebSocket consumer
```

* **No external services.** SQLite is the database; a run executes in a background thread of the Django
  process (`research_lab/tasks.py`); live events go through Channels' in-memory layer of that same
  process. Run a single server process (`python manage.py runserver`).
* A run that was still active when the server stopped is marked `FAILED` on the next start (the thread
  died with the process).
* Turning the module off is one setting, `RESEARCH_LAB_ENABLED=false`: every `research_lab` endpoint
  403s except `/config/`, which still answers so the frontend can show that the module is off.

If Bright Data, OpenAlex, Semantic Scholar, arXiv, Crossref, Google Books, or the LLM provider are
down — individually or all at once — a run still completes, ending in `PARTIAL` rather than
crashing (see §6).

---

## 2. The nine agents

| # | Agent | Role | Inputs → outputs | Tools | LLM? |
|---|---|---|---|---|---|
| 1 | **Boss** | plans and routes; does no domain work | run parameters → plan, hand-offs, final status | none (script) | No |
| 2 | **Web Research** | web / university / video search | topic → candidates | Bright Data, Wikipedia, YouTube | No |
| 3 | **Academic Research** | papers and books | topic → candidates (DOI, authors, PDF link, sometimes full text) | OpenAlex, CORE, Semantic Scholar, Crossref, arXiv, Google Books, Open Library | No |
| 4 | **Document Retrieval** | download originals | candidates → sources + stored files | HTTP downloader | No |
| 5 | **Document Analysis** | read documents | stored files → text, content hash, duplicate flags | document parsers | No |
| 6 | **Source Validator** | decide what is usable | sources (relevant passages) → scores 0-100, accept / review / reject | LLM (4 sources per request) | Yes |
| 7 | **Lecture Builder** | write the lecture | approved sources → lecture JSON | LLM | Yes |
| 8 | **Assignment Generator** | write the assignment | approved sources (+ lecture) → questions, rubric, key | LLM | Yes |
| 9 | **Final Reviewer** | independent check | lecture / assignment + sources → verdict, score, issues | LLM | Yes |

Each agent's completion criterion, and the reasons behind every design decision, are in the report
(`Research_Lab_report.docx`, sections 4 and 5). No agent can crash the whole run: the Boss wraps
every step in `try/except`, and a crash degrades the run to `PARTIAL` instead of `FAILED`.

**Why the Boss doesn't call an LLM.** The pipeline's shape (search → download → read → validate →
write ↔ review) is fixed by the feature itself — an LLM decision for "what runs next" would add
latency, cost and a new failure mode for no benefit. A structured `BossDecision` is still logged on
every Boss step (`research_lab/schemas.py`).

**Why download and read are separate agents.** One agent doing both made 36% of all calls (69% in
search-only mode). Splitting by role gives two agents of ~17% each, and the hand-off is explicit state:
the original file stored on `ResearchDocument.file`, status `FETCHED` → `EXTRACTED`.

**Why the Validator scores in batches.** One request per source made it the busiest agent (up to 41%
of all calls). Four sources per request (`RESEARCH_LAB_VALIDATION_BATCH`) cut its share to ~17%; a
source the model skips, or an unreadable reply, is scored by a single-source request instead.

**Why the writers, the Validator and the Reviewer are separate.** Neither agent reviews its own output.

**Long documents are never sent whole.** `services/passages.py` ranks a document's passages against the
topic with BM25 (no model) and the prompt gets only the best ones within `RESEARCH_LAB_CONTEXT_CHARS`
(30 000) in total; the Validator gets `RESEARCH_LAB_VALIDATION_EXCERPT_CHARS` (6 000) per source.

**Model failures.** Agent calls get at least `RESEARCH_LAB_MIN_OUTPUT_TOKENS` (8192) of output room (a
reply cut off at the limit is requested again with twice the room), and an unreachable model falls back
to the other tier (local ↔ cloud).

## 2a. Load report (the "no agent above 40%" rule)

Load = (LLM calls + tool calls of an agent) / (all LLM calls + all tool calls of the run). Boss makes
neither kind of call. Skipped tool calls (source disabled / no key) are not counted.

```bash
python manage.py research_report <run_id> --markdown report.md --json report.json
# or: GET /api/v1/research-lab/runs/<id>/report/?as=markdown   (also the "Load report" button in Metrics)
```

Reference run (`run-18-report.md`): topic "Python basics: Loops", Cloud mode, lecture + assignment —
9 LLM calls, 21 tool calls, busiest agent Academic Research at 20.0%. Searching and download/extract
calls are what dominate in the search-only mode (run 19: Document Retrieval 49%), which is why the
report treats a full run as the typical scenario; the search-only mode can be switched off in
Settings → Research Lab.

---

## 3. Search providers

`research_lab/providers/search/` — one file per provider, all implementing `SearchProvider.search(query, *, limit) -> list[SourceCandidate]` and normalising to the same `SourceCandidate` dataclass (`research_lab/schemas.py`).

| Provider | File | Needs a key? | Notes |
|---|---|---|---|
| **Bright Data** (web/SERP) | `brightdata.py` | Yes — `BRIGHTDATA_API_TOKEN` + `BRIGHTDATA_SERP_ZONE` | Also used as the Browser/Unlocker *fetch* fallback (not a search provider there) |
| **OpenAlex** | `openalex.py` | No (optional `OPENALEX_API_KEY`/`OPENALEX_MAILTO` only raise rate limits) | Reconstructs the abstract from OpenAlex's word-position index |
| **Semantic Scholar** | `semantic_scholar.py` | No (optional `SEMANTIC_SCHOLAR_API_KEY`) | Keyless tier is tightly rate-limited — expect occasional `429`s, which are logged and skipped |
| **Crossref** | `crossref.py` | No (optional `CROSSREF_MAILTO` for the faster "polite pool") | Also exposes `lookup_doi()` for one-off DOI metadata verification |
| **arXiv** | `arxiv.py` | No | Parses the Atom XML with the stdlib — no new XML dependency |
| **Google Books** | `google_books.py` | No (optional `GOOGLE_BOOKS_API_KEY` raises the quota) | |

> **Bright Data:** the SERP is requested with `format: "raw"` and parsed leniently (plain JSON, JSON wrapped
> in a `body` string, or an HTML results page) — verified against a live account. Wikipedia needs a
> descriptive User-Agent (set from `RESEARCH_LAB_FETCH_USER_AGENT`). CORE needs `CORE_API_KEY`, YouTube
> needs `YOUTUBE_API_KEY`; a source without its key is skipped, shown as "API key missing" in Settings.
> The full list (OpenAlex, CORE, Semantic Scholar, Crossref, arXiv, Google Books, Open Library, Wikipedia,
> YouTube, Bright Data) can be switched on and off individually in Settings → Research Lab.

---

## 4. Document Retrieval and Document Analysis: fetch, extract, deduplicate

```
SourceCandidate list (web + academic)
        │
        ▼
dedup (phase 1 — metadata: DOI, ISBN, normalised URL, fuzzy title+author+year)
        │  cuts obvious duplicates before spending any fetch/LLM budget
        ▼
cap at RESEARCH_LAB_MAX_DOCUMENTS, persist as ResearchSource rows
        │
        ▼
Document Retrieval:  download the original → store it (ResearchDocument.file, status FETCHED)
Document Analysis:   read the stored file → extract text → dedup (phase 2 — content hash)
```

**Fetching** (`services/fetcher.py`) is SSRF-safe: every hostname is resolved and every resolved IP
is checked against private/loopback/link-local/reserved ranges (including on each redirect hop — a
hostname that resolves differently on a later request is re-checked, not trusted from the first
lookup). On failure it escalates:

```
plain HTTP GET
  → (if blocked, or the response looks too short to be real content) Playwright, if installed
  → (if that also fails/unavailable) Bright Data Browser/Unlocker, if configured
  → otherwise: this one source fails, logged, the run continues
```

Playwright is **not** a hard dependency — it is optional (`backend/requirements-optional.txt`, imported
lazily).

**Extraction** (`services/extraction.py`) uses `services/extractors/` (pypdf, python-docx,
python-pptx) for PDF/DOCX/PPTX. HTML uses BeautifulSoup to strip navigation/headers/footers/scripts/
cookie banners. No OCR: a scanned PDF page without a text layer comes back empty.

**Deduplication** (`services/dedup.py`) phase 2 hashes the *extracted text* (SHA-256) — this is
what catches a paper reachable at both its publisher page and a university mirror, which phase 1's
metadata check cannot.

---

## 5. LLM calls

Agents call models through the `llm` app — providers for OpenAI, Anthropic and any local
OpenAI-compatible server (Ollama, vLLM, LM Studio), with `generation.generate_answer` recording
tokens, latency and cost on a `GenerationRun` row. `research_lab/services/llm_router.py` adds one
thing on top: picking *which* `LLMConfiguration` an agent should use, from `ResearchRun.llm_mode`:

| Mode | Source Validator | Assignment Generator / Final Reviewer |
|---|---|---|
| `LOCAL` | a local (Ollama/vLLM/…) configuration | same |
| `CLOUD` | an OpenAI/Anthropic configuration | same |
| `HYBRID` | **local** (bulk, cheap scoring) | **cloud** (low-volume, quality-sensitive writing/review) |
| `CUSTOM` | `ResearchRun.agent_model_overrides["SOURCE_VALIDATOR"]` → an `LLMConfiguration` id | same, per agent name |

Every mode falls back to the default `LLMConfiguration` if nothing matches, so a run
never hard-fails just because a preferred tier has no active configuration.

`services/llm_json.py` wraps every LLM call with one retry (`services/resilience.retry_with_backoff`,
on `core.exceptions.ExternalServiceError`) and defensively parses the JSON reply — a model that
returns prose instead of JSON, or wraps it in ` ```json ` fences, degrades that one call rather than
crashing the agent.

---

## 6. Fault tolerance

- **Per-call**: one provider's/one fetch's failure is caught, logged as a `ToolExecution`, and the
  loop continues with the next query/provider/source.
- **Per-agent**: `agents/boss.py` wraps every agent call in `try/except`; an unexpected crash sets
  `degraded = True` and a short note on `ResearchRun.error_message`, then the Boss moves on with
  whatever that stage *did* produce (possibly nothing).
- **Budgets** (`services/resilience.Budget`): a step counter and a wall-clock deadline
  (`RESEARCH_LAB_MAX_RUNTIME_SECONDS`), checked between every stage — including inside Document
  Analysis's per-document loop. Exceeding either ends the run as `PARTIAL`, not stuck or crashed.
- **Cancellation**: cooperative — `POST /runs/{id}/cancel/` sets `cancel_requested`; the same
  per-stage checkpoint that enforces the budget also checks this flag.
- **Revision loop cap**: `RESEARCH_LAB_MAX_REVISION_CYCLES` (default 2) — the Reviewer can send the
  Generator back at most this many times before the assignment is kept as-is, flagged
  `REVISION_LIMIT_REACHED`, and the run still completes as `PARTIAL`.
- **Never stuck**: `tasks.run_research_task` → `agents.boss.run_workflow` always leaves the run in a
  terminal status (`COMPLETED` / `PARTIAL` / `FAILED` / `CANCELLED`) before returning, even on a
  crash it didn't anticipate.

---

## 7. Data model

| Model | What |
|---|---|
| `ResearchRun` | One request: topic, scope, assignment/LLM-mode settings, status, timing |
| `ResearchSource` | One normalised candidate — found-by-provider fields **and** the Validator's scores/decision (a source is validated at most once per run, so one row covers both) |
| `ResearchDocument` | The fetched + extracted content of one source |
| `AgentExecution` | Append-only: one step of one agent (links to the `GenerationRun` it made, if one) |
| `ToolExecution` | Append-only: one external call (a provider search, a fetch, a browser fallback) |
| `Assignment` | The generated assignment + the Reviewer's verdict |

**Load distribution.** No single agent is meant to dominate a run's LLM/tool calls — in practice
the Boss makes zero calls and the Source Validator's N calls (one per analyzed source) are the
largest share by design. `/metrics/`'s `max_agent_load_pct` reports the actual split; this is
surfaced as a metric, not enforced as a hard runtime constraint (an artificial cap would just make
runs with many sources fail for no real reason).

---

## 8. API

```
GET    /api/v1/research-lab/config/               any authenticated user — {enabled, limits, ...}
POST   /api/v1/research-lab/runs/                  create + queue a run                    teacher/admin
GET    /api/v1/research-lab/runs/                  your own runs (admins: everyone's)
GET    /api/v1/research-lab/runs/{id}/
POST   /api/v1/research-lab/runs/{id}/cancel/       cooperative cancellation
GET    /api/v1/research-lab/runs/{id}/sources/
GET    /api/v1/research-lab/runs/{id}/agents/       AgentExecution log
GET    /api/v1/research-lab/runs/{id}/tools/        ToolExecution log
GET    /api/v1/research-lab/runs/{id}/assignment/   404 if none was generated (yet)
GET    /api/v1/research-lab/runs/{id}/metrics/
```

A run is visible only to its owner (or an admin) — `selectors.runs_for_user`; every nested
sub-resource filters through the same selector, so a 404 on `/runs/{id}/` also means a 404 on every
`/runs/{id}/<anything>/`.

---

## 9. Environment variables

```env
RESEARCH_LAB_ENABLED=true

RESEARCH_LAB_MAX_SEARCH_QUERIES=4          # Bright Data queries per run (each is one paid request)
RESEARCH_LAB_MAX_RESULTS_PER_QUERY=10
RESEARCH_LAB_MAX_DOCUMENTS=20
RESEARCH_LAB_MAX_RUNTIME_SECONDS=1800
RESEARCH_LAB_MAX_REVISION_CYCLES=2
RESEARCH_LAB_MAX_DOWNLOAD_MB=20
RESEARCH_LAB_FETCH_TIMEOUT_SECONDS=20
RESEARCH_LAB_FETCH_USER_AGENT=ResearchLab/1.0
RESEARCH_LAB_FETCH_PER_PROVIDER=5          # download attempts per source per run
RESEARCH_LAB_VALIDATION_BATCH=4            # sources judged per validator request
RESEARCH_LAB_VALIDATION_EXCERPT_CHARS=6000 # passages of a source shown to the validator
RESEARCH_LAB_CONTEXT_CHARS=30000           # total source text in one writer/reviewer prompt
RESEARCH_LAB_MIN_OUTPUT_TOKENS=8192        # minimum answer length given to agent calls

BRIGHTDATA_API_TOKEN=
BRIGHTDATA_SERP_ZONE=        # (BRIGHTDATA_ZONE is accepted too)
CORE_API_KEY=                # required for CORE
YOUTUBE_API_KEY=             # required for YouTube
API_CONTACT_EMAIL=           # optional, "polite pool" for OpenAlex and Crossref

OPENALEX_API_KEY=            # optional
OPENALEX_MAILTO=             # optional, "polite pool"
SEMANTIC_SCHOLAR_API_KEY=    # optional
CROSSREF_MAILTO=             # optional, "polite pool"
GOOGLE_BOOKS_API_KEY=        # optional
```

No API key is ever stored in the database (`LLMProvider.secret_env_name` only names the environment
variable): everything above is read from the environment only. `backend/.env.example` lists them all.

---

## 10. How to run it

See the top-level `README.md` (backend + frontend in two terminals). Research Lab works without any
search key (OpenAlex, Semantic Scholar, Crossref, arXiv, Google Books, Open Library and Wikipedia are
keyless; Web Research needs Bright Data, CORE and YouTube need their keys); writing lectures and
assignments needs at least one LLM — a cloud key or a local model server.

### Your first research run

```bash
curl -X POST http://localhost:8000/api/v1/research-lab/runs/ \
  -H "Authorization: Bearer <access token>" -H "Content-Type: application/json" \
  -d '{"topic": "Retrieval-Augmented Generation", "education_level": "MASTER",
       "material_types": ["PAPERS"], "generate_assignment": true, "llm_mode": "HYBRID"}'
```

Or from the frontend: **New research run**. Poll
`GET /runs/{id}/` (the frontend does this automatically) until `status` is `COMPLETED`/`PARTIAL`,
then check the **Sources**, **Assignment** and **Metrics** tabs.

---

## 11. Tests

`research_lab/tests/` — 177 automated tests, with every external service replaced by fakes (no
network). They cover: providers (parsing, keys, errors),
SSRF and the fetch fallback chain (including "403 is never worked around"), dedup, retry, extraction,
`llm_json` (retry, output budget, local ↔ cloud fallback), batch validation (including fallback to
single requests), BM25 passage selection on a 100 000-character "book", the full multi-agent workflow
(healthy run, one provider down, missing key, all sources rejected, reviewer revision loop, revision
limit, timeout, cancellation, hybrid routing), the event stream / WebSocket / workspace snapshot,
the materials API (filters, text, PDF served inline, owner-only access) and the load report.

```bash
cd backend
python manage.py test
```

Twelve scenarios with expected results (several also run live against the real APIs and Claude) are
listed in the report, section 9.

---

## Materials search (find, download, read)

A run created with `mode: "SEARCH"` is a plain materials search: Web Research and Academic Research query
the selected sources, Document Analysis downloads what is openly available and extracts its text, and the run
ends there (no validation, lecture or assignment). The same pipeline serves full research runs.

* **Sources** — OpenAlex, CORE, Crossref, Google Books, Open Library, arXiv, Wikipedia, YouTube, Bright Data
  (plus Semantic Scholar). Each has an on/off switch in *Settings → Research Lab* (stored in `ModuleSettings`)
  and a status: active / disabled / API key missing / connection error (`provider_health`, updated by every
  real call and by the *Test* button). A run may further pick a subset (`selected_providers`).
* **Keys** — `.env`: `CORE_API_KEY`, `YOUTUBE_API_KEY`, `BRIGHTDATA_API_TOKEN` + `BRIGHTDATA_SERP_ZONE`
  (or `BRIGHTDATA_ZONE`); `OPENALEX_API_KEY`, `GOOGLE_BOOKS_API_KEY`, `API_CONTACT_EMAIL` are optional.
* **Download policy** (`agents/document_analysis.py`) — description-only sources (Crossref, Google Books, Open
  Library, YouTube) are never downloaded; at most `RESEARCH_LAB_FETCH_PER_PROVIDER` (5) downloads per source;
  PDF/PPTX/DOCX/TXT originals are stored in `ResearchDocument.file`, HTML only as text; HTTP 401/402/403/451
  are respected, never bypassed; duplicates are detected by metadata and by content hash.
* **API** — `GET runs/<id>/sources/` (filters `provider`, `source_type`, `document_format`, `downloaded`,
  `duplicates`), `.../sources/<sid>/` (full text), `.../sources/<sid>/file/` (PDF inline, `?download=1`),
  `.../context/` (all text as one block for a future LLM/RAG step, `?download=1` for a .txt),
  `POST settings/providers/<CODE>/test/`.
