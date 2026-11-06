import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { FileLink } from "../../api/types";
import { mockFetch, problem, renderWithProviders } from "../../test/utils";
import FileGallery from "./FileGallery";

afterEach(() => vi.restoreAllMocks());

const link = (
  id: string,
  over: Partial<FileLink> = {},
  kind: "photo" | "document" = "photo",
): FileLink => ({
  id,
  item_id: "item1",
  location_id: null,
  role: kind === "photo" ? "gallery" : "manual",
  is_primary: false,
  sort_order: 0,
  caption: null,
  created_at: "2026-01-01T00:00:00Z",
  file: {
    id: `f-${id}`,
    kind,
    mime: kind === "photo" ? "image/webp" : "application/pdf",
    size_bytes: 2048,
    width: 100,
    height: 100,
    original_name: `${id}.${kind === "photo" ? "jpg" : "pdf"}`,
    caption: null,
    taken_at: null,
    blurhash: null,
    thumbs_ready: true,
    created_at: "2026-01-01T00:00:00Z",
    url: `/api/v1/files/f-${id}`,
    thumb_256_url: null,
    thumb_1024_url: null,
  },
  ...over,
});

const links = [
  link("p1", { is_primary: true, role: "primary" }),
  link("p2"),
  link("d1", {}, "document"),
];

