"""
app.py — Flask API for the Corporate Debt Risk Dashboard.

Run:
    pip install -r requirements.txt
    python app.py
Then open http://localhost:5000 in a browser.
"""

from flask import Flask, jsonify, request, send_from_directory
import os

import sec_edgar

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")


@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/api/search")
def search():
    q = request.args.get("q", "")
    return jsonify(sec_edgar.search_companies(q))


@app.route("/api/dashboard/<ticker>")
def dashboard(ticker: str):
    try:
        data = sec_edgar.build_dashboard(ticker)
    except Exception as exc:  # surface a clean error instead of a 500 traceback
        return jsonify({"error": f"Couldn't load data for '{ticker}': {exc}"}), 502
    status = 404 if "error" in data else 200
    return jsonify(data), status


if __name__ == "__main__":
    app.run(debug=True, port=5000)
