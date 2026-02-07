from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import requests
import time

app = FastAPI()

# Разрешаем запросы с фронтенда
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Простое кэширование (чтобы не спамить Fragment API)
CACHE = {}
CACHE_TTL = 30  # 30 секунд


def cache_get(key):
    if key in CACHE:
        value, timestamp = CACHE[key]
        if time.time() - timestamp < CACHE_TTL:
            return value
    return None


def cache_set(key, value):
    CACHE[key] = (value, time.time())


# 🔥 ПРОКСИ — оставляем как есть
@app.get("/proxy")
def proxy(url: str = Query(...)):
    try:
        r = requests.get(url, timeout=10)
        return Response(
            content=r.content,
            status_code=r.status_code,
            media_type=r.headers.get("content-type", "application/octet-stream"),
            headers={"Access-Control-Allow-Origin": "*"}
        )
    except Exception as e:
        return {"error": "Proxy error", "message": str(e)}


# Получение данных одного подарка
def fetch_gift(gift_id):
    url = f"https://fragment.com/api/v1/gifts/{gift_id}"
    cached = cache_get(url)
    if cached:
        return cached

    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        return None

    data = r.json()
    cache_set(url, data)
    return data


# Поиск подарков по фильтрам
def search_fragment(params):
    url = "https://fragment.com/api/v1/gifts"
    cached = cache_get(str(params))
    if cached:
        return cached

    r = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        return []

    data = r.json()
    cache_set(str(params), data)
    return data


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/gift/{gift_id}")
def get_gift(gift_id: int):
    data = fetch_gift(gift_id)
    if not data:
        return {"error": "Gift not found"}

    return {
        "id": data.get("id"),
        "owner": data.get("owner"),
        "model": data.get("model"),
        "backdrop": data.get("backdrop"),
        "symbol": data.get("symbol"),
    }


# ⭐⭐⭐ ПРАВИЛЬНЫЙ ENDPOINT — ВСЯ КОЛЛЕКЦИЯ ⭐⭐⭐
@app.get("/collection/{slug}")
def get_collection(slug: str):
    """
    slug = berrybox / stellarrocket / goldenstar / ...
    """
    # ❗ ПРАВИЛЬНЫЙ fragment API
    url = f"https://fragment.com/api/v1/gifts?collection={slug}&limit=100000"

    cached = cache_get(url)
    if cached:
        return cached

    try:
        r = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"
        })

        if r.status_code != 200:
            return {"error": "Fragment error", "status": r.status_code}

        data = r.json()

        # fragment API возвращает объект вида:
        # { "gifts": [ ... ] }
        items = data.get("gifts", [])

        cache_set(url, items)
        return items

    except Exception as e:
        return {"error": "Server error", "message": str(e)}


# ⭐ Оставляем твой старый поиск (он пригодится)
@app.get("/search")
def search(
    collection: str = Query("", alias="collection"),
    model: str = Query("", alias="model"),
    backdrop: str = Query("", alias="backdrop"),
    symbol: str = Query("", alias="symbol"),
    number: str = Query("", alias="number"),
):
    params = {}

    if collection:
        params["collection"] = collection
    if model:
        params["model"] = model
    if backdrop:
        params["backdrop"] = backdrop
    if symbol:
        params["symbol"] = symbol
    if number:
        params["number"] = number

    if number:
        gift = fetch_gift(number)
        if not gift:
            return []
        return [{
            "id": gift.get("id"),
            "owner": gift.get("owner"),
            "model": gift.get("model"),
            "backdrop": gift.get("backdrop"),
            "symbol": gift.get("symbol"),
        }]

    results = search_fragment(params)

    output = []
    for g in results:
        output.append({
            "id": g.get("id"),
            "owner": g.get("owner"),
            "model": g.get("model"),
            "backdrop": g.get("backdrop"),
            "symbol": g.get("symbol"),
        })

    return output