describe("FileGallery", () => {
  it("ukáže fotky s náhledem 256 px, primární hvězdu a dokumenty jako přílohy s rolí", async () => {
    mockFetch([[/^GET \/items\/item1\/files$/, () => links]]);
    const { container } = renderWithProviders(
      <FileGallery kind="item" id="item1" canWrite={false} />,
    );
    expect(await screen.findByRole("button", { name: "Otevřít fotku p1.jpg" })).toBeInTheDocument();
    const imgs = Array.from(container.querySelectorAll("img"));
    expect(imgs.map((i) => i.getAttribute("src"))).toContain("/api/v1/files/f-p1/thumb?size=256");
    expect(imgs.every((i) => i.getAttribute("loading") === "lazy")).toBe(true);
    expect(screen.getByLabelText("Hlavní fotka")).toBeInTheDocument();
    expect(screen.getByText("d1.pdf")).toBeInTheDocument();
    expect(screen.getByText("Návod")).toBeInTheDocument(); // role dokumentu (jen pro čtení)
    expect(screen.queryByRole("button", { name: "Vyfotit" })).not.toBeInTheDocument();
  });

  it("lightbox otevře 1024px náhled, umí nastavit primární fotku a uložit popisek", async () => {
    const { calls } = mockFetch([
      [/^GET \/items\/item1\/files$/, () => links],
      [/^PATCH \/file-links\/p2$/, () => links[1]],
    ]);
    renderWithProviders(<FileGallery kind="item" id="item1" canWrite />);
    fireEvent.click(await screen.findByRole("button", { name: "Otevřít fotku p2.jpg" }));
    const dialog = await screen.findByRole("dialog", { name: "Prohlížeč fotek" });
    expect(dialog.querySelector("img")).toHaveAttribute(
      "src",
      "/api/v1/files/f-p2/thumb?size=1024",
    );

    fireEvent.click(within(dialog).getByRole("button", { name: "Nastavit jako hlavní" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(calls.find((c) => c.method === "PATCH")!.body).toEqual({ is_primary: true });

    fireEvent.change(within(dialog).getByLabelText("Popisek"), {
      target: { value: "Zadní strana" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Uložit" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(2));
    expect(calls.filter((c) => c.method === "PATCH")[1].body).toEqual({ caption: "Zadní strana" });

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Prohlížeč fotek" })).not.toBeInTheDocument(),
    );
  });

  it("odebrání fotky se nejdřív potvrdí a pak zavolá DELETE na vazbu", async () => {
    const { calls } = mockFetch([
      [/^GET \/items\/item1\/files$/, () => links],
      [/^DELETE \/file-links\/p1$/, () => new Response(null, { status: 204 })],
    ]);
    renderWithProviders(<FileGallery kind="item" id="item1" canWrite />);
    fireEvent.click(await screen.findByRole("button", { name: "Otevřít fotku p1.jpg" }));
    const dialog = await screen.findByRole("dialog", { name: "Prohlížeč fotek" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Odebrat" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    const confirm = await screen.findByRole("dialog", { name: "Odebrat soubor" });
    fireEvent.click(within(confirm).getByRole("button", { name: "Odebrat" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });

  it("nahrání pošle multipart bez ručního Content-Type, s item_id a rolí dokumentu", async () => {
    const { calls } = mockFetch([
      [/^GET \/items\/item1\/files$/, () => []],
      [/^POST \/files$/, () => ({ file: links[0].file, link: links[0], duplicate: false })],
    ]);
    renderWithProviders(<FileGallery kind="item" id="item1" canWrite />);
    const input = await screen.findByTestId("file-input");
    const pdf = new File(["%PDF-1.4"], "navod.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [pdf] } });
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toBeInstanceOf(FormData);
    const form = post.body as FormData;
    expect(form.get("item_id")).toBe("item1");
    expect(form.get("role")).toBe("manual");
    expect((form.get("file") as File).name).toBe("navod.pdf");
    expect(Object.keys(post.headers).map((k) => k.toLowerCase())).not.toContain("content-type");
    expect(await screen.findByText("nahráno")).toBeInTheDocument();
  });

  it("fotka z foťáku jde nahrát (capture=environment) a duplicita se ohlásí", async () => {
    mockFetch([
      [/^GET \/items\/item1\/files$/, () => []],
      [/^POST \/files$/, () => ({ file: links[0].file, link: null, duplicate: true })],
    ]);
    renderWithProviders(<FileGallery kind="item" id="item1" canWrite />);
    const camera = await screen.findByTestId("camera-input");
    expect(camera).toHaveAttribute("capture", "environment");
    expect(camera).toHaveAttribute("accept", "image/*");
    fireEvent.change(camera, {
      target: { files: [new File(["x"], "a.jpg", { type: "image/jpeg" })] },
    });
    expect(await screen.findByText("už existuje, použit stávající")).toBeInTheDocument();
  });

  it("413 a 422 při nahrávání ukáže česky srozumitelné chyby po souborech", async () => {
    let n = 0;
    mockFetch([
      [/^GET \/items\/item1\/files$/, () => []],
      [
        /^POST \/files$/,
        () =>
          n++ === 0
            ? problem(413, "Soubor je příliš velký (limit 20 MB).")
            : problem(422, "Nepodporovaný formát."),
      ],
    ]);
    renderWithProviders(<FileGallery kind="item" id="item1" canWrite />);
    const input = await screen.findByTestId("file-input");
    fireEvent.change(input, {
      target: {
        files: [
          new File(["x"], "velka.jpg", { type: "image/jpeg" }),
          new File(["y"], "rozbita.jpg", { type: "image/jpeg" }),
        ],
      },
    });
    expect(await screen.findByText("Soubor je příliš velký.")).toBeInTheDocument();
    expect(
      await screen.findByText(/Soubor se nepodařilo zpracovat\. Nepodporovaný formát\./),
    ).toBeInTheDocument();
  });

  it("na umístění používá endpoint /locations/{id}/files a location_id", async () => {
    const { calls } = mockFetch([
      [/^GET \/locations\/loc1\/files$/, () => []],
      [/^POST \/files$/, () => ({ file: links[0].file, link: links[0], duplicate: false })],
    ]);
    renderWithProviders(<FileGallery kind="location" id="loc1" canWrite />);
    const input = await screen.findByTestId("file-input");
    fireEvent.change(input, {
      target: { files: [new File(["x"], "a.jpg", { type: "image/jpeg" })] },
    });
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const form = calls.find((c) => c.method === "POST")!.body as FormData;
    expect(form.get("location_id")).toBe("loc1");
    expect(form.get("item_id")).toBeNull();
  });
});
