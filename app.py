import os
import sqlite3
from datetime import date
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import hashlib

import pandas as pd
import psycopg2
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Gestionale Nonni", layout="wide", initial_sidebar_state="expanded")

TIPOLOGIE = ["Badanti", "Bollette", "Condominio", "Varie"]

ASSETS_DIR = Path("assets")
SIDEBAR_CANDIDATES = [
    ASSETS_DIR / "nonni.png",
    ASSETS_DIR / "nonni.PNG",
    ASSETS_DIR / "nonni.jpg",
    ASSETS_DIR / "nonni.JPG",
    ASSETS_DIR / "nonni.jpeg",
    ASSETS_DIR / "nonni.JPEG",
]

st.markdown(
    """
    <style>
      html { font-size: 115%; }
    </style>
    """,
    unsafe_allow_html=True,
)

def get_database_url() -> str:
    if "DATABASE_URL" in st.secrets:
        return str(st.secrets["DATABASE_URL"])
    env = os.getenv("DATABASE_URL")
    if env:
        return env
    raise RuntimeError("DATABASE_URL non configurata (Streamlit Secrets o variabile ambiente).")

def _add_param(dsn: str, kv: str) -> str:
    if "?" in dsn:
        if kv.split("=")[0] in dsn:
            return dsn
        return dsn + "&" + kv
    return dsn + "?" + kv

def get_conn():
    dsn = get_database_url().strip()
    if "sslmode=" not in dsn:
        dsn = _add_param(dsn, "sslmode=require")
    if "connect_timeout=" not in dsn:
        dsn = _add_param(dsn, "connect_timeout=10")
    if "options=" not in dsn:
        dsn = _add_param(dsn, "options=-c statement_timeout=30000")
    return psycopg2.connect(dsn)

def record_hash(d: date, importo_cents: int, causale: str, tipologia: str, link: str | None) -> str:
    base = f"{d.isoformat()}|{importo_cents}|{causale.strip()}|{tipologia}|{(link or '').strip()}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS spese (
                    id BIGSERIAL PRIMARY KEY,
                    data DATE NOT NULL,
                    importo_cents INTEGER NOT NULL,
                    causale TEXT NOT NULL,
                    tipologia TEXT NOT NULL,
                    link TEXT,
                    rec_hash TEXT NOT NULL UNIQUE
                );
                """
            )
        conn.commit()

def insert_spesa(d: date, importo_eur: float, causale: str, tipologia: str, link: str | None):
    importo_cents = int(round(importo_eur * 100))
    h = record_hash(d, importo_cents, causale, tipologia, link)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO spese (data, importo_cents, causale, tipologia, link, rec_hash)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (rec_hash) DO NOTHING
                """,
                (d, importo_cents, causale.strip(), tipologia, (link or "").strip() or None, h),
            )
        conn.commit()

