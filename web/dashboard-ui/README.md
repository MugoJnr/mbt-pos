# MBT POS Dashboard

Full frontend prototype for MBT POS (dark + gold theme, responsive desktop & mobile).

## Stack
- React 19 + TanStack Start v1 (Vite 7)
- Tailwind CSS v4 (`src/styles.css`)
- shadcn-style UI primitives (`src/components/ui-kit.tsx`)
- Lucide icons, Manrope font

## Structure
```
src/
  assets/            # logo/icon asset JSONs (CDN-hosted)
  components/
    app-shell.tsx    # Responsive sidebar + topbar + footer
    theme.tsx        # Dark/light theme provider
    ui-kit.tsx       # Card, Button, KpiCard, Table, Badge
  lib/
    mock-data.ts     # All mock data (sales, inventory, debt, etc.)
    utils.ts
  routes/            # File-based routes (11 screens)
    index.tsx        # Dashboard
    pos.tsx
    inventory.tsx
    debt.tsx
    reports.tsx
    notes.tsx
    users.tsx
    settings.tsx
    security.tsx
    license.tsx
    diagnostics.tsx
  styles.css         # Theme tokens (dark + light)
public/
  robots.txt
```

## Responsive
- Desktop (>=1024px): full sidebar visible
- Mobile / tablet: hamburger button opens drawer sidebar
- Topbar collapses secondary controls at sm/md breakpoints
- Grids in dashboard/POS collapse to single column below sm

## Run
```bash
bun install
bun run dev
```

## Integrate into existing app
1. Copy `src/components`, `src/lib`, `src/routes`, `src/assets`, `src/styles.css`.
2. Ensure `@tanstack/react-router`, `@tanstack/react-start`, `lucide-react`, `tailwindcss@^4` are installed.
3. Wrap root in `<ThemeProvider>` (see `src/routes/__root.tsx`).
4. Replace `src/lib/mock-data.ts` with your live data source (Cloud/API).
