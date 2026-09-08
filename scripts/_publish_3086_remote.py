from backend.cloud.update_center import UpdateCenter

c = UpdateCenter()
r = c.publish_update(
    version="3.0.86",
    download_url="https://github.com/MugoJnr/mbt-pos/releases/download/v3.0.86/MBT_POS_Setup.exe",
    checksum="eee8c46044d5b4efc9264af5cb9767e802a41315dbe8bcdf1eb80e75369e000a",
    release_notes=(
        "MBT POS v3.0.86: shop-floor inventory access and honest permission UI. "
        "Cashiers Add Product + Receive Stock; cost/categories/delete/adjust/export "
        "gated with reasons; backdate and debt write-off remain Super-Admin PIN."
    ),
    is_mandatory=False,
)
print("OK" if r else "FAIL")
if r:
    print(r.get("version"), (r.get("checksum_sha256") or "")[:20])
