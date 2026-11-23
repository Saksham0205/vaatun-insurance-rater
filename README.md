# Vaatun Insurance Rater

Authenticated workspace for uploading motor policy PDFs, reviewing extracted policy facts, and viewing evidence-backed OD and TP commission decisions. The browser application uses Next.js, TypeScript, Tailwind CSS, and Supabase Auth. FastAPI remains responsible for authenticated upload, extraction, deterministic rating, and persistent Supabase database and private Storage access.

**PDF extraction uses Gemini as the sole provider.** PyMuPDF handles PDF integrity checks, page counting, hashing, and selectable-text extraction; Gemini processes the full PDF bytes for field extraction. Image-only pages that contain no selectable text are passed to Gemini as raw PDF bytes; there is no local OCR fallback.

The frontend does not use Gemini directly, choose commission rates, or display unsupported rates as confirmed.

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
# Configure GEMINI_API_KEY, SUPABASE_URL, SUPABASE_ANON_KEY,
# SUPABASE_SERVICE_ROLE_KEY, SUPABASE_BUCKET, and CORS_ORIGINS.
python -m uvicorn app.main:app --reload --port 8000
```

Keep `SUPABASE_SERVICE_ROLE_KEY` and all provider secrets only in the backend environment. The backend must use the existing migrated Supabase schema and a private `policy-pdfs` bucket.

#### Dependency files

| File | Purpose |
|------|---------|
| `requirements.txt` | Production dependencies (installed by Render) |
| `requirements-dev.txt` | Development/test tools — pytest, debugpy |



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

The repository includes [`render.yaml`](render.yaml) for the FastAPI service. Create a Render Blueprint from this repository, set `GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and set `CORS_ORIGINS` to the deployed Vercel URL.

Deploy `frontend` as a Vercel project with its root directory set to `frontend`. Set `NEXT_PUBLIC_API_URL` to the Render API URL and set the two public Supabase variables from `frontend/.env.example`. After deployment, update Render's `CORS_ORIGINS` with the final Vercel origin and configure that origin in Supabase Auth redirect URLs.

