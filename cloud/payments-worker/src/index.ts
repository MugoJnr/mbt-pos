/**
 * MugoByte Payments Worker — payments.mugobyte.com
 *
 * POS never holds Daraja secrets. "request accepted" ≠ paid.
 *
 * Daraja Lipa Na M-Pesa Online password =
 *   Base64(Shortcode + Passkey + Timestamp)  — NOT SHA-256.
 */
export interface Env {
  DB: D1Database;
  APP_ENV: string;
  DARAJA_BASE_URL: string;
  /** Public HTTPS origin for callbacks, e.g. https://payments.mugobyte.com */
  PUBLIC_BASE_URL?: string;
  /** When "1", allow mock STK if Daraja secrets missing (dev only). */
  ALLOW_MOCK_STK?: string;
  DARAJA_CONSUMER_KEY?: string;
  DARAJA_CONSUMER_SECRET?: string;
  DARAJA_PASSKEY?: string;
  DARAJA_SHORTCODE?: string;
  SHOP_JWT_SECRET?: string;
  ADMIN_TOKEN?: string;
}

type Json = Record<string, unknown>;

function json(data: Json, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
    },
  });
}

function maskPhone(phone: string): string {
  const d = String(phone || '').replace(/\D+/g, '');
  if (d.length < 6) return '***';
  return `${d.slice(0, 4)}****${d.slice(-3)}`;
}

function now(): number {
  return Date.now() / 1000;
}

/** Kenya MSISDN → 2547XXXXXXXX */
function normalizeKePhone(phone: string): string {
  let d = String(phone || '').replace(/\D+/g, '');
  if (d.startsWith('0') && d.length === 10) d = `254${d.slice(1)}`;
  if (d.startsWith('7') && d.length === 9) d = `254${d}`;
  if (d.startsWith('254') && d.length === 12) return d;
  return d;
}

/** YYYYMMDDHHmmss in Africa/Nairobi */
function darajaTimestamp(): string {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Africa/Nairobi',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).formatToParts(new Date());
  const get = (t: string) => parts.find((p) => p.type === t)?.value || '00';
  return `${get('year')}${get('month')}${get('day')}${get('hour')}${get('minute')}${get('second')}`;
}

/** Official Lipa Na M-Pesa password: Base64(Shortcode+Passkey+Timestamp) */
function lipaPassword(shortcode: string, passkey: string, timestamp: string): string {
  const raw = `${shortcode}${passkey}${timestamp}`;
  // btoa expects binary string; ASCII-safe for these inputs
  return btoa(raw);
}

function requireShop(request: Request): { shopId: string; deviceId: string } | Response {
  const shopId = request.headers.get('X-MBT-Shop-Id') || '';
  const deviceId = request.headers.get('X-MBT-Device-Id') || '';
  if (!shopId) {
    return json({ ok: false, error_code: 'AUTH', error_message: 'X-MBT-Shop-Id required' }, 401);
  }
  // JWT verification hooks in when SHOP_JWT_SECRET is configured.
  return { shopId, deviceId };
}

function requireAdmin(request: Request, env: Env): Response | null {
  const token = env.ADMIN_TOKEN || env.SHOP_JWT_SECRET || '';
  if (!token) return null; // sandbox open until ADMIN_TOKEN set
  const auth = request.headers.get('Authorization') || '';
  const got = auth.startsWith('Bearer ') ? auth.slice(7) : request.headers.get('X-MBT-Admin-Token') || '';
  if (got !== token) {
    return json({ ok: false, error_code: 'FORBIDDEN', error_message: 'Admin token required' }, 403);
  }
  return null;
}

async function getProfile(env: Env, shopId: string) {
  return env.DB.prepare('SELECT * FROM merchant_profiles WHERE shop_id = ?')
    .bind(shopId)
    .first();
}

async function findShopByShortcode(env: Env, code: string) {
  const c = String(code || '').trim();
  if (!c) return null;
  return env.DB.prepare(
    `SELECT * FROM merchant_profiles
     WHERE shortcode = ? OR till_number = ? OR paybill_number = ?
     LIMIT 1`,
  )
    .bind(c, c, c)
    .first();
}

