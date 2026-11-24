# Vaatun Insurance Rater

Upload a private-car motor insurance policy PDF and get back the **OD and TP commission** that the insurer's
rate card pays on it. Every number comes with its evidence: the policy page and text it was read from, and
the rate-card sheet/cell or table/row it was looked up in.

Rating is **fully deterministic. No AI or LLM is involved** in reading, rating or commission. Scanned
policies are read with local OCR, values are extracted by layout-aware rules, and rates come straight from
the insurers' own grids.

| | |
|---|---|
| **Web app** | https://vaatun-insurance-rater.vercel.app |
| **API** | https://vaatun-insurance-rater.onrender.com ([health](https://vaatun-insurance-rater.onrender.com/api/v1/health)) |

> The API runs on Render's free plan, which sleeps when idle. The first request after a pause can take
> about a minute while it wakes up.

**Supported insurers:** HDFC ERGO · Reliance General · Go Digit · Tata AIG (private car: Package, SAOD, SATP)

---

## Using the app

1. **Sign up / log in.** This uses Supabase Auth (email + password). Each user sees only their own documents.
2. **Upload a policy PDF** (up to 25 MB). Duplicate uploads are recognised by SHA-256.
3. **Analyze.** The backend reads the PDF, extracts the policy facts, identifies the insurer and product,
   and rates the OD and TP components against that insurer's rate card.
4. **Review the decision.** Each extracted fact shows its value, confidence, page and source text. Each
   component shows its status (resolved / ambiguous / unsupported / not applicable), the rate, the premium
   basis, the ₹ commission and the rate-card evidence.
5. **Supply missing inputs.** Some grids select on values a policy doesn't print (for example fuel on
   HDFC/Reliance, or Tata AIG segment and business type). The reviewer picks them under *Review rating
   inputs* from the rate card's own vocabulary. They are stored as "Operator review" evidence and the
   commission is recomputed without re-reading the PDF.

The four PDFs in [`sample-policies/`](sample-policies) (one per insurer) are good for trying it out.

---

## How a policy is rated

```
PDF ──► Read ──► Extract ──► Identify & classify ──► Rate ──► Review
        PyMuPDF   layout      insurer, product,       insurer    reviewer fills
        + local   rules       business type           adapter    missing selectors
        OCR                                           + grid
```

1. **Read** (`parsers/pdf.py`). PyMuPDF reads the text layer and tables. Pages with no text layer
   (scans) are OCR'd locally with RapidOCR, with no external API and no quota. At most the first 8
   scanned pages are read (the schedule pages; the rest is policy wording).
2. **Extract** (`insurer_rules.py`, `document_pipeline.py`). Each value is read from the same row as
   its label, or directly beneath it, using OCR positions. Every value keeps its page and exact source text
   as evidence. Values that aren't printed are never guessed, and low-confidence reads are flagged.
3. **Identify & classify** (`identification.py`, `classification.py`). The insurer is matched to
   exactly one supported rate-card family. The product is classified as Package, SAOD or SATP, and the
   business type comes from the current vs previous insurer.
4. **Rate** (`adapters/*.py`, `engine.py`). One adapter per insurer selects the rate from that
   insurer's grid in `backend/rate_cards/`. Commission = premium basis × rate.

| Insurer | Selects on | Basis |
|---|---|---|
| HDFC ERGO | zone (state/city table), OD-premium slab, fuel group, NCB | OD premium (OD-only grid, so no TP payout) |
| Reliance | region (from state/RTO), fuel; <1000 CC, standalone ZD and Tyre/RTI adjustments | OD premium (STP 0%) |
| Go Digit | RTO code → cluster; SATP: fuel/CC segment × age band; Package: make group (new business) | TP premium / OD premium |
| Tata AIG | territory, segment, business type, fuel, NCB, add-on | OD premium; SATP on net premium |

**Stated assumptions** (each appears on the decision as `Assumption: …`):
- Reliance grid adjustments are percentage points.
- Go Digit "Max CD2" is the payout rate, as on its New Business 1+3 sheet.
- The Reliance Extended Warranty flat payout is not part of the grid commission.

