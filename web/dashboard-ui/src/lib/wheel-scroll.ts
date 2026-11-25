/** Page scroll distance for a mouse-wheel notch. Touchpad movement is not scaled. */

export const SCROLL_INTERVAL_DEFAULT = 3;
const LINE_PX = 48;

export function scrollInterval(raw: unknown): number {
  const number = Number(raw);
  if (!Number.isFinite(number) || number < 1 || number > 10 || Math.round(number) !== number) {
    return SCROLL_INTERVAL_DEFAULT;
  }
  return number;
}

export function wheelScrollPixels(
  event: { deltaX: number; deltaY: number; deltaMode: number },
  interval: number,
): { x: number; y: number } | null {
  const gap = scrollInterval(interval);
  const horizontal = Math.abs(event.deltaX) > Math.abs(event.deltaY);
  const primary = horizontal ? event.deltaX : event.deltaY;
  if (!primary) return null;
  const mouseNotch = event.deltaMode === 1 || Math.abs(primary) >= 40;
  if (!mouseNotch) return null;
  const notches = event.deltaMode === 1 ? primary : Math.sign(primary);
  const distance = notches * gap * LINE_PX;
  return horizontal ? { x: distance, y: 0 } : { x: 0, y: distance };
}

function scrollHost(start: EventTarget | null): Element | null {
  let node = start instanceof Element ? start : null;
  while (node && node !== document.body) {
    const style = window.getComputedStyle(node);
    const overflow = `${style.overflow} ${style.overflowY} ${style.overflowX}`;
    if (/(auto|scroll)/.test(overflow) && node.scrollHeight + node.scrollWidth > node.clientHeight + node.clientWidth + 2) {
      return node;
    }
    node = node.parentElement;
  }
  return document.scrollingElement;
}

export function installWheelScroll(interval: number): () => void {
  const onWheel = (event: WheelEvent) => {
    const target = event.target;
    if (
      target instanceof HTMLInputElement
      || target instanceof HTMLTextAreaElement
      || target instanceof HTMLSelectElement
    ) return;
    if (event.ctrlKey || event.defaultPrevented) return;
    const move = wheelScrollPixels(event, interval);
    if (!move) return;
    const host = scrollHost(event.target);
    if (!host) return;
    event.preventDefault();
    host.scrollBy({ left: move.x, top: move.y, behavior: "auto" });
  };
  window.addEventListener("wheel", onWheel, { capture: true, passive: false });
  return () => window.removeEventListener("wheel", onWheel, { capture: true });
}
