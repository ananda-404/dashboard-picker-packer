import socket
import xmlrpc.client
from datetime import datetime

import pandas as pd
import streamlit as st

from logic import OUTLETS, WIB, fetch_rows, summarize

socket.setdefaulttimeout(120)
st.set_page_config(page_title="Produktivitas Picker & Packer", layout="wide")
st.title("Produktivitas Picker & Packer")


def odoo_conn():
    c = st.secrets["odoo"]
    common = xmlrpc.client.ServerProxy(f"{c['url']}/xmlrpc/2/common")
    uid = common.authenticate(c["db"], c["user"], c["api_key"], {})
    if not uid:
        raise RuntimeError("Login Odoo gagal: cek db, user, atau API key di Secrets.")
    models = xmlrpc.client.ServerProxy(f"{c['url']}/xmlrpc/2/object")

    def call(model, method, *args, **kw):
        return models.execute_kw(c["db"], uid, c["api_key"], model, method, list(args), kw)
    return call


@st.cache_data(ttl=300, show_spinner="Mengambil data dari Odoo...")
def load(start, end):
    return fetch_rows(odoo_conn(), start, end)


# ---------- Penyimpanan jam kerja (Google Sheets, opsional) ----------
def storage_on():
    return "gcp_service_account" in st.secrets and "jam_kerja_sheet_id" in st.secrets


def sheet():
    import gspread
    gc = gspread.service_account_from_dict(dict(st.secrets["gcp_service_account"]))
    sh = gc.open_by_key(st.secrets["jam_kerja_sheet_id"])
    try:
        return sh.worksheet("jam_kerja")
    except gspread.WorksheetNotFound:
        return sh.add_worksheet("jam_kerja", 2000, 3)


if "jam" not in st.session_state:
    st.session_state.jam = {}
    if storage_on():
        try:
            for r in sheet().get_all_records():
                st.session_state.jam[(str(r["tanggal"]), r["user"])] = float(r["jam"] or 0)
        except Exception as ex:
            st.sidebar.warning(f"Gagal membaca jam kerja dari Google Sheets: {ex}")

# ---------- Sidebar ----------
today = (datetime.utcnow() + WIB).date()
pick = st.sidebar.date_input("Tanggal (pilih 1 hari atau rentang)", (today, today))
if isinstance(pick, (list, tuple)):
    start, end = (pick[0], pick[-1])
else:
    start = end = pick

if st.sidebar.button("Segarkan data"):
    st.cache_data.clear()
if st.sidebar.button("Cek koneksi Odoo"):
    try:
        odoo_conn()
        st.sidebar.success("Koneksi dan login Odoo berhasil.")
    except Exception as ex:
        st.sidebar.error(f"Koneksi gagal: {ex}")

if st.sidebar.button("Simpan jam kerja"):
    if not storage_on():
        st.sidebar.error("Penyimpanan Google Sheets belum diatur di Secrets.")
    else:
        try:
            rows = [[k[0], k[1], v] for k, v in sorted(st.session_state.jam.items())]
            ws = sheet()
            ws.clear()
            ws.update(values=[["tanggal", "user", "jam"]] + rows, range_name="A1",
                      value_input_option="RAW")
            st.sidebar.success("Jam kerja tersimpan.")
        except Exception as ex:
            st.sidebar.error(f"Gagal menyimpan: {ex}")
if not storage_on():
    st.sidebar.caption("Jam kerja belum bisa disimpan permanen (Google Sheets belum diatur).")

# ---------- Data ----------
try:
    df = load(start, end)
except Exception as ex:
    st.error(f"Gagal mengambil data dari Odoo: {ex}")
    st.stop()
if df.empty:
    st.info("Tidak ada data Pick/Pack pada tanggal ini.")
    st.stop()
st.caption(f"Periode {start} s/d {end} (WIB). Outlet: marketplace kosong dihitung Website.")


def section(role):
    t = summarize(df, role)
    if t.empty:
        st.info(f"Tidak ada data {role}.")
        return
    inp = t[["Tanggal", "Nama"]].copy()
    inp["Jam Kerja"] = [st.session_state.jam.get((str(a), b), 0.0) for a, b in zip(t["Tanggal"], t["Nama"])]
    with st.expander(f"Input jam kerja {role}", expanded=False):
        ed = st.data_editor(
            inp, key=f"ed_{role}", hide_index=True, use_container_width=True,
            disabled=["Tanggal", "Nama"],
            column_config={"Jam Kerja": st.column_config.NumberColumn(min_value=0.0, max_value=24.0, step=0.25)},
        )
    for a, b, j in zip(ed["Tanggal"], ed["Nama"], ed["Jam Kerja"]):
        st.session_state.jam[(str(a), b)] = float(j) if pd.notna(j) else 0.0
    t["Jam Kerja"] = ed["Jam Kerja"].fillna(0).astype(float).values
    t["Pcs/Jam"] = (t["Total Pcs"] / t["Jam Kerja"].where(t["Jam Kerja"] > 0)).round(1)

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Order", int(t["Total Order"].sum()))
    c2.metric("Total Pcs", int(t["Total Pcs"].sum()))
    ok = t[t["Jam Kerja"] > 0]
    c3.metric("Rata-rata Pcs/Jam", round(ok["Total Pcs"].sum() / ok["Jam Kerja"].sum(), 1) if len(ok) else "-")

    st.dataframe(t, hide_index=True, use_container_width=True)
    st.caption("Pcs/Jam kosong = jam kerja belum diisi.")
    st.subheader("Pcs per outlet")
    st.bar_chart(t.groupby("Nama")[[f"Pcs {o}" for o in OUTLETS]].sum())
    if role == "Packer":
        st.subheader("Pcs per jam (waktu proses)")
        hourly = df[df["role"] == "Packer"].groupby("jam")["qty"].sum().reindex(range(24), fill_value=0)
        st.bar_chart(hourly)
    else:
        st.caption("Tren per jam tidak ditampilkan untuk picker karena validasi dilakukan per batch.")


tab_picker, tab_packer = st.tabs(["Picker", "Packer"])
with tab_picker:
    section("Picker")
with tab_packer:
    section("Packer")