async function darajaToken(env: Env): Promise<string | null> {
  const key = env.DARAJA_CONSUMER_KEY;
  const secret = env.DARAJA_CONSUMER_SECRET;
  if (!key || !secret) return null;
  const auth = btoa(`${key}:${secret}`);
  const url = `${env.DARAJA_BASE_URL}/oauth/v1/generate?grant_type=client_credentials`;
  const res = await fetch(url, { headers: { Authorization: `Basic ${auth}` } });
  if (!res.ok) {
    const t = await res.text().catch(() => '');
    console.error('daraja oauth failed', res.status, t.slice(0, 200));
    return null;
  }
  const body = (await res.json()) as { access_token?: string };
  return body.access_token || null;
}

function publicBase(env: Env, request: Request): string {
  const configured = (env.PUBLIC_BASE_URL || '').replace(/\/$/, '');
  if (configured) return configured;
  return new URL(request.url).origin;
}

function stkSecretsReady(env: Env, profile: Record<string, unknown>): boolean {
  const shortcode = String(profile.shortcode || env.DARAJA_SHORTCODE || '');
  const passkey = env.DARAJA_PASSKEY || '';
  return Boolean(env.DARAJA_CONSUMER_KEY && env.DARAJA_CONSUMER_SECRET && shortcode && passkey);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    if (request.method === 'GET' && (path === '/health' || path === '/healthz')) {
      return json({
        ok: true,
        service: 'mbt-payments',
        env: env.APP_ENV || 'sandbox',
        daraja_configured: Boolean(env.DARAJA_CONSUMER_KEY && env.DARAJA_CONSUMER_SECRET),
        passkey_configured: Boolean(env.DARAJA_PASSKEY),
        shortcode_configured: Boolean(env.DARAJA_SHORTCODE),
        mock_allowed: env.ALLOW_MOCK_STK === '1',
        ts: now(),
      });
    }

    // Capabilities — portable merchant profile (no secrets)
    if (request.method === 'GET' && path.match(/^\/v1\/shops\/[^/]+\/capabilities$/)) {
      const shopId = path.split('/')[3];
      const auth = requireShop(request);
      if (auth instanceof Response) return auth;
      if (auth.shopId !== shopId) {
        return json({ ok: false, error_code: 'FORBIDDEN', error_message: 'Shop mismatch' }, 403);
      }
      const profile = await getProfile(env, shopId);
      if (!profile) {
        return json({
          ok: true,
          capabilities: {
            shop_id: shopId,
            stk_enabled: false,
            c2b_enabled: false,
            environment: env.APP_ENV || 'sandbox',
          },
        });
      }
      return json({
        ok: true,
        capabilities: {
          shop_id: shopId,
          profile_id: profile.id,
          stk_enabled: Boolean(profile.stk_enabled),
          c2b_enabled: Boolean(profile.c2b_enabled),
          till_number: profile.till_number || '',
          paybill_number: profile.paybill_number || '',
          business_name: profile.business_name || '',
          shortcode: profile.shortcode || '',
          environment: profile.environment || env.APP_ENV || 'sandbox',
          account_reference_label: profile.account_reference_label || 'Invoice',
          synced_at: now(),
        },
      });
    }

    // STK initiate — idempotent by (shop_id, idempotency_key)
    if (request.method === 'POST' && path === '/v1/stk/initiate') {
      const auth = requireShop(request);
      if (auth instanceof Response) return auth;
      const body = (await request.json()) as Json;
      if (String(body.shop_id || '') !== auth.shopId) {
        return json({ ok: false, error_code: 'FORBIDDEN', error_message: 'Shop mismatch' }, 403);
      }
      const idem = String(body.idempotency_key || '');
      const amount = Math.round(Number(body.amount || 0));
      const phone = normalizeKePhone(String(body.phone || ''));
      const paymentId = String(body.payment_id || '');
      if (!idem || amount <= 0 || !phone || phone.length < 12 || !paymentId) {
        return json({ ok: false, error_code: 'VALIDATION', error_message: 'Missing/invalid fields' }, 400);
      }

      const existing = await env.DB.prepare(
        'SELECT * FROM payment_intents WHERE shop_id = ? AND idempotency_key = ?',
      )
        .bind(auth.shopId, idem)
        .first();
      if (existing) {
        return json({
          ok: true,
          idempotent: true,
          request_accepted: true,
          status: existing.status,
          provider_checkout_id: existing.id,
          checkout_request_id: existing.checkout_request_id,
          merchant_request_id: existing.merchant_request_id,
        });
      }

      const profile = await getProfile(env, auth.shopId);
      if (!profile || !profile.stk_enabled) {
        return json({
          ok: false,
          error_code: 'STK_NOT_ENABLED',
          error_message: 'STK not enabled for merchant profile',
        }, 400);
      }

      const intentId = `pi_${crypto.randomUUID().replace(/-/g, '')}`;
      let checkoutRequestId = '';
      let merchantRequestId = '';
      let requestAccepted = false;
      let resultDesc = '';

      const shortcode = String(profile.shortcode || env.DARAJA_SHORTCODE || '');
      const till = String(profile.till_number || '');
      const passkey = env.DARAJA_PASSKEY || '';
      const buyGoods = Boolean(till) && !String(profile.paybill_number || '');
      const partyB = buyGoods ? till || shortcode : shortcode;
      const txType = buyGoods ? 'CustomerBuyGoodsOnline' : 'CustomerPayBillOnline';

      if (stkSecretsReady(env, profile as Record<string, unknown>)) {
        const token = await darajaToken(env);
        if (!token) {
          return json({
            ok: false,
            error_code: 'DARAJA_AUTH',
            error_message: 'Could not obtain Daraja access token',
          }, 502);
        }
        const ts = darajaTimestamp();
        const password = lipaPassword(shortcode, passkey, ts);
        const callback = `${publicBase(env, request)}/v1/webhooks/daraja/stk`;
        const stkUrl = `${env.DARAJA_BASE_URL}/mpesa/stkpush/v1/processrequest`;
        const stkBody = {
          BusinessShortCode: shortcode,
          Password: password,
          Timestamp: ts,
          TransactionType: txType,
          Amount: amount,
          PartyA: phone,
          PartyB: partyB,
          PhoneNumber: phone,
          CallBackURL: callback,
          AccountReference: String(body.account_reference || paymentId).slice(0, 12),
          TransactionDesc: String(body.description || 'POS Payment').slice(0, 20),
        };
        const stkRes = await fetch(stkUrl, {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(stkBody),
        });
        const stkJson = (await stkRes.json().catch(() => ({}))) as Json;
        const respCode = String(stkJson.ResponseCode ?? stkJson.responseCode ?? '');
        if (!stkRes.ok || (respCode && respCode !== '0')) {
          return json({
            ok: false,
            error_code: 'STK_REJECTED',
            error_message: String(
              stkJson.errorMessage || stkJson.ResponseDescription || stkJson.CustomerMessage || 'STK rejected',
            ),
            daraja: stkJson,
          }, 502);
        }
        checkoutRequestId = String(stkJson.CheckoutRequestID || '');
        merchantRequestId = String(stkJson.MerchantRequestID || '');
        requestAccepted = true;
        resultDesc = String(stkJson.CustomerMessage || stkJson.ResponseDescription || 'STK accepted');
      } else if (env.ALLOW_MOCK_STK === '1') {
        checkoutRequestId = `ws_checkout_${intentId.slice(-12)}`;
        merchantRequestId = `ws_merchant_${intentId.slice(-12)}`;
        requestAccepted = true;
        resultDesc = 'Mock STK accepted (ALLOW_MOCK_STK=1) — NOT paid';
      } else {
        return json({
          ok: false,
          error_code: 'DARAJA_NOT_CONFIGURED',
          error_message:
            'Daraja secrets/shortcode missing. Set DARAJA_* secrets and merchant shortcode, or ALLOW_MOCK_STK=1 for local mock.',
        }, 503);
      }

      await env.DB.prepare(
        `INSERT INTO payment_intents
         (id, shop_id, device_id, pos_payment_id, amount, phone_masked, account_reference,
          idempotency_key, status, checkout_request_id, merchant_request_id, result_desc, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'awaiting_customer', ?, ?, ?, ?, ?)`,
      )
        .bind(
          intentId,
          auth.shopId,
          auth.deviceId,
          paymentId,
          amount,
          maskPhone(phone),
          String(body.account_reference || '').slice(0, 12),
          idem,
          checkoutRequestId,
          merchantRequestId,
          resultDesc,
          now(),
          now(),
        )
        .run();

      return json({
        ok: true,
        request_accepted: requestAccepted,
        status: 'awaiting_customer',
        provider_checkout_id: intentId,
        checkout_request_id: checkoutRequestId,
        merchant_request_id: merchantRequestId,
        result_desc: resultDesc,
      });
    }

    // STK query — live Daraja query then update D1; never treat accept as paid
    if (request.method === 'POST' && path === '/v1/stk/query') {
      const auth = requireShop(request);
      if (auth instanceof Response) return auth;
      const body = (await request.json()) as Json;
      const paymentId = String(body.payment_id || '');
      const checkoutId = String(body.provider_checkout_id || '');
      let row = null as Record<string, unknown> | null;
      if (checkoutId) {
        row = (await env.DB.prepare('SELECT * FROM payment_intents WHERE id = ? AND shop_id = ?')
          .bind(checkoutId, auth.shopId)
          .first()) as Record<string, unknown> | null;
      }
      if (!row && paymentId) {
        row = (await env.DB.prepare(
          'SELECT * FROM payment_intents WHERE pos_payment_id = ? AND shop_id = ? ORDER BY created_at DESC',
        )
          .bind(paymentId, auth.shopId)
          .first()) as Record<string, unknown> | null;
      }
      if (!row) {
        return json({ ok: false, error_code: 'NOT_FOUND', error_message: 'Intent not found', status: 'unknown' }, 404);
      }

      // Already terminal
      const st = String(row.status || '');
      if (st === 'verified' || st === 'failed' || st === 'cancelled' || st === 'expired') {
        return json({
          ok: true,
          status: st,
          provider_reference: row.provider_reference || '',
          amount_received: row.amount_received || 0,
          result_code: row.result_code || '',
          result_desc: row.result_desc || '',
          checkout_request_id: row.checkout_request_id,
        });
      }

      const checkoutRequestId = String(row.checkout_request_id || body.checkout_request_id || '');
      const profile = await getProfile(env, auth.shopId);
      if (
        checkoutRequestId &&
        !checkoutRequestId.startsWith('ws_checkout_') &&
        profile &&
        stkSecretsReady(env, profile as Record<string, unknown>)
      ) {
        const token = await darajaToken(env);
        if (token) {
          const shortcode = String((profile as Json).shortcode || env.DARAJA_SHORTCODE || '');
          const ts = darajaTimestamp();
          const password = lipaPassword(shortcode, env.DARAJA_PASSKEY || '', ts);
          const qUrl = `${env.DARAJA_BASE_URL}/mpesa/stkpushquery/v1/query`;
          const qRes = await fetch(qUrl, {
            method: 'POST',
            headers: {
              Authorization: `Bearer ${token}`,
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              BusinessShortCode: shortcode,
              Password: password,
              Timestamp: ts,
              CheckoutRequestID: checkoutRequestId,
            }),
          });
          const qJson = (await qRes.json().catch(() => ({}))) as Json;
          // ResultCode "0" = success paid; "1032" cancelled; "4999" still processing etc.
          const resultCode = String(qJson.ResultCode ?? qJson.resultCode ?? '');
          const resultDesc = String(qJson.ResultDesc ?? qJson.resultDesc ?? '');
          if (resultCode === '0') {
            // Receipt may be in CallbackMetadata-like fields or ResultDesc only on query
            const providerReference = String(
              qJson.MpesaReceiptNumber || qJson.mpesa_receipt || row.provider_reference || '',
            );
            const amountReceived = Number(qJson.Amount || row.amount || 0);
            await env.DB.prepare(
              `UPDATE payment_intents SET status = 'verified', provider_reference = ?,
               amount_received = ?, result_code = ?, result_desc = ?, updated_at = ?
               WHERE id = ?`,
            )
              .bind(
                providerReference || null,
                amountReceived,
                resultCode,
                resultDesc,
                now(),
                row.id,
              )
              .run();
            row = {
              ...row,
              status: 'verified',
              provider_reference: providerReference,
              amount_received: amountReceived,
              result_code: resultCode,
              result_desc: resultDesc,
            };
          } else if (resultCode && resultCode !== '4999' && resultCode !== '1037') {
            // Definitive failure / cancel (not "still processing")
            const failed = ['1032', '1', '1001', '1019', '1025', '1037'].includes(resultCode)
              ? resultCode === '1032'
                ? 'cancelled'
                : 'failed'
              : st;
            if (failed !== st && (failed === 'failed' || failed === 'cancelled')) {
              await env.DB.prepare(
                `UPDATE payment_intents SET status = ?, result_code = ?, result_desc = ?, updated_at = ?
                 WHERE id = ?`,
              )
                .bind(failed, resultCode, resultDesc, now(), row.id)
                .run();
              row = { ...row, status: failed, result_code: resultCode, result_desc: resultDesc };
            } else {
              // Keep awaiting; attach last desc
              await env.DB.prepare(
                `UPDATE payment_intents SET result_code = ?, result_desc = ?, updated_at = ? WHERE id = ?`,
              )
                .bind(resultCode, resultDesc, now(), row.id)
                .run();
            }
          }
        }
      }

      return json({
        ok: true,
        status: row.status,
        provider_reference: row.provider_reference || '',
        amount_received: row.amount_received || 0,
        result_code: row.result_code || '',
        result_desc: row.result_desc || '',
        checkout_request_id: row.checkout_request_id,
      });
    }

    // Daraja STK callback
    if (request.method === 'POST' && path === '/v1/webhooks/daraja/stk') {
      const body = (await request.json()) as Json;
      const callback = (body.Body as Json)?.stkCallback as Json | undefined;
      if (!callback) return json({ ResultCode: 0, ResultDesc: 'Accepted' });
      const checkoutRequestId = String(callback.CheckoutRequestID || '');
      const resultCode = String(callback.ResultCode ?? '');
      const resultDesc = String(callback.ResultDesc || '');
      let providerReference = '';
      let amountReceived = 0;
      const meta = callback.CallbackMetadata as { Item?: Array<{ Name: string; Value: unknown }> } | undefined;
      for (const item of meta?.Item || []) {
        if (item.Name === 'MpesaReceiptNumber') providerReference = String(item.Value || '');
        if (item.Name === 'Amount') amountReceived = Number(item.Value || 0);
      }
      const status = resultCode === '0' ? 'verified' : resultCode === '1032' ? 'cancelled' : 'failed';
      await env.DB.prepare(
        `UPDATE payment_intents SET status = ?, provider_reference = ?, amount_received = ?,
         result_code = ?, result_desc = ?, updated_at = ?
         WHERE checkout_request_id = ?`,
      )
        .bind(status, providerReference || null, amountReceived, resultCode, resultDesc, now(), checkoutRequestId)
        .run();
      return json({ ResultCode: 0, ResultDesc: 'Accepted' });
    }

    // C2B validation (RegisterURL ValidationURL)
    if (request.method === 'POST' && path === '/v1/webhooks/daraja/c2b/validation') {
      return json({ ResultCode: 0, ResultDesc: 'Accepted' });
    }

    // C2B confirmation webhook
    if (
      request.method === 'POST' &&
      (path === '/v1/webhooks/daraja/c2b' || path === '/v1/webhooks/daraja/c2b/confirmation')
    ) {
      const body = (await request.json()) as Json;
      const shortcode = String(body.BusinessShortCode || body.ShortCode || body.TillNumber || '');
      let shopId = String(body.shop_id || '');
      if (!shopId && shortcode) {
        const profile = await findShopByShortcode(env, shortcode);
        shopId = profile ? String(profile.shop_id) : '';
      }
      const ref = String(body.TransID || body.provider_reference || '').toUpperCase();
      const amount = Number(body.TransAmount || body.amount || 0);
      if (!shopId || !ref) {
        return json({
          ResultCode: 0,
          ResultDesc: 'Accepted',
          ok: false,
          error_code: 'UNMAPPED_SHOP',
          error_message: 'Could not map BusinessShortCode to shop_id',
        });
      }
      const id = `in_${shopId}_${ref}`;
      try {
        await env.DB.prepare(
          `INSERT INTO incoming_payments
           (id, shop_id, provider_reference, amount, phone_masked, till_number, paybill_number,
            bill_ref, trans_time, status, raw_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'unmatched', ?, ?)`,
        )
          .bind(
            id,
            shopId,
            ref,
            amount,
            maskPhone(String(body.MSISDN || '')),
            String(body.till_number || body.TillNumber || ''),
            String(body.paybill_number || body.BusinessShortCode || ''),
            String(body.BillRefNumber || ''),
            String(body.TransTime || ''),
            JSON.stringify(body),
            now(),
          )
          .run();
      } catch {
        // UNIQUE (shop_id, provider_reference) — idempotent
      }
      return json({ ResultCode: 0, ResultDesc: 'Accepted' });
    }

    // Incoming list for POS matching
    if (request.method === 'GET' && path.match(/^\/v1\/shops\/[^/]+\/incoming$/)) {
      const shopId = path.split('/')[3];
      const auth = requireShop(request);
      if (auth instanceof Response) return auth;
      if (auth.shopId !== shopId) {
        return json({ ok: false, error_code: 'FORBIDDEN', error_message: 'Shop mismatch' }, 403);
      }
      const unmatched = url.searchParams.get('unmatched') !== '0';
      const since = Number(url.searchParams.get('since') || 0);
      const sql = unmatched
        ? `SELECT * FROM incoming_payments WHERE shop_id = ? AND status = 'unmatched' AND created_at >= ? ORDER BY created_at DESC LIMIT 200`
        : `SELECT * FROM incoming_payments WHERE shop_id = ? AND created_at >= ? ORDER BY created_at DESC LIMIT 200`;
      const { results } = await env.DB.prepare(sql).bind(shopId, since).all();
      return json({ ok: true, items: results || [] });
    }

    // Manual reference attestation
    if (request.method === 'POST' && path === '/v1/manual/register') {
      const auth = requireShop(request);
      if (auth instanceof Response) return auth;
      const body = (await request.json()) as Json;
      const ref = String(body.provider_reference || '').toUpperCase();
      if (ref.length < 6) {
        return json({ ok: false, error_code: 'VALIDATION', error_message: 'Reference too short' }, 400);
      }
      await env.DB.prepare(
        `INSERT INTO audit_events (shop_id, event_type, detail, created_at) VALUES (?, 'manual_ref', ?, ?)`,
      )
        .bind(auth.shopId, `${body.payment_id}:${ref}`, now())
        .run();
      return json({
        ok: true,
        status: 'manual_pending',
        provider_reference: ref,
        amount_received: Number(body.amount || 0),
        result_desc: 'Manual reference attested — POS must confirm',
      });
    }

    // Admin: upsert portable merchant profile (no secrets in body)
    if (request.method === 'POST' && path === '/v1/admin/merchant-profiles') {
      const denied = requireAdmin(request, env);
      if (denied) return denied;
      const body = (await request.json()) as Json;
      const shopId = String(body.shop_id || '');
      if (!shopId) return json({ ok: false, error_code: 'VALIDATION', error_message: 'shop_id required' }, 400);
      const id = String(body.id || `mp_${shopId}`);
      await env.DB.prepare(
        `INSERT INTO merchant_profiles
         (id, shop_id, business_name, shortcode, till_number, paybill_number, stk_enabled, c2b_enabled,
          environment, account_reference_label, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(shop_id) DO UPDATE SET
           business_name=excluded.business_name,
           shortcode=excluded.shortcode,
           till_number=excluded.till_number,
           paybill_number=excluded.paybill_number,
           stk_enabled=excluded.stk_enabled,
           c2b_enabled=excluded.c2b_enabled,
           environment=excluded.environment,
           account_reference_label=excluded.account_reference_label,
           updated_at=excluded.updated_at`,
      )
        .bind(
          id,
          shopId,
          String(body.business_name || ''),
          String(body.shortcode || ''),
          String(body.till_number || ''),
          String(body.paybill_number || ''),
          body.stk_enabled ? 1 : 0,
          body.c2b_enabled ? 1 : 0,
          String(body.environment || env.APP_ENV || 'sandbox'),
          String(body.account_reference_label || 'Invoice'),
          now(),
          now(),
        )
        .run();
      return json({ ok: true, profile_id: id });
    }

    return json({ ok: false, error_code: 'NOT_FOUND', error_message: 'Not found' }, 404);
  },
};
