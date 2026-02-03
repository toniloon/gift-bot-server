from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import sqlite3

app = FastAPI()

conn = sqlite3.connect("nfts.db", check_same_thread=False)
conn.execute('''
CREATE TABLE IF NOT EXISTS nfts (
    id INTEGER PRIMARY KEY,
    model TEXT,
    bg_color TEXT,
    symbol TEXT,
    owner TEXT
)
''')
conn.commit()

@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <html>
    <body style="font-family:sans-serif">
        <h2>Поиск NFT подарков</h2>
        <form action="/search">
            Модель: <input name="model"><br>
            Цвет фона: <input name="bg"><br>
            <button type="submit">Искать</button>
        </form>
    </body>
    </html>
    """

@app.get("/search")
def search(model: str = "", bg: str = ""):
    q = "SELECT * FROM nfts WHERE 1=1"
    params = []

    if model:
        q += " AND model=?"
        params.append(model)
    if bg:
        q += " AND bg_color=?"
        params.append(bg)

    rows = conn.execute(q, params).fetchall()
    return {"results": rows}
