import { createFileRoute, redirect } from "@tanstack/react-router";

/** Deep-link alias — bookmarks historically used /licenses (plural). */
export const Route = createFileRoute("/_app/licenses")({
  beforeLoad: () => {
    throw redirect({ to: "/license" });
  },
  head: () => ({ meta: [{ title: "Licenses | MugoByte" }] }),
});
