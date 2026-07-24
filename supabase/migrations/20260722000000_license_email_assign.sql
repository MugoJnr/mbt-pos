-- Link activation keys to customer email (+ optional reserved device).
-- Safe to re-run (IF NOT EXISTS).

ALTER TABLE public.licenses
  ADD COLUMN IF NOT EXISTS assigned_email text,
  ADD COLUMN IF NOT EXISTS assigned_user_id uuid,
  ADD COLUMN IF NOT EXISTS reserved_device_id text,
  ADD COLUMN IF NOT EXISTS claim_status text NOT NULL DEFAULT 'unassigned',
  ADD COLUMN IF NOT EXISTS claimed_at timestamptz,
  ADD COLUMN IF NOT EXISTS assigned_at timestamptz;

COMMENT ON COLUMN public.licenses.assigned_email IS
  'Customer email this key is reserved for. Sign-in with this email can auto-claim.';
COMMENT ON COLUMN public.licenses.reserved_device_id IS
  'Optional hardware device_id; when set only this device may activate the key.';
COMMENT ON COLUMN public.licenses.claim_status IS
  'unassigned | reserved | claimed';

CREATE INDEX IF NOT EXISTS licenses_assigned_email_idx
  ON public.licenses (lower(assigned_email))
  WHERE assigned_email IS NOT NULL AND assigned_email <> '';

CREATE INDEX IF NOT EXISTS licenses_claim_status_idx
  ON public.licenses (claim_status)
  WHERE claim_status IS NOT NULL;
