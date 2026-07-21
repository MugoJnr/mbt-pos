export function renderErrorPage(): string {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Something went wrong | MugoByte</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="theme-color" content="#1a1f3a" />
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <style>
      body { font: 15px/1.5 Manrope, system-ui, -apple-system, sans-serif; background: #0b1220; color: #e2e8f0; display: grid; place-items: center; min-height: 100vh; margin: 0; padding: 1.5rem; }
      .card { max-width: 28rem; width: 100%; text-align: center; padding: 2rem; border: 1px solid #1f2937; border-radius: 12px; background: #111827; }
      .brand { font-weight: 700; letter-spacing: 0.04em; margin-bottom: 1rem; color: #93c5fd; }
      h1 { font-size: 1.25rem; margin: 0 0 0.5rem; color: #f8fafc; }
      p { color: #94a3b8; margin: 0 0 1.5rem; }
      .actions { display: flex; gap: 0.5rem; justify-content: center; flex-wrap: wrap; }
      a, button { padding: 0.5rem 1rem; border-radius: 0.5rem; font: inherit; cursor: pointer; text-decoration: none; border: 1px solid transparent; }
      .primary { background: #3b82f6; color: #fff; }
      .secondary { background: transparent; color: #e2e8f0; border-color: #334155; }
      .foot { margin-top: 1.25rem; font-size: 12px; color: #64748b; }
    </style>
  </head>
  <body>
    <div class="card">
      <div class="brand">MugoByte Technologies</div>
      <h1>This page didn't load</h1>
      <p>Something went wrong on our end. You can try refreshing or return to MugoByte Workspace.</p>
      <div class="actions">
        <button class="primary" onclick="location.reload()">Try again</button>
        <a class="secondary" href="/dashboard">Workspace home</a>
      </div>
      <div class="foot">portal.mugobyte.com</div>
    </div>
  </body>
</html>`;
}
