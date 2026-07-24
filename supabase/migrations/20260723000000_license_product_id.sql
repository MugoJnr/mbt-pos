-- Multi-product licenses: MBT POS, Pulse, and future apps.
-- Safe to re-run (IF NOT EXISTS).

ALTER TABLE public.licenses
  ADD COLUMN IF NOT EXISTS product_id text NOT NULL DEFAULT 'mbt-pos';

COMMENT ON COLUMN public.licenses.product_id IS
  'Portal product id this seat belongs to (mbt-pos, pulse, exam-hub, …).';

-- Existing rows were POS-only before multi-product licensing.
UPDATE public.licenses
SET product_id = 'mbt-pos'
WHERE product_id IS NULL OR product_id = '';

CREATE INDEX IF NOT EXISTS licenses_product_id_idx
  ON public.licenses (product_id);

CREATE INDEX IF NOT EXISTS licenses_email_product_idx
  ON public.licenses (lower(assigned_email), product_id)
  WHERE assigned_email IS NOT NULL AND assigned_email <> '';
