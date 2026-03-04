import sqlite3
from datetime import date
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# -----------------------------
# CONFIG
# -----------------------------
st.set_page_config(
    page_title="Gestionale Nonni",
    layout="wide",
    initial_sidebar_state="expanded",
)

DB_DIR = Path("data")
DB_DIR.mkdir(exist_ok=True)
DB_PATH = DB_DIR / "spese.db"

TIPOLOGIE = ["Badanti", "Bollette", "Condominio", "Varie"]

# -----------------------------
# DB HELPERS
# -----------------------------
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS spese (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data TEXT NOT NULL,
                importo_cents INTEGER NOT NULL,
                causale TEXT NOT NULL,
                tipologia TEXT NOT NULL,
                link TEXT
            )
            """
        )
        conn.commit()

def insert_spesa(d: date, importo_eur: float, causale: str, tipologia: str, link: str | None):
    importo_cents = int(round(importo_eur * 100))
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO spese (data, importo_cents, causale, tipologia, link) VALUES (?, ?, ?, ?, ?)",
            (d.isoformat(), importo_cents, causale.strip(), tipologia, (link or "").strip() or None),
        )
        conn.commit()

def update_spesa(spesa_id: int, d: date, importo_eur: float, causale: str, tipologia: str, link: str | None):
    importo_cents = int(round(importo_eur * 100))
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE spese
            SET data = ?, importo_cents = ?, causale = ?, tipologia = ?, link = ?
            WHERE id = ?
            """,
            (d.isoformat(), importo_cents, causale.strip(), tipologia, (link or "").strip() or None, spesa_id),
        )
        conn.commit()

def delete_spesa(spesa_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM spese WHERE id = ?", (spesa_id,))
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

# -----------------------------
# DROPBOX HELPERS (preview)
# -----------------------------
def dropbox_to_embed_url(url: str) -> str:
    try:
        p = urlparse(url)
        if "dropbox.com" not in p.netloc:
            return url

        qs = parse_qs(p.query)
        qs["dl"] = ["0"]  # preview
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

# -----------------------------
# UI
# -----------------------------
init_db()

st.title("Gestionale Nonni")
st.caption("Radici forti, ali libere.")

menu = st.sidebar.radio("Vai a:", ["➕ Inserisci spesa", "📊 Riepilogo e gestione", "⚙️ Impostazioni"])

# ---- PAGE: INSERIMENTO ----
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
        st.dataframe(
            show[["id", "data", "tipologia", "causale", "importo_eur", "link"]],
            width="stretch",
            hide_index=True,
        )

# ---- PAGE: RIEPILOGO + GESTIONE ----
elif menu == "📊 Riepilogo e gestione":
    st.subheader("Riepilogo e gestione record")

    df = load_spese()
    if df.empty:
        st.info("Non ci sono dati da riepilogare.")
        st.stop()

    # Filtri
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

    st.write("### Totali per tipologia")
    pivot = (
        f.groupby("tipologia", as_index=False)["importo_eur"]
        .sum()
        .sort_values("importo_eur", ascending=False)
    )
    pivot["importo_eur"] = pivot["importo_eur"].map(lambda x: f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."))
    st.dataframe(pivot, width="stretch", hide_index=True)

    st.divider()

    st.write("### Elenco spese")

    f_disp = f.sort_values(["data", "id"], ascending=[False, False]).copy()
    f_disp["importo_eur"] = f_disp["importo_eur"].map(lambda x: f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."))

    # Tabella cliccabile: la colonna "Documento" diventa un link (Apri)
    st.data_editor(
        f_disp[["id", "data", "tipologia", "causale", "importo_eur", "link"]],
        width="stretch",
        hide_index=True,
        disabled=True,
        column_config={
            "link": st.column_config.LinkColumn(
                "Documento",
                help="Apri il documento collegato (Dropbox o altro).",
                display_text="Apri",
            )
        },
    )

    st.divider()

    st.write("## Gestione: modifica / elimina")

    id_list = f_disp["id"].tolist()
    sel_id = st.selectbox("Scegli il record (ID)", id_list, index=0)

    # riga originale (da f con importo numerico)
    row = f[f["id"] == sel_id].iloc[0]
    link_val = row["link"] if isinstance(row["link"], str) else ""

    col_form, col_preview = st.columns([1, 1])
    with col_form:
        with st.form("form_edit"):
            d_new = st.date_input("Data (modifica)", value=row["data"])
            tip_new = st.selectbox("Tipologia (modifica)", TIPOLOGIE, index=TIPOLOGIE.index(row["tipologia"]))
            imp_new = st.number_input("Importo (€) (modifica)", min_value=0.0, value=float(row["importo_eur"]), step=1.0, format="%.2f")
            caus_new = st.text_input("Causale (modifica)", value=str(row["causale"]))
            link_new = st.text_input("Link documento (Dropbox) (modifica)", value=str(link_val))

            cA, cB = st.columns(2)
            save = cA.form_submit_button("💾 Salva modifiche", width="stretch")
            delete = cB.form_submit_button("🗑️ Elimina", width="stretch")

            if save:
                if not caus_new.strip():
                    st.error("La causale è obbligatoria.")
                else:
                    update_spesa(int(sel_id), d_new, float(imp_new), caus_new, tip_new, link_new)
                    st.success("Modifiche salvate ✅")
                    st.rerun()

            if delete:
                delete_spesa(int(sel_id))
                st.success("Record eliminato ✅")
                st.rerun()

    with col_preview:
        st.write("### Documento")
        if link_val and str(link_val).strip():
            embed = dropbox_to_embed_url(str(link_val).strip())
            st.link_button("Apri documento", embed)
            render_doc_preview(embed)
        else:
            st.info("Nessun link documento per questo record.")

# ---- PAGE: SETTINGS ----
else:
    st.subheader("Impostazioni")
    st.write(f"**Database:** `{DB_PATH}`")

    df = load_spese()
    if df.empty:
        st.info("Nessun dato da esportare.")
    else:
        csv = df.drop(columns=["anno"], errors="ignore").to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Scarica CSV (backup)", data=csv, file_name="gestionale_nonni_backup.csv", mime="text/csv")
