# Phase 4: Deploy — Render + Groq + Supabase Auth + Netlify

## Goal
Everything running in the cloud. Backend on Render (free), frontend on Netlify (free), LLM via Groq (free), locked down with Supabase Auth so only Akash can use it.

## Prerequisites
- Phase 1-3 complete: full stack working locally
- Accounts: Render (render.com), Netlify (netlify.com), Groq (console.groq.com)

## Steps

### Step 1: Groq API setup
- Go to console.groq.com, create account, get API key
- Test locally first: set `LLM_PROVIDER=groq` and `GROQ_API_KEY=<key>` in .env
- Run cli.py, verify the agent works with Groq instead of Ollama
- Groq free tier: 30 requests/minute, 14,400/day — plenty for personal use

### Step 2: Dockerize the backend
Create `backend/Dockerfile`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
```

Create `backend/.dockerignore`:
```
.env
__pycache__/
*.pyc
.venv/
```

Test locally:
```bash
docker build -t akash-planner .
docker run -p 8000:8000 --env-file .env akash-planner
```

### Step 3: Deploy backend to Render
- Go to render.com → New → Web Service → connect GitHub repo (or use Docker image)
- Settings:
  - Build command: `pip install -r requirements.txt`
  - Start command: `uvicorn api.server:app --host 0.0.0.0 --port $PORT`
  - Or use Docker (preferred): point to the Dockerfile
- Environment variables: add SUPABASE_URL, SUPABASE_KEY, LLM_PROVIDER=groq, GROQ_API_KEY, GROQ_MODEL
- Free tier: service sleeps after 15 min inactivity. First request after sleep takes ~30 seconds.

Note the Render URL (like https://akash-planner.onrender.com).

### Step 4: Keep-warm workaround (optional)
Render free tier sleeps the service after 15 min of no requests. To avoid cold starts:
- Option A: Supabase Edge Function that pings /health every 14 minutes (free)
- Option B: Use a free cron service like cron-job.org to hit the /health endpoint every 14 min
- Option C: Accept the 30-second cold start (it's a personal tool, this is fine honestly)

### Step 5: Supabase Auth
Enable auth in Supabase:
1. Go to Supabase dashboard → Authentication → Providers → enable Google
2. Set up Google OAuth credentials (console.cloud.google.com → create OAuth client)
3. Add `user_id` column to items, conversations, user_context tables:
   ```sql
   alter table items add column user_id uuid references auth.users(id);
   alter table conversations add column user_id uuid references auth.users(id);
   alter table user_context add column user_id uuid references auth.users(id);
   
   -- Update existing rows (your user ID after first login)
   -- update items set user_id = '<your-user-uuid>';
   -- update conversations set user_id = '<your-user-uuid>';
   -- update user_context set user_id = '<your-user-uuid>';
   ```

4. Enable RLS and create policies:
   ```sql
   alter table items enable row level security;
   create policy "Users see own items" on items for all using (auth.uid() = user_id);
   
   alter table conversations enable row level security;
   create policy "Users see own conversations" on conversations for all using (auth.uid() = user_id);
   
   alter table user_context enable row level security;
   create policy "Users see own context" on user_context for all using (auth.uid() = user_id);
   ```

5. Update frontend to use Supabase Auth:
   - Add login screen with Google OAuth button
   - Pass Supabase auth token to backend API calls
   - Backend validates the token and extracts user_id

6. Update backend to include user_id in all Supabase operations:
   - Use service_role key in backend (bypasses RLS) OR
   - Pass user's JWT to supabase client (respects RLS)
   - Better: use service_role key + manually filter by user_id (simpler, more predictable)

### Step 6: Deploy frontend to Netlify
- Go to netlify.com → New site → connect GitHub repo
- Build settings: auto-detected from netlify.toml (build command: npm run build, publish: dist)
- Environment variables:
  - VITE_API_URL=https://akash-planner.onrender.com (your Render URL)
  - VITE_SUPABASE_URL=<your supabase url>
  - VITE_SUPABASE_ANON_KEY=<your anon key>
- The frontend is now live at something like https://akash-planner.netlify.app

### Step 7: CORS and security hardening
Update backend CORS to only allow:
- Your Netlify domain (https://akash-planner.netlify.app)
- localhost:5173 (for local dev)

Update backend to validate auth token on all endpoints:
- Extract Bearer token from Authorization header
- Verify with Supabase auth
- Reject unauthenticated requests

### Step 8: Custom domain (optional)
- Buy a domain or use a free subdomain
- Point it to Netlify
- Update CORS in backend

## Verification checklist
- [ ] Backend running on Render, responds to /health
- [ ] Groq API working as LLM provider
- [ ] Frontend deployed on Netlify, loads correctly
- [ ] Google login works, only authenticated users can access
- [ ] Chat from phone browser works end-to-end
- [ ] RLS enabled, data isolated per user
- [ ] Cold start time acceptable (or keep-warm configured)
