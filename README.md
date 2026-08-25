# Debt Wall — Corporate Debt Risk Dashboard

Type in any US public company's ticker and see its debt maturity wall, interest
coverage, leverage ratios, and a rules-based refinancing-risk score, pulled
live from SEC EDGAR's XBRL data. No API key, no paid data provider.

## Why this exists

Public companies disclose their debt maturity schedule, interest expense, and
leverage every year in their 10-K footnotes, but it's typically buried in a
table on page 60. This pulls the same numbers straight from SEC's structured
XBRL data and turns them into one screen.

## Run it

```bash
cd backend
pip install -r requirements.txt
```

SEC requires every request to identify a real contact. The default is set in
`backend/sec_edgar.py`; override it without editing code by setting an env var:

```bash
export SEC_USER_AGENT="Debt Wall (contact: you@example.com)"
python app.py
```

Open **http://localhost:5000** and type a ticker (try `AAPL`, `KO`, `T`, `F`,
or `BA`).

## Deploy it

The repo ships with a `render.yaml` and a `Procfile`, so it runs on any
Python host that speaks gunicorn.

**Render (free tier):**

1. Go to [render.com](https://render.com) → **New → Blueprint**.
2. Connect this GitHub repo. Render reads `render.yaml` automatically.
3. Set the `SEC_USER_AGENT` environment variable to `Debt Wall (contact: your-real-email)`.
4. Deploy. First request after idle takes ~30s on the free tier (cold start).

**Anywhere else** (Railway, Fly, Heroku): the start command is

```bash
gunicorn --chdir backend app:app
```

Note: GitHub Pages can't host this, since the Flask backend is what talks
to SEC EDGAR.

## How it works

- **`backend/sec_edgar.py`** — talks to two SEC EDGAR endpoints:
  - `company_tickers.json` to map a ticker to its CIK (company ID)
  - `companyconcept` to pull the reported history of a single XBRL tag
    (e.g. `LongTermDebtMaturitiesRepaymentsOfPrincipalInYearOne`)

  It tries a handful of tag name variants per concept, because companies
  aren't perfectly consistent in how they tag the same real-world line item.
  From the raw facts it computes interest coverage, debt/EBITDA, debt/equity,
  current ratio, and a simple 0–100 refinancing-risk score that blends
  near-term maturities vs. cash on hand, interest coverage, and leverage.

- **`backend/app.py`** — a thin Flask API (`/api/search`, `/api/dashboard/<ticker>`)
  and static file server for the frontend.

- **`frontend/`** — vanilla HTML/CSS/JS. The maturity-wall chart is Chart.js;
  everything else is hand-rolled so it's easy to read and modify.

## Known limitations (worth knowing before you put this on a resume)

- **Coverage is uneven.** Not every filer tags a maturity schedule the same
  way — some smaller companies or ones with little long-term debt won't have
  one at all. The dashboard says so explicitly rather than showing a fake
  zero.
- **The risk score is a teaching tool, not a credit rating.** It's a
  transparent, documented blend of three ratios — real rating agencies weigh
  covenants, off-balance-sheet obligations, industry norms, and qualitative
  factors that aren't in XBRL.
- **EBITDA is estimated** as operating income + D&A, since "EBITDA" itself
  isn't a standard XBRL tag.
- **SEC data lags real time** by however long it takes a company to file —
  usually 60–90 days after fiscal year end for a 10-K.

## Natural next steps

- Add a quarter-over-quarter trend view (the API already returns full history
  per tag, this UI just shows the latest).
  - Layer in bond-level detail (coupon, maturity date, credit rating) from a
  provider like Financial Modeling Prep's free tier once you're ready to add
  an API key.
- Cache SEC responses (e.g. SQLite or Redis) so repeat lookups don't re-hit
  the API.
- Compare 2–3 companies side by side.
