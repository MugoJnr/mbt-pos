from backend.cloud.update_center import UpdateCenter

c = UpdateCenter()
r = c.publish_update(
    version="3.0.87",
    download_url="https://github.com/MugoJnr/mbt-pos/releases/download/v3.0.87/MBT_POS_Setup.exe",
    checksum="ffb87b5f1335448d47aa75bb520f23c74a84ac8ff9654a633eb445ee865bcb43",
    release_notes=(
        "MBT POS v3.0.87: web Super Admin elevated actions. "
        "Cashiers blocked from inventory export/cost/valuation nav; "
        "SA Adjust, write-off (PIN), Users & Access, Receive on web."
    ),
    is_mandatory=False,
)
print("OK" if r else "FAIL")
if r:
    print(r.get("version"), (r.get("checksum_sha256") or "")[:20])