A decision is **complete** only when every applicable component has both a rate and a ₹ amount.

---

## Architecture

| Layer | Tech | Hosted on |
|---|---|---|
| Frontend | Next.js 15 (App Router), React 18, TypeScript, Tailwind CSS | Vercel |
| Backend API | FastAPI, Python 3.11, PyMuPDF, RapidOCR (ONNX Runtime), openpyxl | Render (free, 512 MB) |
| Auth, database, file storage | Supabase Auth, Postgres with row-level security, private Storage bucket | Supabase |

- The browser authenticates with Supabase and sends its access token to the API as `Authorization: Bearer …`.
  The API verifies the token on every request.
- Only the backend holds the Supabase **service-role key**. The browser gets only the publishable key.
- PDFs are stored in the private `policy-pdfs` bucket. Analyses, extracted facts, component decisions and
  evidence references are stored in Postgres, all scoped per user by RLS.

### Project structure

```
backend/
  app/
    main.py                 FastAPI routes, logging, error handling
    auth.py                 Supabase token verification (cached)
    repository.py           Supabase Storage + Postgres persistence
    config.py               settings from environment variables
    rating_engine/
      parsers/pdf.py        text layer, tables, local OCR
      parsers/excel.py      rate-card cell parser (used by tests)
      document_pipeline.py  PDF → facts → decision
      insurer_rules.py      layout-aware, insurer-specific extraction
      identification.py     insurer identification
      classification.py     product and business-type classification
      engine.py             selects and runs the insurer adapter
      adapters/             one rate-card adapter per insurer
      review.py             reviewer overrides and re-rating
  rate_cards/               the insurers' grids (xlsx / pdf)
  ocr_cache/                stored OCR output for the sample policies (see below)
  tests/
frontend/
  app/                      login, signup, workspace, document detail pages
  components/               workspace shell, rating review panel
  lib/                      API client, Supabase clients
  tests/e2e/                Playwright tests
supabase/migrations/        database schema, RLS policies, storage bucket
sample-policies/            one sample policy PDF per insurer
render.yaml                 Render Blueprint for the API
```

### API

