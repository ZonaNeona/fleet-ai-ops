export function appRoute() {
  if (new URLSearchParams(location.search).get("web") === "1") return "product";
  if (
    /^#tg(?:\/|$)/.test(location.hash) ||
    new URLSearchParams(location.search).has("tg") ||
    /tgWebApp/.test(location.hash + location.search)
  )
    return "tg";
  return location.hash.startsWith("#under") ? "under" : "product";
}
export function deepRoute(start?: string) {
  if (!start) return "";
  const m = start.match(/^(booking|fine|ticket)_([a-f0-9]{32})$/);
  return m
    ? ({
        booking: "rentals/",
        fine: "driver/fines/",
        ticket: "driver/tickets/",
      }[m[1]] || "") + m[2]
    : "";
}
