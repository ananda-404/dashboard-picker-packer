import hashlib
import re
import socket
import time
import xmlrpc.client
from datetime import datetime, time as dtime

import pandas as pd
import streamlit as st

from theme import THEMES, build_css, neon_theme, palette, style_table
from logic import OUTLETS, WIB, fetch_rows, summarize, to_excel, verify_password

socket.setdefaulttimeout(120)
st.set_page_config(page_title="Produktivitas Picker & Packer", layout="wide")

# ---------- Tema ----------
_names = list(THEMES)
_q = st.query_params.get("tema")
tema = st.sidebar.selectbox("Tema tampilan", _names, index=_names.index(_q) if _q in _names else 0)
st.query_params["tema"] = tema
if tema == "Futuristik (Neon)":
    _w = st.query_params.get("warna", "00e5ff")
    _w = "#" + (_w if re.fullmatch(r"[0-9a-fA-F]{6}", _w or "") else "00e5ff")
    c1 = st.sidebar.color_picker("Warna neon utama (bebas pilih)", _w)
    st.query_params["warna"] = c1.lstrip("#")
    oto = st.sidebar.checkbox("Warna kedua & ketiga otomatis", value=True)
    if oto:
        c2 = c3 = None
    else:
        c2 = st.sidebar.color_picker("Warna neon kedua", "#ff2bd6")
        c3 = st.sidebar.color_picker("Warna neon ketiga", "#7c4dff")
    # warna bawaan (cyan) memakai tampilan neon biru asli
    T = THEMES[tema] if (c1.lower() == "#00e5ff" and oto) else neon_theme(c1, c2, c3)
else:
    T = THEMES[tema]
st.markdown(f"<style>{build_css(T)}</style>", unsafe_allow_html=True)
@st.cache_resource
def shared_store():
    """Jam kerja, remarks, dan nama tampilan: bertahan saat halaman dimuat ulang dan dipakai bersama semua
    pengguna, tetapi hilang jika aplikasi restart (misalnya saat kode diperbarui)."""
    return {"jam": {}, "remarks": {}, "alias": {}}


@st.cache_resource
def _failures():
    return {}


def login_gate():
    user = st.session_state.get("auth_user")
    if user:
        st.sidebar.caption(f"Login sebagai {user}")
        if st.sidebar.button("Logout"):
            del st.session_state["auth_user"]
            st.rerun()
        return True
    st.title("Login")
    with st.form("login"):
        email = st.text_input("Email").strip().lower()
        pw = st.text_input("Password", type="password")
        go = st.form_submit_button("Masuk")
    if go:
        users = {str(k).lower(): v for k, v in st.secrets.get("users", {}).items()}
        if not users:
            st.error("Belum ada pengguna di Secrets (bagian [users]).")
            return False
        fails = _failures()
        n, until = fails.get(email, (0, 0.0))
        if time.time() < until:
            st.error("Terlalu banyak percobaan gagal. Coba lagi 5 menit lagi.")
            return False
        if verify_password(pw, users.get(email, "")):
            fails.pop(email, None)
            st.session_state["auth_user"] = email
            st.rerun()
        n += 1
        fails[email] = (n, time.time() + 300 if n >= 5 else 0.0)
        st.error("Email atau password salah.")
    return False


if not login_gate():
    st.stop()
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


@st.cache_data(ttl=3600, max_entries=20, show_spinner="Mengambil data dari Odoo...")
def load(start, end, version=5, bucket=0):  # naikkan 'version' tiap ada perubahan logic.py agar cache lama tidak dipakai
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
    st.session_state.jam = shared_store()["jam"]
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

_ja, _jb = st.sidebar.columns(2)
jam_mulai = _ja.time_input("Dari jam", dtime(0, 0), step=60)
jam_selesai = _jb.time_input("Sampai jam", dtime(23, 59), step=60)

if st.sidebar.button("Segarkan data"):
    st.cache_data.clear()
if st.sidebar.button("Cek koneksi Odoo"):
    try:
        odoo_conn()
        st.sidebar.success("Koneksi dan login Odoo berhasil.")
    except Exception as ex:
        st.sidebar.error(f"Koneksi gagal: {ex}")

if storage_on() and st.sidebar.button("Simpan jam kerja"):
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

# ---------- Refresh otomatis ----------
auto = st.sidebar.toggle("Refresh otomatis", value=True,
                         help="Matikan saat sedang mengisi jam kerja agar isian tidak terganggu.")
menit = st.sidebar.number_input("Refresh setiap (menit)", min_value=1, max_value=120, value=5, step=1,
                                disabled=not auto)
run_every = int(menit) * 60 if auto else None


