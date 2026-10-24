import { ImagePlus } from "lucide-react";
import { useState } from "react";

const SIZES = { sm: "h-10 w-10", md: "h-16 w-16", lg: "h-24 w-24" };

export function productPhotoSrc(path?: string | null): string {
  const name = String(path || "").split(/[/\\]/).pop() || "";
  if (!name || name.includes("..")) return "";
  const base = name.split("?")[0];
  return base ? `/product-images/${base}` : "";
}

export function ProductPhoto({
  src,
  preview,
  size = "md",
  onFile,
  onRemove,
  disabled,
  busy,
}: {
  src?: string | null;
  preview?: string;
  size?: keyof typeof SIZES;
  onFile?: (file: File) => void;
  onRemove?: () => void;
  disabled?: boolean;
  busy?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const photo = failed ? "" : (preview || productPhotoSrc(src));
  const label = photo ? "Change photograph" : "Add photograph";
  const tile = (
    <span
      className={`${SIZES[size]} relative grid shrink-0 place-items-center overflow-hidden rounded-xl border border-gold/50 bg-gold/10 text-gold transition hover:border-gold focus-within:ring-2 focus-within:ring-gold/70 ${disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer"}`}
    >
      {photo ? (
        <img
          src={photo}
          alt=""
          className="h-full w-full object-cover"
          onError={() => setFailed(true)}
        />
      ) : (
        <ImagePlus className="h-5 w-5" aria-hidden="true" />
      )}
      {busy ? <span className="absolute inset-0 grid place-items-center bg-black/50 text-[10px] font-semibold text-white">Saving…</span> : null}
      {onFile ? (
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp,image/heic"
          className="absolute inset-0 cursor-pointer opacity-0 disabled:cursor-not-allowed"
          aria-label={label}
          title={failed ? "Photograph could not be loaded. Choose another." : label}
          disabled={disabled || busy}
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) onFile(file);
          }}
        />
      ) : (
        <span className="sr-only">{failed ? "Photograph could not be loaded" : photo ? "Product photograph" : "No photograph"}</span>
      )}
    </span>
  );
  return (
    <span className="inline-flex items-center gap-3">
      {tile}
      {onRemove && photo ? (
        <button type="button" className="text-xs font-semibold text-text2 underline" onClick={onRemove} disabled={disabled || busy}>
          Remove photograph
        </button>
      ) : null}
    </span>
  );
}