All endpoints except health need a Supabase access token.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/health` | Service and database status |
| `POST` | `/api/v1/documents/upload` | Upload a policy PDF (multipart `file`) |
| `GET` | `/api/v1/documents` | List documents (`q`, `status`, `insurer`, `limit`, `offset`) with dashboard stats |
| `GET` | `/api/v1/documents/{id}` | Document with its analyses |
| `DELETE` | `/api/v1/documents/{id}` | Delete a document and its file |
| `POST` | `/api/v1/documents/{id}/analyze` | Run the analysis (`force=true` re-runs a completed one) |
| `GET` | `/api/v1/analyses/{id}` | One analysis with facts, decisions and evidence |
| `GET` | `/api/v1/review/options` | Reviewable inputs and the values each rate card accepts |
| `POST` | `/api/v1/analyses/{id}/review` | Apply reviewer inputs and recompute the commission |

Interactive docs: `/docs` on the API.

---

## Running within 512 MB (free Render plan)

Local OCR is the heaviest step: running it on a scanned policy briefly needs about 430–460 MB. To stay
inside the free instance's 512 MB, the backend:

- **releases PyMuPDF's internal cache** after each PDF and each OCR'd page. It otherwise grew by 50–100 MB
  per policy and was never returned.
- opens rate-card workbooks **read-only** (the Tata AIG grid went from about 147 MB to about 3 MB).
- runs **one analysis at a time**, so two uploads can't add their memory peaks together.
- turns off ONNX Runtime's per-input-shape buffer cache, and skips table detection on pages with no text layer.
- sets `MALLOC_ARENA_MAX=2` to limit memory fragmentation across threads.

**Stored OCR for the sample policies.** `backend/ocr_cache/` holds the OCR output for the four
`sample-policies/` PDFs, produced by the same engine and settings and named by each PDF's SHA-256. When one
of those exact files is analyzed, the stored text is used instead of running OCR. That analysis gives
identical results, peaks at about 120 MB and finishes in about a second instead of 1–4 minutes. **Any other
PDF is OCR'd live.** `tests/test_bundled_ocr_cache.py` fails if a sample page is missing. If you change
the OCR settings, delete `backend/ocr_cache/*.json`, re-run the samples, and copy the new files from the
temp cache (`vaatun-policy-ocr-cache` in the system temp folder).

---

## Local setup

**Prerequisites:** Python 3.11.11 (pinned in `backend/.python-version`), Node.js 18+, and a Supabase project
with [`supabase/migrations/202611220001_application_foundation.sql`](supabase/migrations/202611220001_application_foundation.sql)
applied. The migration creates the tables, RLS policies and the private `policy-pdfs` bucket.

### Backend

```powershell
cd backend
python3.11 -m venv .venv
.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt
Copy-Item .env.example .env          # macOS/Linux: cp .env.example .env
python -m uvicorn app.main:app --reload --port 8000
```

| Variable | Required | Description |
|---|---|---|
| `SUPABASE_URL` | yes | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | yes | Service-role key. **Backend only, never expose it.** |
| `SUPABASE_PUBLISHABLE_KEY` | yes | Publishable (anon) key |
| `SUPABASE_BUCKET` | no | Storage bucket, default `policy-pdfs` |
| `CORS_ORIGINS` | no | Comma-separated allowed frontend origins, default `localhost:3000` |
| `LOCAL_OCR_ENABLED` | no | `false` turns OCR off, default `true` |
| `LOCAL_OCR_MAX_PAGES` | no | Scanned pages OCR'd per policy, default `8` |
| `LOCAL_OCR_THREADS` | no | ONNX Runtime threads, default `2` |
| `MAX_UPLOAD_BYTES` | no | Upload limit, default 25 MB |
| `ANALYSIS_STALE_AFTER_SECONDS` | no | When a stuck `processing` analysis counts as failed |

### Frontend

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local    # macOS/Linux: cp .env.example .env.local
npm run dev
```

| Variable | Description |
|---|---|
| `NEXT_PUBLIC_API_URL` | Backend URL, e.g. `http://localhost:8000` |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Publishable (anon) key. Never use the service-role key here. |

Open http://localhost:3000. For email-confirmed sign-up, add `http://localhost:3000/auth/callback` (and the
deployed origin's `/auth/callback`) to Supabase Auth's redirect URLs.

---

## Tests

```powershell
# Backend: unit, adapter, API, and end-to-end document-to-decision tests
cd backend
python -m pytest tests -q

# Frontend: production build, dependency audit, Playwright E2E
cd frontend
npm run build
npm audit --omit=dev
npm run test:e2e -- --workers=1
```

- `test_document_to_decision.py` checks every extracted field of the four sample policies against the
  values printed in the PDFs, and the reviewed commission against the rate card.
- `test_supabase_e2e_live.py` and the Playwright tests run against a **real** Supabase project. They create
  and clean up temporary users. Run them against an isolated project with valid local env files. Without
  that configuration, `test_supabase_e2e_live.py` is skipped.

---

## Deployment

**Backend (Render).** Create a Blueprint from this repository; [`render.yaml`](render.yaml) defines the
service. Set `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` and `SUPABASE_PUBLISHABLE_KEY`, and set `CORS_ORIGINS`
to the Vercel origin exactly, with no trailing slash: `https://vaatun-insurance-rater.vercel.app`.
A `Dockerfile` is also included if you prefer a container deploy.

**Frontend (Vercel).** Import the repository with the root directory set to `frontend`. Set the three
`NEXT_PUBLIC_*` variables, with `NEXT_PUBLIC_API_URL` pointing to the Render URL. Then add the Vercel
origin to Supabase Auth's redirect URLs.

**Troubleshooting:** if the browser reports a *CORS error* while `/api/v1/health` is fine, check that
`CORS_ORIGINS` matches the frontend origin exactly. If health itself fails, the instance is restarting or
waking up: Render's proxy error page has no CORS headers, so the browser shows that as a CORS error too.
