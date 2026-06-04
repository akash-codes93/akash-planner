# Phase 3: Frontend — React Chat UI + Dashboard + Quick Capture

## Goal
A mobile-responsive web app with three views: chat with the agent (shows ReAct steps), dashboard (items overview), and quick capture (fast item entry). Deployable to Netlify.

## Prerequisites
- Phase 1 + 2 complete: FastAPI running with all tools, POST /chat returns structured steps
- Backend running on localhost:8000

## Steps

### Step 1: Scaffold React app
```bash
cd akash-planner
npm create vite@latest frontend -- --template react
cd frontend
npm install @supabase/supabase-js
```

Create `frontend/.env`:
```
VITE_API_URL=http://localhost:8000
VITE_SUPABASE_URL=<same as backend>
VITE_SUPABASE_ANON_KEY=<same as backend>
```

Create `frontend/netlify.toml`:
```toml
[build]
  command = "npm run build"
  publish = "dist"

[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200
```

### Step 2: Supabase client (frontend)
Create `frontend/src/lib/supabase.js`:
- Initialize Supabase client with VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY
- Export the client for direct reads (dashboard uses this, bypasses the agent for speed)

### Step 3: App layout and routing
Create `frontend/src/App.jsx`:
- Three-tab layout: Chat | Dashboard | Capture
- Use simple state-based tab switching (no router needed for 3 views)
- Mobile-first design: bottom tab bar on mobile, sidebar on desktop
- Dark theme (Akash uses dark themes — see iTerm2 setup)
- Clean, monospace-accented design (IBM Plex Mono for labels, IBM Plex Sans for body)

### Step 4: Chat component
Create `frontend/src/components/Chat.jsx`:
- Text input at bottom (mobile keyboard friendly)
- Messages scroll area above
- When user sends a message:
  1. POST to `${API_URL}/chat` with `{message, thread_id}`
  2. Response contains `{steps: [...], answer: str}`
  3. Render each step as a card with color coding:
     - 🧠 THOUGHT — purple
     - ⚡ ACTION — yellow/amber (show tool name + args)
     - 👁 OBSERVATION — green
     - ✅ ANSWER — blue
  4. Steps animate in sequentially (small delay between each) to show the ReAct loop
- Thread ID: generate a UUID per "conversation session", store in localStorage
- "New conversation" button resets thread_id
- Show loading state while agent is thinking (pulsing dots or "reasoning..." text)

### Step 5: Dashboard component
Create `frontend/src/components/Dashboard.jsx`:
- Reads DIRECTLY from Supabase (not through the agent — fast)
- Tabs or filter buttons: All | Work | Interview Prep | Learning | Personal | Hobby
- Status filter: Active (backlog + today + in_progress) | Done | All
- Items displayed as cards sorted by priority descending:
  - Priority badge (color-coded: red 80+, yellow 50-79, green <50)
  - Title, category/type tag, effort estimate, cognitive load indicator
  - Due date warning if approaching/overdue
  - Tags as small chips
  - Quick action buttons: ▶ Start (→ in_progress), ✓ Done, 📝 Edit
- Quick actions call Supabase directly (no need for the agent for simple status toggles)
- Supabase realtime subscription: when the agent adds/updates items via chat, dashboard updates live

### Step 6: Quick capture component
Create `frontend/src/components/Capture.jsx`:
- Minimal form: just title + category dropdown
- Everything else is optional (collapsible "more details" section):
  - item_type dropdown, priority slider, effort minutes, cognitive load, due date, url, tags, notes
- On submit: INSERT directly to Supabase (faster than going through the agent)
  - Set source="quick_capture"
  - Let the agent assign detailed priority/effort later if needed
- After submit: clear form, show confirmation toast
- This is the "I'm on my phone, quickly dump an item" interface

### Step 7: Mobile responsiveness
- Bottom tab bar for navigation on screens < 768px
- Chat input fixed to bottom of viewport
- Dashboard cards stack vertically on mobile
- Quick capture form full-width on mobile
- Touch targets minimum 44px
- Test on actual phone via local network (find your IP: `ifconfig`, open http://192.168.x.x:5173 on phone)

### Step 8: Polish
- Error states: show toast/banner when API is unreachable
- Empty states: "No items yet" with prompt to add some
- Loading skeletons for dashboard
- Keyboard shortcut: Cmd+K or / to focus chat input
- Auto-scroll chat to bottom on new messages

## Verification checklist
- [ ] Chat shows ReAct steps (thought/action/observation/answer) with colors
- [ ] Dashboard loads items from Supabase, filters work
- [ ] Quick capture adds items to Supabase, dashboard updates in realtime
- [ ] Works on mobile browser (test on phone via local network)
- [ ] "New conversation" resets chat thread
- [ ] Quick status toggles on dashboard update Supabase directly