@st.fragment(run_every=run_every)
def dashboard():
    # ---------- Data ----------
    bucket = int(time.time() // ((int(menit) if auto else 5) * 60))
    try:
        df, skipped = load(start, end, 5, bucket)
    except Exception as ex:
        st.error(f"Gagal mengambil data dari Odoo: {ex}")
        return
    st.caption(f"Diperbarui {(datetime.utcnow() + WIB).strftime('%H:%M:%S')} WIB")
    if jam_mulai > jam_selesai:
        st.error("Jam mulai harus lebih awal dari jam selesai.")
        return
    sufiks = ""
    if (jam_mulai, jam_selesai) != (dtime(0, 0), dtime(23, 59)):
        sufiks = f"_{jam_mulai:%H%M}-{jam_selesai:%H%M}"
        if not df.empty:
            ts = pd.to_datetime(df["selesai"])
            menit_sel = ts.dt.hour * 60 + ts.dt.minute
            df = df[(menit_sel >= jam_mulai.hour * 60 + jam_mulai.minute) &
                    (menit_sel <= jam_selesai.hour * 60 + jam_selesai.minute)]
    if df.empty:
        st.info("Tidak ada data Pick/Pack pada tanggal dan jam yang dipilih.")
        return


    detail_slot = st.container()
    RESULT = {}
    alias = shared_store()["alias"]
    remarks = shared_store()["remarks"]

    def section(role):
        t = summarize(df, role)
        if t.empty:
            st.info(f"Tidak ada data {role}.")
            return
        t["Nama Asli"] = t["Nama"]
        sig = hashlib.md5("|".join(f"{a}|{b}" for a, b in zip(t["Tanggal"], t["Nama Asli"])).encode()).hexdigest()[:10]
        inp = pd.DataFrame({
            "Tanggal": t["Tanggal"], "Nama Asli": t["Nama Asli"],
            "Nama Tampil": [alias.get(n, n) for n in t["Nama Asli"]],
            "Jam Kerja": [st.session_state.jam.get((str(a), b), 0.0) for a, b in zip(t["Tanggal"], t["Nama Asli"])],
            "Remarks": [remarks.get((str(a), b), "") for a, b in zip(t["Tanggal"], t["Nama Asli"])],
        })
        with st.expander(f"Input jam kerja, remarks & nama {role}", expanded=False):
            ed = st.data_editor(
                inp, key=f"ed_{role}_{sig}", hide_index=True, use_container_width=True,
                disabled=["Tanggal", "Nama Asli"],
                column_config={
                    "Nama Tampil": st.column_config.TextColumn(
                        "Nama Tampil", max_chars=60, help="Ubah nama yang ditampilkan. Kosongkan untuk kembali ke nama asli."),
                    "Jam Kerja": st.column_config.NumberColumn(min_value=0.0, max_value=24.0, step=0.25),
                    "Remarks": st.column_config.TextColumn("Remarks", max_chars=300, width="large"),
                },
            )
        for i in range(len(ed)):
            d, asli = str(ed["Tanggal"].iloc[i]), ed["Nama Asli"].iloc[i]
            j = ed["Jam Kerja"].iloc[i]
            st.session_state.jam[(d, asli)] = float(j) if pd.notna(j) else 0.0
            r = ed["Remarks"].iloc[i]
            r = "" if pd.isna(r) else str(r).strip()
            if r:
                remarks[(d, asli)] = r
            else:
                remarks.pop((d, asli), None)
            nm = ed["Nama Tampil"].iloc[i]
            nm = "" if pd.isna(nm) else str(nm).strip()
            if nm != inp["Nama Tampil"].iloc[i]:  # hanya baris yang benar-benar diubah
                if nm in ("", asli):
                    alias.pop(asli, None)
                else:
                    alias[asli] = nm
        t["Nama"] = [alias.get(n, n) for n in t["Nama Asli"]]
        t["Jam Kerja"] = [st.session_state.jam.get((str(a), b), 0.0) for a, b in zip(t["Tanggal"], t["Nama Asli"])]
        t["Pcs/Jam"] = (t["Total Pcs"] / t["Jam Kerja"].where(t["Jam Kerja"] > 0)).round(1)
        t["Remarks"] = [remarks.get((str(a), b), "") for a, b in zip(t["Tanggal"], t["Nama Asli"])]
        t = t.drop(columns="Nama Asli")
        RESULT[role] = t

        c1, c2, c3 = st.columns(3)
        c1.metric("Total Order", int(t["Total Order"].sum()))
        c2.metric("Total Pcs", int(t["Total Pcs"].sum()))
        ok = t[t["Jam Kerja"] > 0]
        c3.metric("Rata-rata Pcs/Jam", round(ok["Total Pcs"].sum() / ok["Jam Kerja"].sum(), 1) if len(ok) else "-")

        st.dataframe(style_table(t, T), hide_index=True, use_container_width=True,
                     column_config={"Remarks": st.column_config.TextColumn("Remarks", width="large")})
        st.subheader("Pcs per outlet")
        o = t.groupby("Nama")[[f"Pcs {x}" for x in OUTLETS]].sum()
        o.columns = OUTLETS
        st.line_chart(o, color=[T["accent"], T["accent2"], T["accent3"]] if T else None, x_label="Nama", y_label="Pcs")
        names = list(t.groupby("Nama")["Total Pcs"].sum().sort_values(ascending=False).index)
        sel = st.multiselect(f"Tampilkan di grafik per jam ({role})", names, default=names[:8], key=f"sel_{role}")
        if not sel:
            st.info("Pilih minimal satu nama untuk menampilkan grafik per jam.")
        else:
            st.subheader("Pcs per jam, per orang")
            dfa = df.assign(user=df["user"].map(lambda u: alias.get(u, u)))
            hourly = (dfa[(dfa["role"] == role) & (dfa["user"].isin(sel))]
                      .groupby(["jam", "user"])["qty"].sum().unstack(fill_value=0)
                      .reindex(range(24), fill_value=0))
            st.line_chart(hourly, color=palette(T, hourly.shape[1]), x_label="Jam (WIB)", y_label="Pcs")

    top = st.container()
    tab_picker, tab_packer = st.tabs(["Picker", "Packer"])
    with tab_picker:
        section("Picker")
    with tab_packer:
        section("Packer")

    df_disp = df.assign(user=df["user"].map(lambda u: alias.get(u, u)))
    with detail_slot:
        with st.expander("Detail transfer (referensi & waktu selesai)"):
            st.dataframe(style_table(df_disp, T), hide_index=True, use_container_width=True)
    if RESULT:
        with top:
            st.download_button(
                "Export ke Excel",
                data=to_excel(RESULT, df_disp),
                file_name=f"produktivitas_{start}_{end}{sufiks}.xlsx",
                help="Jam kerja, remarks, dan nama tampilan yang sudah diisi ikut ter-export.",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )


dashboard()
