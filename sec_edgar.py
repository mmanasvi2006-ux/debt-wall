"""
sec_edgar.py
------------
Thin client for SEC EDGAR's public XBRL "company facts" / "company concept"
APIs, plus the financial math that turns raw XBRL facts into the numbers
the dashboard shows (debt maturity wall, interest coverage, leverage ratios,
a simple refinancing-risk score).

No API key required. SEC just asks that every request carries a descriptive
User-Agent with a real contact (see USER_AGENT below) — requests without one
get blocked.

Docs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
"""

from __future__ import annotations

import time
import functools
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# SEC requires a real identifying User-Agent. Edit the email before you
# deploy this anywhere public — SEC will block generic/placeholder agents.
USER_AGENT = "Corporate Debt Risk Dashboard (contact: your-email@example.com)"

HEADERS = {"User-Agent": USER_AGENT}

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
COMPANY_CONCEPT_URL = (
    "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"
)

# SEC asks for <=10 requests/second; we stay well under that.
_MIN_INTERVAL = 0.15
_last_call = [0.0]


def _throttle() -> None:
    elapsed = time.time() - _last_call[0]
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_call[0] = time.time()


def _get(url: str) -> dict[str, Any] | None:
    _throttle()
    resp = requests.get(url, headers=HEADERS, timeout=15)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Ticker -> CIK lookup
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _ticker_table() -> dict[str, dict[str, Any]]:
    """SEC publishes one big ticker->CIK->name JSON. Cache it in memory."""
    data = _get(TICKER_MAP_URL) or {}
    table = {}
    for _, row in data.items():
        table[row["ticker"].upper()] = {
            "cik": str(row["cik_str"]).zfill(10),
            "title": row["title"],
        }
    return table


def lookup_ticker(ticker: str) -> dict[str, Any] | None:
    """Return {'cik': '0000320193', 'title': 'Apple Inc.'} or None."""
    return _ticker_table().get(ticker.upper())


def search_companies(query: str, limit: int = 8) -> list[dict[str, Any]]:
    """Loose prefix/substring match over ticker and name, for a search box."""
    q = query.strip().upper()
    if not q:
        return []
    results = []
    for ticker, row in _ticker_table().items():
        if ticker.startswith(q) or q in row["title"].upper():
            results.append({"ticker": ticker, "cik": row["cik"], "title": row["title"]})
    # Exact/prefix ticker matches first
    results.sort(key=lambda r: (not r["ticker"].startswith(q), r["ticker"]))
    return results[:limit]


# ---------------------------------------------------------------------------
# Raw XBRL fact helpers
# ---------------------------------------------------------------------------

def get_concept_values(cik: str, tag: str, unit: str = "USD") -> list[dict[str, Any]]:
    """
    Fetch one us-gaap tag's full reported history for a company.
    Returns a list of {end, val, fy, fp, form, frame} dicts, most recent last.
    Returns [] if the company never tagged this concept (very common — not
    every filer uses the same tags for the same real-world line item).
    """
    data = _get(COMPANY_CONCEPT_URL.format(cik=cik, tag=tag))
    if not data:
        return []
    units = data.get("units", {})
    values = units.get(unit, [])
    return sorted(values, key=lambda v: v.get("end", ""))


def latest_annual_value(cik: str, tag: str, unit: str = "USD") -> dict[str, Any] | None:
    """Most recent value taken from a 10-K (annual) filing for a tag."""
    values = get_concept_values(cik, tag, unit)
    annual = [v for v in values if v.get("form") == "10-K"]
    pool = annual or values
    return pool[-1] if pool else None


def first_available(cik: str, tags: list[str], unit: str = "USD") -> dict[str, Any] | None:
    """Try several alternate tag names (companies vary) and return the first hit."""
    for tag in tags:
        v = latest_annual_value(cik, tag, unit)
        if v is not None:
            v["_tag"] = tag
            return v
    return None


# ---------------------------------------------------------------------------
# Tag families (companies are inconsistent, so we try a few names for each concept)
# ---------------------------------------------------------------------------

MATURITY_TAGS = {
    "Year 1": ["LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths"],
    "Year 2": ["LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo"],
    "Year 3": ["LongTermDebtMaturitiesRepaymentsOfPrincipalInYearThree"],
    "Year 4": ["LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFour"],
    "Year 5": ["LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFive"],
    "Thereafter": ["LongTermDebtMaturitiesRepaymentsOfPrincipalAfterYearFive"],
}

CREDIT_TAGS = {
    "total_debt_current": ["LongTermDebtCurrent", "DebtCurrent"],
    "total_debt_noncurrent": ["LongTermDebtNoncurrent"],
    "short_term_borrowings": ["ShortTermBorrowings"],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsAtCarryingValue",
    ],
    "operating_income": ["OperatingIncomeLoss"],
    "interest_expense": ["InterestExpense", "InterestExpenseDebt", "InterestExpenseOther"],
    "depreciation_amortization": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
    ],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "total_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "revenues": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
    "net_income": ["NetIncomeLoss"],
}


