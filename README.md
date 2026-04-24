# LEMNI Price History App

A small Flask + SQLite + Chart.js app for storing and displaying LEMNI price history.

## Local setup

```bat
cd /d "D:\AI Development\LEMNI Chart"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

## Files

- `app.py` - Flask app, SQLite database setup, GeckoTerminal fetcher, API routes
- `lemni_price_seed.csv` - trusted starting price history from Google Sheets
- `lemni_prices.sqlite` - created automatically when the app first runs
- `templates/index.html` - page shell
- `static/app.js` - Chart.js range buttons and chart rendering
- `static/style.css` - mobile/desktop styling
- `requirements.txt` - Python packages
- `Procfile` - Railway/GitHub deployment command

## API endpoints

- `/api/status`
- `/api/history?range=1D`
- `/api/history?range=5D`
- `/api/history?range=1M`
- `/api/history?range=6M`
- `/api/history?range=YTD`
- `/api/history?range=1Y`
- `/api/history?range=5Y`
- `POST /api/refresh`
