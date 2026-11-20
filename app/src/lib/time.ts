const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

/** "Hace 5 h", "Ayer"… para la lista de recientes. Fechas viejas, con día y mes. */
export function whenOpened(iso: string, now: Date = new Date()): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const ago = now.getTime() - t;
  if (ago < MIN) return "Recién";
  if (ago < HOUR) return `Hace ${Math.floor(ago / MIN)} min`;
  if (ago < DAY) return `Hace ${Math.floor(ago / HOUR)} h`;
  if (ago < 2 * DAY) return "Ayer";
  if (ago < 7 * DAY) return `Hace ${Math.floor(ago / DAY)} días`;
  return new Date(t).toLocaleDateString("es-AR", { day: "numeric", month: "short", year: "numeric" });
}
