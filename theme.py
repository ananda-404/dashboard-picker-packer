"""Tema tampilan dashboard (tanpa Streamlit). Tema dipilih di sidebar, diterapkan lewat CSS."""

THEMES = {
    "Futuristik (Neon)": dict(bg="#050816", sidebar="#070d24", card="#0b1230", text="#d8f3ff",
                              accent="#00e5ff", accent2="#ff2bd6", accent3="#7c4dff",
                              font="Rajdhani", head="Orbitron", grid=True, glow=True),
    "Cyberpunk": dict(bg="#0a0a0f", sidebar="#101018", card="#15151f", text="#f2f2f2",
                      accent="#fcee0a", accent2="#ff003c", accent3="#00f0ff",
                      font="Rajdhani", head="Orbitron", grid=False, glow=True),
    "Samudra": dict(bg="#06202b", sidebar="#052531", card="#0b3040", text="#e8f6f8",
                    accent="#2ec4b6", accent2="#4cc9f0", accent3="#f4d35e",
                    font="Inter", head="Poppins", grid=False, glow=False),
    "Hutan": dict(bg="#0d1f14", sidebar="#0a1a10", card="#14301f", text="#e9f5ec",
                  accent="#7bd88f", accent2="#d4e157", accent3="#4dd0e1",
                  font="Inter", head="Poppins", grid=False, glow=False),
    "Senja": dict(bg="#1b1026", sidebar="#150c1f", card="#2a1b3d", text="#f3e9ff",
                  accent="#ff9e64", accent2="#f7768e", accent3="#bb9af7",
                  font="Inter", head="Poppins", grid=False, glow=False),
    "Terang Bersih": dict(bg="#f6f8fb", sidebar="#eaeff6", card="#ffffff", text="#0f172a",
                          accent="#2563eb", accent2="#0ea5e9", accent3="#f59e0b",
                          font="Inter", head="Poppins", grid=False, glow=False),
    "Bawaan Streamlit": None,
}

_CSS = """
@import url('https://fonts.googleapis.com/css2?family=@head@:wght@600;800&family=@font@:wght@400;600&display=swap');
.stApp { background-color: @bg@; @grid@ color: @text@; font-family: '@font@', sans-serif; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stSidebar"] { background: @sidebar@; border-right: 1px solid @accent@44; }
.stApp p, .stApp label, .stApp li, .stApp span, .stApp [data-testid="stMarkdownContainer"],
.stApp [data-testid="stCaptionContainer"] { color: @text@; }
h1, h2, h3, h4 { font-family: '@head@', sans-serif !important; color: @accent@ !important; letter-spacing: .04em; }
@title@
[data-testid="stMetric"] { background: @card@; border: 1px solid @accent@66; border-radius: 14px;
  padding: 14px 18px; @glow@ }
[data-testid="stMetricValue"] { color: @accent@; font-family: '@head@', sans-serif; }
[data-testid="stMetricLabel"] p { color: @text@cc; }
.stTabs [data-baseweb="tab"] { color: @text@; }
.stTabs [aria-selected="true"] { color: @accent@; }
.stTabs [data-baseweb="tab-highlight"] { background-color: @accent@; }
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {
  background: @card@; color: @accent@; border: 1px solid @accent@; border-radius: 10px; }
.stButton > button:hover, .stDownloadButton > button:hover, [data-testid="stFormSubmitButton"] > button:hover {
  background: @accent@; color: @bg@; box-shadow: 0 0 14px @accent@88; }
[data-testid="stExpander"] { background: @card@; border: 1px solid @accent@44; border-radius: 12px; }
[data-baseweb="input"] > div, [data-baseweb="select"] > div, [data-baseweb="base-input"] { background: @card@ !important; }
input { color: @text@ !important; }
"""


def build_css(T):
    if not T:
        return ""
    grid = ("background-image: linear-gradient(@accent@14 1px, transparent 1px), "
            "linear-gradient(90deg, @accent@14 1px, transparent 1px); background-size: 42px 42px;"
            if T["grid"] else "")
    title = ("h1 { background: linear-gradient(90deg, @accent@, @accent2@); -webkit-background-clip: text;"
             " -webkit-text-fill-color: transparent; text-shadow: none; font-weight: 800; }"
             if T["glow"] else "")
    glow = "box-shadow: 0 0 18px @accent@33, inset 0 0 12px @accent@11;" if T["glow"] else ""
    css = _CSS.replace("@grid@", grid).replace("@title@", title).replace("@glow@", glow)
    for k, v in T.items():
        css = css.replace(f"@{k}@", str(v))
    return css


def style_table(df, T):
    """Beri warna sel tabel sesuai tema (tabel Streamlit tidak ikut CSS)."""
    if not T or df.empty or df.size > 100000:
        return df

    def fmt(v):
        if isinstance(v, str):
            return v
        if isinstance(v, float):
            return f"{v:g}"
        return str(v)

    return (df.style.set_properties(**{"background-color": T["card"], "color": T["text"]})
            .format(fmt, na_rep="-"))


EXTRA = ["#ffd166", "#06d6a0", "#ef476f", "#118ab2", "#f78c6b", "#c77dff",
         "#80ed99", "#4cc9f0", "#f72585", "#b5e48c", "#ffb703", "#8ecae6"]


def palette(T, n):
    """Daftar warna untuk n garis (aksen tema dulu, lalu warna tambahan; berulang jika lebih banyak)."""
    base = ([T["accent"], T["accent2"], T["accent3"]] if T else []) + EXTRA
    return [base[i % len(base)] for i in range(n)]
