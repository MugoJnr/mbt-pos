# MugoByte Payments — Cloudflare Worker

Topology: `MBT POS --HTTPS--> payments.mugobyte.com --→ Safaricom Daraja`

Daraja Consumer Secret / Passkey live **only** in Worker secrets. Shop PCs never receive them.

## Behaviour

- STK initiate posts real Lipa Na M-Pesa Online when secrets + merchant `shortcode` + `stk_enabled` are set.
- Password = `Base64(Shortcode + Passkey + Timestamp)` (Africa/Nairobi timestamp).
- STK query calls Daraja `/mpesa/stkpushquery/v1/query` then updates D1.
- Callbacks: `/v1/webhooks/daraja/stk`, `/v1/webhooks/daraja/c2b/validation`, `/v1/webhooks/daraja/c2b/confirmation`.
- C2B maps `BusinessShortCode` → `merchant_profiles.shortcode|till_number|paybill_number`.
- `ALLOW_MOCK_STK=1` (sandbox var) allows mock checkout IDs when secrets are missing — **disable in production**.

## Deploy

```bash
cd cloud/payments-worker
npx wrangler login
npx wrangler d1 create mbt-payments
# paste database_id into wrangler.toml
npx wrangler d1 migrations apply mbt-payments --remote
npx wrangler secret put DARAJA_CONSUMER_KEY
npx wrangler secret put DARAJA_CONSUMER_SECRET
npx wrangler secret put DARAJA_PASSKEY
npx wrangler secret put DARAJA_SHORTCODE
npx wrangler secret put ADMIN_TOKEN
npx wrangler deploy
```

Then DNS: CNAME `payments` → `<worker>.<account>.workers.dev` (or Workers custom domain), set `PUBLIC_BASE_URL=https://payments.mugobyte.com`, set `ALLOW_MOCK_STK=0`, re-deploy.

Seed a merchant profile:

```bash
curl -X POST https://payments.mugobyte.com/v1/admin/merchant-profiles \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"shop_id":"SHOP_ID","business_name":"Mama Milanoi","shortcode":"174379","till_number":"","stk_enabled":true,"c2b_enabled":true,"environment":"sandbox"}'
```
