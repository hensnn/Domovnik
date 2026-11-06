import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import OfflineBanner from "../../components/OfflineBanner";
import { setCurrentLocation, useCurrentLocation } from "../../lib/currentLocation";
import PrintLabelsDialog from "./PrintLabelsDialog";

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("PrintLabelsDialog", () => {
  it("sestaví odkaz na PDF a respektuje počáteční buňku", () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("[]", { status: 200 }));
    wrap(<PrintLabelsDialog open onClose={() => {}} kind="item" ids={["a", "b"]} />);
    const link = screen.getByRole("link", { name: /Otevřít PDF/ });
    const url = new URL(link.getAttribute("href")!, "http://x");
    expect(url.searchParams.get("kind")).toBe("item");
    expect(url.searchParams.get("ids")).toBe("a,b");
    expect(url.searchParams.get("start")).toBe("0");
    expect(screen.getByText(/Štítků: 2, stran A4: 1/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Buňka 5" }));
    const url2 = new URL(
      screen.getByRole("link", { name: /Otevřít PDF/ }).getAttribute("href")!,
      "http://x",
    );
    expect(url2.searchParams.get("start")).toBe("4");
  });

  it("nic nevykreslí, když je zavřený", () => {
    wrap(<PrintLabelsDialog open={false} onClose={() => {}} kind="item" ids={["a"]} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("useCurrentLocation", () => {
  it("drží hodnotu v localStorage a upozorní odběratele", () => {
    const { result } = renderHook(() => useCurrentLocation());
    expect(result.current[0]).toBeNull();
    act(() => setCurrentLocation("loc-1"));
    expect(result.current[0]).toBe("loc-1");
    expect(localStorage.getItem("domovnik.currentLocation")).toBe("loc-1");
    act(() => result.current[1](null));
    expect(result.current[0]).toBeNull();
  });
});

describe("OfflineBanner", () => {
  it("zobrazí se jen offline", () => {
    const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
    const { container } = render(<OfflineBanner />);
    expect(container).toBeEmptyDOMElement();
    online.mockReturnValue(false);
    act(() => {
      window.dispatchEvent(new Event("offline"));
    });
    expect(screen.getByRole("status")).toHaveTextContent("Jsi offline");
  });
});
