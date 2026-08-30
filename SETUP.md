# Setup — No Coding Required

I've already built and wired together everything: the data pulling, the
trend detection, the win-rate calculator, and the dashboard. This runs
itself automatically once you finish these steps. It's about 15 minutes,
all clicking, no code.

## What you're doing, in plain terms

You're going to put this project on a free website called GitHub, tell it
your one password (an API key, which is just a long code you copy-paste),
and turn on two switches. After that, it checks the games and updates your
dashboard every morning by itself, forever, for free.

---

### Step 1 — Get your free data key (2 minutes)

1. Go to **oddspapi.io** and sign up for a free account (no credit card).
2. Once logged in, find your **API key** (usually on a dashboard/account
   page) and copy it. It'll look like a long random string of letters and
   numbers.
3. Keep that tab open — you'll paste this in Step 4.

### Step 2 — Create a free GitHub account (2 minutes)

1. Go to **github.com** and sign up (free plan is all you need).

### Step 3 — Create your project and upload these files (5 minutes)

1. Once logged in, click the **+** icon top-right → **New repository**.
2. Name it something like `sports-edge-finder`. Set it to **Private**
   (so only you can see it). Click **Create repository**.
3. On the new repo page, click **"uploading an existing file"**.
4. Drag the entire unzipped project folder (all the files I gave you —
   the .py files, README, requirements.txt, and the `.github` folder)
   into the upload box. GitHub will upload everything, including the
   hidden `.github/workflows` folder — that's the automation.
5. Scroll down, click **Commit changes**.

### Step 4 — Give it your API key (2 minutes)

1. In your repo, click **Settings** (top menu) → **Secrets and variables**
   → **Actions** (left sidebar).
2. Click **New repository secret**.
3. Name: `ODDSPAPI_KEY`
4. Value: paste the key you copied in Step 1.
5. Click **Add secret**.

### Step 5 — Turn on automation permissions (1 minute)

1. Still in **Settings** → **Actions** → **General** (left sidebar).
2. Scroll to **Workflow permissions**.
3. Select **"Read and write permissions"**.
4. Click **Save**.

### Step 6 — Turn on your dashboard webpage (1 minute)

1. In **Settings** → **Pages** (left sidebar).
2. Under "Build and deployment" → Source: **Deploy from a branch**.
3. Branch: select **main**, folder: select **/docs**. Click **Save**.
4. GitHub will show you a URL like
   `https://yourusername.github.io/sports-edge-finder/` — that's your
   dashboard, bookmark it. It'll be empty until Step 7 runs.

### Step 7 — Run the one-time historical backfill (1 click)

1. Click the **Actions** tab (top menu) in your repo.
2. Click **"One-Time Season Backfill"** in the left list.
3. Click the **Run workflow** button (right side) → **Run workflow**.
4. Wait a few minutes, then refresh — it'll show a green checkmark when
   done. This pulls this season's (and last season's) MLB and WNBA games
   and results.

### Step 8 — Done. It now runs itself every morning.

The **"Daily Sports Data Pipeline"** workflow is scheduled to run
automatically every morning. It pulls new odds, checks yesterday's
results, recalculates the trends, and updates your dashboard webpage —
with zero further action from you.

You can also trigger it manually any time: **Actions** tab → **"Daily
Sports Data Pipeline"** → **Run workflow**.

---

## What to actually do day to day

- **Check your dashboard URL** (from Step 6) whenever you want — it's
  always current as of that morning's run.
- **Give it time.** A trend needs a real sample size (roughly 100+ graded
  games) before the win-rate numbers mean anything. Early on, the
  dashboard will say "small sample, keep watching" — that's the system
  being honest with you, not broken.
- **NFL and NCAAF** will start showing real data once their seasons begin
  in the next couple weeks — no changes needed on your end, it's already
  wired up.
- If anything breaks (a red X in the Actions tab), copy the error text
  and send it to me — I'll fix it.

## The one real gap (explained honestly)

Free, reliable **public bet%/handle%** data (the exact number your Twitter
account posts) doesn't really exist anywhere for free — that data point is
usually paid. So the system starts by testing **line movement alone**
(steam moves), which is a real, well-studied signal that doesn't need
bet% data. If you ever want to add a paid handle% feed later, the system
already has a slot ready for it — just tell me and I'll wire it in.
