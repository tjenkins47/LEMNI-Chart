LEMNI Chart Background Fetcher Update

Copy these files into D:\AI Development\LEMNI Chart and replace the existing files when prompted.

Changed files:
- app.py
- templates/index.html
- static/app.js
- static/style.css

Run locally:
cd /d "D:\AI Development\LEMNI Chart"
.venv\Scripts\activate
python app.py

Open:
http://127.0.0.1:5005

Default background fetch interval: 15 minutes.
To change it temporarily in Command Prompt before running the app:
set FETCH_INTERVAL_MINUTES=5
python app.py

The app stores each fetched price in lemni_prices.sqlite and logs each fetch in the fetch_log table.
