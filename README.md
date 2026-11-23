# Vaatun Insurance Rater

Authenticated workspace for uploading motor policy PDFs, reviewing extracted policy facts, and viewing evidence-backed OD and TP commission decisions. The browser application uses Next.js, TypeScript, Tailwind CSS, and Supabase Auth. FastAPI remains responsible for authenticated upload, extraction, deterministic rating, and persistent Supabase database and private Storage access.

## How a policy is rated (no AI)

1. **Read.** PyMuPDF reads the text layer; scanned pages are OCR'd locally with RapidOCR (no API, no quota).
2. **Extract.** Layout-aware rules (`backend/app/rating_engine/insurer_rules.py`) read each value from the
   same row as its label (or directly beneath it) using OCR positions, plus the text parser in
   `document_pipeline.py`. Every value keeps its page and the exact OCR text as evidence. Values that are
   not printed are never guessed.
3. **Rate.** Deterministic adapters select the rate from each insurer's rate card in `backend/rate_cards/`;
   commission = premium basis × rate.
4. **Review.** When the PDF omits a selector (e.g. fuel on HDFC/Reliance, Tata AIG segment and business
   type), the reviewer supplies it under *Review rating inputs*. Values are validated against the rate card's
   vocabulary, recorded as "Operator review" evidence, and the commission is recomputed.

`tests/test_document_to_decision.py` checks every extracted field of the four sample policies against the
values printed in the PDFs, and the reviewed commission against the rate card.

| Insurer | Selects on | Basis |
|---|---|---|
| HDFC ERGO | zone (state/city table), OD-premium slab, fuel group, NCB | OD premium (OD-only grid: no TP payout) |
| Reliance | region (from state/RTO), fuel; <1000 CC, standalone ZD and Tyre/RTI adjustments | OD premium (STP 0%) |
| Go Digit | RTO code → cluster; SATP: fuel/CC segment × age band; Package: make group (new business) | TP premium / OD premium |
| Tata AIG | territory, segment, business type, fuel, NCB, add-on | OD premium; SATP on net premium |

**Stated assumptions** (shown on the decision as `Assumption: …`): Reliance grid adjustments are percentage points;
Go Digit "Max CD2" is the payout rate (as on its New Business 1+3 sheet); the Reliance Extended Warranty flat payout
is not part of the grid commission. A decision is "complete" only when every applicable component has a rate and a
₹ amount.

## Local setup

### Backend

The backend requires **Python 3.11.11** (pinned in `backend/.python-version`).

```powershell
cd backend
python3.11 -m venv .venv
.venv\Scripts\Activate.ps1
# Production dependencies only:
python -m pip install -r requirements.txt
# Add development/test dependencies:
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
# Configure SUPABASE_URL, SUPABASE_ANON_KEY,
# SUPABASE_SERVICE_ROLE_KEY, SUPABASE_BUCKET, and CORS_ORIGINS.
python -m uvicorn app.main:app --reload --port 8000
```

Keep `SUPABASE_SERVICE_ROLE_KEY` and all provider secrets only in the backend environment. The backend must use the existing migrated Supabase schema and a private `policy-pdfs` bucket.

#### Dependency files

| File | Purpose |
|------|---------|
| `requirements.txt` | Production dependencies (installed by Render) |
| `requirements-dev.txt` | Development/test tools — pytest |



### Frontend

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
# Set NEXT_PUBLIC_API_URL, NEXT_PUBLIC_SUPABASE_URL, and
# NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY.
npm run dev
```

Open `http://localhost:3000`. The `NEXT_PUBLIC_*` Supabase key is the publishable/anon key; never place the service-role key in frontend configuration.

For email-confirmed sign-up, configure the Supabase Auth Site URL and redirect allow list to include `http://localhost:3000/auth/callback` and the intended application origin's `/auth/callback` URL. Configure the API CORS allow list to include the frontend origin.

Frontend variables are listed in `frontend/.env.example`; backend variables are listed in `backend/.env.example`. Local environment files are ignored by Git.

## Frontend checks

```powershell
cd frontend
npm run build
npm audit --omit=dev
npm run test:e2e -- --workers=1
```

The Playwright E2E test uses two temporary real Supabase users and the actual Supabase project, while running Next.js and FastAPI locally. Its Node test runner reads the backend service key only to provision and clean up test identities and verify persisted records; browser JavaScript receives only the publishable key. Run it against an isolated project and valid local environment files.

## Backend tests

```powershell
cd backend
python -m pytest tests -q
```

## Deployment

The repository includes [`render.yaml`](render.yaml) for the FastAPI service. Create a Render Blueprint from this repository, set `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and set `CORS_ORIGINS` to the deployed Vercel URL.

Deploy `frontend` as a Vercel project with its root directory set to `frontend`. Set `NEXT_PUBLIC_API_URL` to the Render API URL and set the two public Supabase variables from `frontend/.env.example`. After deployment, update Render's `CORS_ORIGINS` with the final Vercel origin and configure that origin in Supabase Auth redirect URLs.

