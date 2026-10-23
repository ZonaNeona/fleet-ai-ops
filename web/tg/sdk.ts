export type ActionButton = {
  text: string;
  disabled?: boolean;
  busy?: boolean;
} | null;
type NativeApp = {
  initData: string;
  initDataUnsafe?: { start_param?: string };
  colorScheme?: string;
  themeParams?: Record<string, string>;
  viewportStableHeight?: number;
  safeAreaInset?: { top: number; bottom: number };
  contentSafeAreaInset?: { top: number; bottom: number };
  MainButton?: {
    setText(t: string): void;
    show(): void;
    hide(): void;
    enable(): void;
    disable(): void;
    showProgress(): void;
    hideProgress(): void;
    onClick(f: () => void): void;
    offClick(f: () => void): void;
  };
  BackButton?: {
    show(): void;
    hide(): void;
    onClick(f: () => void): void;
    offClick(f: () => void): void;
  };
  HapticFeedback?: {
    impactOccurred(t: string): void;
    notificationOccurred(t: string): void;
  };
  LocationManager?: {
    init(cb: () => void): void;
    getLocation(
      cb: (v: { latitude: number; longitude: number } | null) => void,
    ): void;
  };
  ready(): void;
  expand(): void;
  close(): void;
  showConfirm?(text: string, callback: (confirmed: boolean) => void): void;
  openTelegramLink?(u: string): void;
  onEvent?(event: string, handler: () => void): void;
  offEvent?(event: string, handler: () => void): void;
  isVersionAtLeast?(v: string): boolean;
};
export const nativeApp = (): NativeApp | undefined =>
  (window as any).Telegram?.WebApp;
export const embedded = () =>
  window.parent !== window &&
  new URLSearchParams(location.search).has("emulator");
export function host(type: string, value?: unknown) {
  if (embedded())
    window.parent.postMessage(
      { channel: "fleet-miniapp-v1", type, value },
      location.origin,
    );
}
export function setupSdk() {
  const tg = nativeApp();
  let browserTheme: string | undefined;
  const apply = () => {
    const r = document.documentElement;
    r.dataset.tgTheme = browserTheme || tg?.colorScheme || "light";
    const p = tg?.themeParams || {};
    for (const [k, v] of Object.entries(p))
      if (/^#[0-9a-f]{6}$/i.test(v))
        r.style.setProperty("--tg-" + k.replaceAll("_", "-"), v);
    r.style.setProperty(
      "--tg-safe-top",
      (tg?.safeAreaInset?.top || 0) +
        (tg?.contentSafeAreaInset?.top || 0) +
        "px",
    );
    r.style.setProperty(
      "--tg-safe-bottom",
      (tg?.safeAreaInset?.bottom || 0) +
        (tg?.contentSafeAreaInset?.bottom || 0) +
        "px",
    );
    if (tg?.viewportStableHeight)
      r.style.setProperty("--tg-height", tg.viewportStableHeight + "px");
  };
  tg?.ready();
  tg?.expand();
  apply();
  [
    "themeChanged",
    "viewportChanged",
    "safeAreaChanged",
    "contentSafeAreaChanged",
  ].forEach((e) => tg?.onEvent?.(e, apply));
  const receive = (event: MessageEvent) => {
    if (
      embedded() &&
      event.origin === location.origin &&
      event.source === window.parent &&
      event.data?.channel === "fleet-miniapp-v1" &&
      event.data.type === "theme" &&
      ["light", "dark"].includes(event.data.value)
    ) {
      browserTheme = event.data.value;
      apply();
    }
  };
  window.addEventListener("message", receive);
  host("ready");
  return () => {
    window.removeEventListener("message", receive);
    [
      "themeChanged",
      "viewportChanged",
      "safeAreaChanged",
      "contentSafeAreaChanged",
    ].forEach((e) => tg?.offEvent?.(e, apply));
  };
}
/** Native confirmation when supported; the browser renders its own accessible confirmation. */
export function confirmAction(
  text: string,
  confirmed: () => void,
  browserFallback: () => void,
) {
  const tg = nativeApp();
  if (tg?.initData && tg.showConfirm && tg.isVersionAtLeast?.("6.2"))
    tg.showConfirm(text, (ok) => {
      if (ok) confirmed();
    });
  else browserFallback();
}
export function setMainButton(button: ActionButton, action: () => void) {
  const b = nativeApp()?.MainButton;
  if (button && b) {
    b.setText(button.text);
    b.show();
    button.disabled || button.busy ? b.disable() : b.enable();
    button.busy ? b.showProgress() : b.hideProgress();
    b.onClick(action);
  } else b?.hide();
  host("main-button", button);
  const receive = (e: MessageEvent) => {
    if (
      e.origin === location.origin &&
      e.source === window.parent &&
      e.data?.channel === "fleet-miniapp-v1" &&
      e.data.type === "main-click" &&
      button &&
      !button.disabled &&
      !button.busy
    )
      action();
  };
  window.addEventListener("message", receive);
  return () => {
    b?.offClick(action);
    b?.hide();
    window.removeEventListener("message", receive);
    host("main-button", null);
  };
}
export function setBackButton(enabled: boolean, back: () => void) {
  const b = nativeApp()?.BackButton;
  if (enabled) {
    b?.show();
    b?.onClick(back);
  } else b?.hide();
  host("back-button", enabled);
  const receive = (e: MessageEvent) => {
    if (
      e.origin === location.origin &&
      e.source === window.parent &&
      e.data?.channel === "fleet-miniapp-v1" &&
      e.data.type === "back-click"
    )
      back();
  };
  window.addEventListener("message", receive);
  return () => {
    b?.offClick(back);
    b?.hide();
    window.removeEventListener("message", receive);
  };
}
export function haptic(ok = false) {
  const tg = nativeApp();
  if (!tg?.isVersionAtLeast?.("6.1")) return;
  if (ok) tg.HapticFeedback?.notificationOccurred("success");
  else tg.HapticFeedback?.impactOccurred("light");
}
export async function getLocation(): Promise<string> {
  const tg = nativeApp();
  if (tg?.LocationManager && tg.isVersionAtLeast?.("8.0"))
    return new Promise((resolve, reject) => {
      tg.LocationManager!.init(() =>
        tg.LocationManager!.getLocation((v) =>
          v
            ? resolve(`${v.latitude.toFixed(6)}, ${v.longitude.toFixed(6)}`)
            : reject(
                new Error("Местоположение не получено. Укажите адрес вручную."),
              ),
        ),
      );
    });
  return new Promise((resolve, reject) =>
    navigator.geolocation
      ? navigator.geolocation.getCurrentPosition(
          (p) =>
            resolve(
              `${p.coords.latitude.toFixed(6)}, ${p.coords.longitude.toFixed(6)}`,
            ),
          () =>
            reject(
              new Error(
                "Укажите адрес вручную — доступ к местоположению не получен.",
              ),
            ),
          { timeout: 10000 },
        )
      : reject(new Error("Укажите адрес вручную.")),
  );
}
