from datetime import datetime, timedelta

import pandas as pd

WIB = timedelta(hours=7)  # Odoo menyimpan UTC; Indonesia (WIB) = UTC+7
FMT = "%Y-%m-%d %H:%M:%S"
WAREHOUSES = ["PGM-LB-SHPE", "PGM-LB-TKTK", "PGM-LB-OL"]
OUTLETS = ["Shopee", "TikTok", "Website"]
COLS = ["tanggal", "jam", "user", "role", "order", "qty", "lokasi", "outlet"]


def _chunks(ids, n=1000):
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


def fetch_rows(call, start, end):
    """Ambil baris Pick/Pack selesai pada rentang tanggal WIB [start, end]."""
    types = call(
        "stock.picking.type", "search_read",
        [("sequence_code", "in", ["PICK", "PACK"]),
         ("warehouse_id.name", "in", WAREHOUSES)],
        fields=["sequence_code"], context={"active_test": False},
    )
    role = {t["id"]: ("Picker" if t["sequence_code"] == "PICK" else "Packer") for t in types}
    if not role:
        raise RuntimeError("Tipe operasi Pick/Pack untuk gudang SHPE/TKTK/OL tidak ditemukan.")

    s = (datetime.combine(start, datetime.min.time()) - WIB).strftime(FMT)
    e = (datetime.combine(end, datetime.min.time()) + timedelta(days=1) - WIB).strftime(FMT)
    ids = call("stock.move.line", "search",
               [("state", "=", "done"), ("date", ">=", s), ("date", "<", e),
                ("picking_id.picking_type_id", "in", list(role))])
    if not ids:
        return pd.DataFrame(columns=COLS)

    lines = []
    for ch in _chunks(ids):
        lines += call("stock.move.line", "read", ch,
                      fields=["picking_id", "qty_done", "location_id", "date", "write_uid"])

    pids = list({l["picking_id"][0] for l in lines if l.get("picking_id")})
    pk = {}
    for ch in _chunks(pids):
        for p in call("stock.picking", "read", ch, fields=["name", "picking_type_id", "sale_id"]):
            pk[p["id"]] = p

    sids = list({p["sale_id"][0] for p in pk.values() if p.get("sale_id")})
    mk = {}
    for ch in _chunks(sids):
        for so in call("sale.order", "read", ch, fields=["marketplace"]):
            mk[so["id"]] = so.get("marketplace")

    rows = []
    for l in lines:
        p = pk.get(l["picking_id"][0]) if l.get("picking_id") else None
        if not p or not p.get("picking_type_id"):
            continue
        r = role.get(p["picking_type_id"][0])
        if not r:
            continue
        sale = p.get("sale_id")
        mp = mk.get(sale[0]) if sale else None
        outlet = {"shopee": "Shopee", "tiktok": "TikTok"}.get(mp or "", "Website")
        local = datetime.strptime(l["date"], FMT) + WIB
        rows.append({
            "tanggal": local.date(), "jam": local.hour,
            "user": l["write_uid"][1] if l.get("write_uid") else "-",
            "role": r,
            "order": sale[1] if sale else p["name"],
            "qty": l.get("qty_done") or 0,
            "lokasi": l["location_id"][1] if l.get("location_id") else "-",
            "outlet": outlet,
        })
    return pd.DataFrame(rows, columns=COLS)


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
