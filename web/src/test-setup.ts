// Test-environment shim only: jsdom has no ResizeObserver, which OpenLayers needs to track its target size.
// Browsers provide it; nothing in the app depends on this file.
class ResizeObserverShim {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver ??= ResizeObserverShim as unknown as typeof ResizeObserver;
