from datetime import datetime, timedelta

import pandas as pd

WIB = timedelta(hours=7)  # Odoo menyimpan UTC; Indonesia (WIB) = UTC+7
FMT = "%Y-%m-%d %H:%M:%S"
WAREHOUSES = ["PGM-LB-SHPE", "PGM-LB-TKTK", "PGM-LB-OL"]
OUTLETS = ["Shopee", "TikTok", "Website"]
COLS = ["tanggal", "jam", "user", "role", "order", "qty", "lokasi", "outlet", "ref", "selesai"]


def _chunks(ids, n=1000):
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


def fetch_rows(call, start, end):
    """Ambil transfer PICK/PACK berstatus Done yang Date of Transfer-nya jatuh di [start, end] (WIB).
    Return (DataFrame, jumlah transfer yang dikecualikan karena referensi bukan PICK/PACK)."""
    types = call(
        "stock.picking.type", "search_read",
        [("sequence_code", "in", ["PICK", "PACK"]),
         ("warehouse_id.name", "in", WAREHOUSES)],
        fields=["sequence_code"], context={"active_test": False},
    )
    tids = [t["id"] for t in types]
    if not tids:
        raise RuntimeError("Tipe operasi Pick/Pack untuk gudang SHPE/TKTK/OL tidak ditemukan.")

    s = (datetime.combine(start, datetime.min.time()) - WIB).strftime(FMT)
    e = (datetime.combine(end, datetime.min.time()) + timedelta(days=1) - WIB).strftime(FMT)
    picks = call("stock.picking", "search_read",
                 [("state", "=", "done"), ("date_done", ">=", s), ("date_done", "<", e),
                  ("picking_type_id", "in", tids)],
                 fields=["name", "origin", "sale_id", "user_id", "date_done"])

    pk, skipped = {}, 0
    for p in picks:
        nm = (p.get("name") or "").upper()
        txt = nm + " " + (p.get("origin") or "").upper()
        if "RETURN OF" in txt or "WAITING" in txt:
            skipped += 1  # retur / waiting tidak dihitung
            continue
        if "/PICK/" in nm:
            p["role"] = "Picker"
        elif "/PACK/" in nm:
            p["role"] = "Packer"
        else:
            skipped += 1  # INT, OUT, dll.
            continue
        pk[p["id"]] = p
    if not pk:
        return pd.DataFrame(columns=COLS), skipped

    lines = []
    for ch in _chunks(list(pk)):
        lines += call("stock.move.line", "search_read",
                      [("picking_id", "in", ch), ("state", "=", "done")],
                      fields=["picking_id", "qty_done", "location_id", "write_uid"])

    sids = list({p["sale_id"][0] for p in pk.values() if p.get("sale_id")})
    mk = {}
    for ch in _chunks(sids):
        for so in call("sale.order", "read", ch, fields=["marketplace"]):
            mk[so["id"]] = so.get("marketplace")

    rows = []
    for l in lines:
        p = pk.get(l["picking_id"][0]) if l.get("picking_id") else None
        if not p:
            continue
        sale = p.get("sale_id")
        mp = mk.get(sale[0]) if sale else None
        outlet = {"shopee": "Shopee", "tiktok": "TikTok"}.get(mp or "", "Website")
        who = p.get("user_id") or l.get("write_uid")  # Responsible di transfer; cadangan: user terakhir yang mengubah baris
        local = datetime.strptime(p["date_done"], FMT) + WIB  # waktu selesai transfer
        if not (start <= local.date() <= end):
            continue  # pengaman: hanya transfer yang selesai di rentang tanggal terpilih
        rows.append({
            "tanggal": local.date(), "jam": local.hour,
            "user": who[1] if who else "-",
            "role": p["role"],
            "order": sale[1] if sale else p["name"],
            "qty": l.get("qty_done") or 0,
            "lokasi": l["location_id"][1] if l.get("location_id") else "-",
            "outlet": outlet,
            "ref": p["name"], "selesai": local.strftime(FMT),
        })
    return pd.DataFrame(rows, columns=COLS), skipped


def summarize(df, role):
    """Ringkasan per tanggal + nama. Packer tidak punya kolom lokasi."""
    d = df[df["role"] == role]
    if d.empty:
        return pd.DataFrame()
    keys = ["tanggal", "user"]
    agg = {"Total Order": ("order", "nunique"), "Total Pcs": ("qty", "sum")}
    if role == "Picker":
        agg["Lokasi Unik"] = ("lokasi", "nunique")
    out = d.groupby(keys).agg(**agg).reset_index()
    for o in OUTLETS:
        x = (d[d["outlet"] == o].groupby(keys)
             .agg(**{f"Order {o}": ("order", "nunique"), f"Pcs {o}": ("qty", "sum")})
             .reset_index())
        out = out.merge(x, on=keys, how="left")
    out = out.fillna(0).rename(columns={"tanggal": "Tanggal", "user": "Nama"})
    for c in out.columns:
        if c not in ("Tanggal", "Nama"):
            out[c] = out[c].round().astype(int)
    return out.sort_values(["Tanggal", "Total Pcs"], ascending=[True, False]).reset_index(drop=True)


def to_excel(tables, detail):
    """tables: {'Picker': df, 'Packer': df}; detail: df baris mentah. Return bytes .xlsx"""
    from io import BytesIO

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for name, t in tables.items():
            t.to_excel(w, sheet_name=name, index=False)
        d = detail.rename(columns={"tanggal": "Tanggal", "jam": "Jam", "user": "Nama", "role": "Peran",
                                   "order": "Order", "qty": "Qty", "lokasi": "Lokasi", "outlet": "Outlet",
                                   "ref": "Referensi", "selesai": "Selesai (WIB)"})
        d.to_excel(w, sheet_name="Detail", index=False)
        for ws in w.book.worksheets:
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 40)
    return buf.getvalue()