def get_debt_maturity_wall(cik: str) -> dict[str, Any]:
    """Debt maturity schedule as disclosed in the most recent 10-K footnotes."""
    wall = {}
    fiscal_year = None
    for label, tags in MATURITY_TAGS.items():
        v = first_available(cik, tags)
        if v:
            wall[label] = v["val"]
            fiscal_year = fiscal_year or v.get("fy")
    return {"fiscal_year": fiscal_year, "schedule": wall}


def get_credit_metrics(cik: str) -> dict[str, Any]:
    """Pull the raw line items needed for the ratio panel and compute them."""
    raw: dict[str, Any] = {}
    for label, tags in CREDIT_TAGS.items():
        v = first_available(cik, tags)
        raw[label] = v["val"] if v else None
        if v:
            raw[f"{label}_fy"] = v.get("fy")

    total_debt = (raw.get("total_debt_current") or 0) + (raw.get("total_debt_noncurrent") or 0) + (raw.get("short_term_borrowings") or 0)

    ebit = raw.get("operating_income")
    interest = raw.get("interest_expense")
    ebitda = None
    if ebit is not None:
        ebitda = ebit + (raw.get("depreciation_amortization") or 0)

    def safe_div(a, b):
        if a is None or not b:
            return None
        return round(a / b, 2)

    metrics = {
        "total_debt": total_debt or None,
        "cash": raw.get("cash"),
        "net_debt": (total_debt - raw["cash"]) if (total_debt and raw.get("cash") is not None) else None,
        "ebit": ebit,
        "ebitda": ebitda,
        "interest_expense": interest,
        "interest_coverage_ebit": safe_div(ebit, interest),
        "interest_coverage_ebitda": safe_div(ebitda, interest),
        "debt_to_ebitda": safe_div(total_debt, ebitda),
        "debt_to_equity": safe_div(total_debt, raw.get("total_equity")),
        "current_ratio": safe_div(raw.get("current_assets"), raw.get("current_liabilities")),
        "debt_to_assets": safe_div(total_debt, raw.get("total_assets")),
        "net_margin": safe_div(raw.get("net_income"), raw.get("revenues")),
        "revenues": raw.get("revenues"),
        "net_income": raw.get("net_income"),
    }
    return {"raw": raw, "metrics": metrics}


def score_refinancing_risk(maturity_wall: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    """
    A transparent, rules-based risk score (0-100, higher = riskier) —
    NOT a substitute for an actual credit rating. It combines:
      - how much debt comes due in the next 1-2 years vs. cash on hand
      - interest coverage (can the company service its debt from earnings)
      - leverage (debt/EBITDA)
    Each factor is scored 0-100 and blended with the weights below.
    """
    schedule = maturity_wall.get("schedule", {})
    near_term = (schedule.get("Year 1") or 0) + (schedule.get("Year 2") or 0)
    cash = metrics.get("cash") or 0

    # Coverage of near-term maturities by cash on hand
    if near_term <= 0:
        coverage_score = 5  # little/no near-term wall disclosed -> low risk on this axis
    else:
        ratio = cash / near_term
        coverage_score = max(0, min(100, round(100 - ratio * 60)))

    # Interest coverage: <1.5x is dangerous, >8x is very safe
    icr = metrics.get("interest_coverage_ebitda") or metrics.get("interest_coverage_ebit")
    if icr is None:
        icr_score = 50
    elif icr < 1.5:
        icr_score = 95
    elif icr >= 8:
        icr_score = 5
    else:
        icr_score = round(100 - ((icr - 1.5) / (8 - 1.5)) * 95)

    # Leverage: debt/EBITDA >6x is stressed, <1.5x is conservative
    lev = metrics.get("debt_to_ebitda")
    if lev is None:
        lev_score = 50
    elif lev <= 1.5:
        lev_score = 5
    elif lev >= 6:
        lev_score = 95
    else:
        lev_score = round(((lev - 1.5) / (6 - 1.5)) * 90 + 5)

    blended = round(coverage_score * 0.4 + icr_score * 0.35 + lev_score * 0.25)

    if blended >= 70:
        band = "Elevated"
    elif blended >= 40:
        band = "Moderate"
    else:
        band = "Low"

    return {
        "score": blended,
        "band": band,
        "components": {
            "near_term_coverage": coverage_score,
            "interest_coverage": icr_score,
            "leverage": lev_score,
        },
        "near_term_maturities": near_term,
        "cash_on_hand": cash,
    }


def build_dashboard(ticker: str) -> dict[str, Any]:
    company = lookup_ticker(ticker)
    if not company:
        return {"error": f"No SEC-registered company found for ticker '{ticker}'."}

    cik = company["cik"]
    maturity_wall = get_debt_maturity_wall(cik)
    credit = get_credit_metrics(cik)
    risk = score_refinancing_risk(maturity_wall, credit["metrics"])

    return {
        "ticker": ticker.upper(),
        "company": company["title"],
        "cik": cik,
        "maturity_wall": maturity_wall,
        "credit_metrics": credit["metrics"],
        "raw_facts": credit["raw"],
        "refinancing_risk": risk,
    }
