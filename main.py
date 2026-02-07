import os
import time
import sqlite3
from typing import List

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DB_PATH = "nft_index.db"
TONAPI_KEY = os.getenv("TONAPI_KEY", "")  # можешь не ставить, но лучше поставить
TONAPI_BASE = "https://tonapi.io/v2"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS collections (
            slug TEXT PRIMARY KEY,
            address TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS nfts (
            slug TEXT NOT NULL,
            id INTEGER NOT NULL,
            nft_address TEXT NOT NULL,
            owner_address TEXT,
            updated_at INTEGER,
            PRIMARY KEY (slug, id)
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


def tonapi_get(path: str, params=None):
    headers = {"Accept": "application/json"}
    if TONAPI_KEY:
        headers["Authorization"] = f"Bearer {TONAPI_KEY}"

    url = f"{TONAPI_BASE}{path}"
    r = requests.get(url, params=params or {}, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()


def sync_collection(slug: str, collection_address: str):
    """
    Тянем ВСЮ коллекцию из TON API и кладём в SQLite.
    Предполагаем, что id = index + 1.
    """
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "INSERT OR REPLACE INTO collections (slug, address) VALUES (?, ?)",
        (slug, collection_address),
    )
    conn.commit()

    limit = 1000
    offset = 0
    total = 0

    while True:
        data = tonapi_get(
            f"/nfts/collections/{collection_address}/items",
            params={"limit": limit, "offset": offset},
        )

        items = data.get("nft_items") or data.get("items") or []
        if not items:
            break

        now = int(time.time())

        for it in items:
            index = it.get("index")
            address = it.get("address")
            owner = (it.get("owner") or {}).get("address")

            if index is None or not address:
                continue

            gift_id = index + 1  # id = index + 1

            cur.execute(
                """
                INSERT OR REPLACE INTO nfts (slug, id, nft_address, owner_address, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (slug, gift_id, address, owner, now),
            )
            total += 1

        conn.commit()
        offset += limit

    conn.close()
    return total


def refresh_owners(slug: str, ids: List[int]):
    """
    Обновляем владельцев для конкретных id через batch TON API.
    """
    if not ids:
        return

    conn = get_db()
    cur = conn.cursor()

    q_marks = ",".join("?" for _ in ids)
    cur.execute(
        f"SELECT id, nft_address FROM nfts WHERE slug = ? AND id IN ({q_marks})",
        (slug, *ids),
    )
    rows = cur.fetchall()
    if not rows:
        conn.close()
        return

    addr_by_id = {row["id"]: row["nft_address"] for row in rows}
    addresses = list(addr_by_id.values())

    payload = {"addresses": addresses}
    headers = {"Accept": "application/json"}
    if TONAPI_KEY:
        headers["Authorization"] = f"Bearer {TONAPI_KEY}"

    r = requests.post(
        f"{TONAPI_BASE}/nfts/_bulk",
        json=payload,
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()

    now = int(time.time())
    items = data.get("nft_items") or data.get("nfts") or []

    owner_by_addr = {}
    for it in items:
        addr = it.get("address")
        owner = (it.get("owner") or {}).get("address")
        if addr:
            owner_by_addr[addr] = owner

    for gift_id, nft_addr in addr_by_id.items():
        owner = owner_by_addr.get(nft_addr)
        cur.execute(
            """
            UPDATE nfts
            SET owner_address = ?, updated_at = ?
            WHERE slug = ? AND id = ?
            """,
            (owner, now, slug, gift_id),
        )

    conn.commit()
    conn.close()


class SyncRequest(BaseModel):
    slug: str
    collection_address: str


class OwnersRequest(BaseModel):
    slug: str
    ids: List[int]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/sync")
def sync(req: SyncRequest):
    """
    Один раз дергаешь для коллекции:
    slug = "berrybox"
    collection_address = "EQC..."
    """
    total = sync_collection(req.slug, req.collection_address)
    return {"status": "ok", "synced": total}


@app.post("/owners")
def owners(req: OwnersRequest):
    """
    Фронт шлёт slug + список id (после фильтрации локального JSON),
    backend возвращает владельцев.
    """
    ids = list(set(req.ids))
    if not ids:
        return []

    refresh_owners(req.slug, ids)

    conn = get_db()
    cur = conn.cursor()
    q_marks = ",".join("?" for _ in ids)
    cur.execute(
        f"""
        SELECT id, owner_address
        FROM nfts
        WHERE slug = ? AND id IN ({q_marks})
        """,
        (req.slug, *ids),
    )
    rows = cur.fetchall()
    conn.close()

    out = []
    for row in rows:
        out.append(
            {
                "id": row["id"],
                "owner_address": row["owner_address"],
            }
        )

    return out
