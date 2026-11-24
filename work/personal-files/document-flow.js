const PAGE_GAP = 16;
const MARGIN = 12;

export function pageFlow(sizes, viewportWidth, viewportHeight, zoom) {
  const available = Math.max(100, viewportWidth - 30);
  const pageWidth = available * zoom;
  let top = MARGIN;
  const pages = sizes.map(([w, h]) => {
    const height = pageWidth * h / Math.max(1, w);
    const page = { top, width: pageWidth, height };
    top += height + PAGE_GAP;
    return page;
  });
  return { pages, pageWidth, viewportHeight, viewportWidth,
    maxX: pages.length ? Math.max(0, pageWidth + 2*MARGIN - viewportWidth) : 0,
    maxY: Math.max(0, top - PAGE_GAP + MARGIN - viewportHeight) };
}

export function pageAt(flow, y) {
  let lo = 0, hi = flow.pages.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    const page = flow.pages[mid];
    if (y > page.top + page.height) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

export function visiblePages(flow, startY, padding = 120) {
  if (!flow.pages.length) return [];
  const start = pageAt(flow, Math.max(0, startY-padding));
  const end = pageAt(flow, startY + flow.viewportHeight + padding);
  return Array.from({length:end-start+1}, (_, i) => start+i);
}

export function restorePosition(flow, index, fraction, viewportOffset = 0) {
  const page = flow.pages[Math.min(index, flow.pages.length-1)];
  return page ? Math.max(0, Math.min(flow.maxY, page.top + page.height*fraction - viewportOffset)) : 0;
}

export function dropSide(point, bounds) {
  if (!point || point.x < bounds.left || point.x > bounds.right || point.y < bounds.top || point.y > bounds.bottom) return null;
  return point.x < (bounds.left+bounds.right)/2 ? 'left' : 'right';
}