def update_spesa(spesa_id: int, d: date, importo_eur: float, causale: str, tipologia: str, link: str | None):
    importo_cents = int(round(importo_eur * 100))
    h = record_hash(d, importo_cents, causale, tipologia, link)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE spese
                SET data=%s, importo_cents=%s, causale=%s, tipologia=%s, link=%s, rec_hash=%s
                WHERE id=%s
                """,
                (d, importo_cents, causale.strip(), tipologia, (link or "").strip() or None, h, spesa_id),
            )
        conn.commit()

def delete_spesa(spesa_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM spese WHERE id=%s", (spesa_id,))
        conn.commit()

def load_spese() -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query(
            "SELECT id, data, importo_cents, causale, tipologia, link FROM spese ORDER BY data DESC, id DESC",
            conn,
        )
    if df.empty:
        return df
    df["data"] = pd.to_datetime(df["data"]).dt.date
    df["importo_eur"] = df["importo_cents"] / 100.0
    df.drop(columns=["importo_cents"], inplace=True)
    return df

LOCAL_DB_PATH = Path("data") / "spese.db"

def load_spese_from_sqlite(db_path: Path) -> pd.DataFrame:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    try:
        df = pd.read_sql_query("SELECT data, importo_cents, causale, tipologia, link FROM spese", conn)
    finally:
        conn.close()
    if df.empty:
        return df
    df["data"] = pd.to_datetime(df["data"]).dt.date
    return df

def dropbox_to_embed_url(url: str) -> str:
    try:
        p = urlparse(url)
        if "dropbox.com" not in p.netloc:
            return url
        qs = parse_qs(p.query)
        qs["dl"] = ["0"]
        new_query = urlencode(qs, doseq=True)
        return urlunparse((p.scheme, p.netloc, p.path, p.params, new_query, p.fragment))
    except Exception:
        return url

def looks_like_image(url: str) -> bool:
    u = url.lower()
    return any(u.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif"])

def looks_like_pdf(url: str) -> bool:
    return url.lower().endswith(".pdf")

def render_doc_preview(url: str, height: int = 520):
    if not url:
        return
    embed = dropbox_to_embed_url(url)
    if looks_like_image(embed):
        st.image(embed, width="stretch")
    elif looks_like_pdf(embed) or ("pdf" in embed.lower()):
        components.iframe(embed, height=height, scrolling=True)
    else:
        st.info("Anteprima non disponibile per questo tipo di link. Usa il bottone per aprirlo.")
        st.link_button("Apri documento", embed)

def sidebar_image_path() -> Path | None:
    for p in SIDEBAR_CANDIDATES:
        if p.exists():
            return p
    return None

with st.spinner("Connessione al database..."):
    try:
        init_db()
        DB_OK = True
        DB_ERR = ""
    except Exception as e:
        DB_OK = False
        DB_ERR = str(e)

st.title("Gestionale Nonni")
st.caption("Radici forti, ali libere.")

menu = st.sidebar.radio("Vai a:", ["➕ Inserisci spesa", "📊 Riepilogo e gestione", "⚙️ Impostazioni"])

img = sidebar_image_path()
if img is not None:
    st.sidebar.image(str(img), width="stretch")

if not DB_OK:
    st.error("Connessione a Supabase non riuscita.")
    st.code(DB_ERR)
    st.info("Controlla Secrets: DATABASE_URL deve essere quella del Session pooler e la password quella appena resettata.")
    st.stop()

if menu == "➕ Inserisci spesa":
    st.subheader("Inserimento record")
    with st.form("form_spesa", clear_on_submit=True):
        c1, c2 = st.columns([1, 1])
        with c1:
            d = st.date_input("Data", value=date.today())
            tipologia = st.selectbox("Tipologia", TIPOLOGIE, index=0)
        with c2:
            importo = st.number_input("Importo (€)", min_value=0.0, value=0.0, step=1.0, format="%.2f")
            causale = st.text_input("Causale", placeholder="Es. Farmaci, spesa alimentare, visita medica...")
        link = st.text_input("Link documento (Dropbox)", placeholder="Incolla qui il link condiviso...")
        submitted = st.form_submit_button("Salva")
        if submitted:
            if not causale.strip():
                st.error("La causale è obbligatoria.")
            else:
                insert_spesa(d, float(importo), causale, tipologia, link)
                st.success("Spesa salvata ✅")

    st.divider()
    st.subheader("Ultime spese inserite")
    df = load_spese()
    if df.empty:
        st.info("Nessuna spesa ancora.")
    else:
        show = df.head(20).copy()
        show["importo_eur"] = show["importo_eur"].map(lambda x: f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."))
        st.data_editor(
            show[["id", "data", "tipologia", "causale", "importo_eur", "link"]],
            width="stretch",
            hide_index=True,
            disabled=True,
            column_config={"link": st.column_config.LinkColumn("Documento", display_text="Apri")},
        )

elif menu == "📊 Riepilogo e gestione":
    st.subheader("Riepilogo e gestione record")
    df = load_spese()
    if df.empty:
        st.info("Non ci sono dati da riepilogare.")
        st.stop()

    df["anno"] = pd.to_datetime(df["data"]).dt.year
    anni = sorted(df["anno"].unique().tolist(), reverse=True)
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        anno_sel = st.selectbox("Anno", ["Tutti"] + [str(a) for a in anni], index=0)
    with c2:
        tipo_sel = st.selectbox("Tipologia", ["Tutte"] + TIPOLOGIE, index=0)
    with c3:
        search = st.text_input("Cerca nella causale", placeholder="Es. farmacia, Enel, condominio...")

    f = df.copy()
    if anno_sel != "Tutti":
        f = f[f["anno"] == int(anno_sel)]
    if tipo_sel != "Tutte":
        f = f[f["tipologia"] == tipo_sel]
    if search.strip():
        f = f[f["causale"].str.contains(search.strip(), case=False, na=False)]

    totale = float(f["importo_eur"].sum())
    st.metric("Totale uscite (filtro attivo)", f"{totale:,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."))

    st.divider()
    f_disp = f.sort_values(["data", "id"], ascending=[False, False]).copy()
    f_disp["importo_eur"] = f_disp["importo_eur"].map(lambda x: f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."))
    st.data_editor(
        f_disp[["id", "data", "tipologia", "causale", "importo_eur", "link"]],
        width="stretch",
        hide_index=True,
        disabled=True,
        column_config={"link": st.column_config.LinkColumn("Documento", display_text="Apri")},
    )

else:
    st.subheader("Impostazioni")
    df = load_spese()
    st.caption(f"Record attuali su Supabase: **{len(df)}**")

    st.divider()
    st.write("### Importa CSV (ripristino)")
    up = st.file_uploader("Carica un CSV esportato dall'app", type=["csv"])
    if up is not None:
        imp = pd.read_csv(up)
        st.write("Anteprima:", imp.head(10))
        if st.button("Importa nel database", type="primary"):
            n_ok = 0
            for _, r in imp.iterrows():
                try:
                    d = pd.to_datetime(r["data"]).date()
                    tip = str(r["tipologia"])
                    caus = str(r["causale"])
                    link = None if pd.isna(r.get("link", None)) else str(r.get("link", "")).strip()
                    impv = r.get("importo_eur", 0)
                    val = float(str(impv).replace("€", "").strip().replace(".", "").replace(",", "."))
                    insert_spesa(d, val, caus, tip, link)
                    n_ok += 1
                except Exception:
                    continue
            st.success(f"Import completato: {n_ok} righe inserite (senza duplicati).")
            st.rerun()
