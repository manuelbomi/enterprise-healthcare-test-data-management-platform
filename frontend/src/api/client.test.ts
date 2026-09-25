import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiGet, apiPost } from "./client";

describe("apiGet", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns parsed JSON on a 200 response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await apiGet<{ status: string }>("/api/v1/health");
    expect(result).toEqual({ status: "ok" });
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/health", expect.objectContaining({ method: "GET" }));
  });

  it("builds a query string from params, omitting undefined/null/empty values", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("[]", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await apiGet("/api/v1/catalog", { category: "phi", dataset: undefined, needs_review: false, empty: "" });

    const calledUrl = fetchMock.mock.calls[0][0] as string;
    expect(calledUrl).toContain("category=phi");
    expect(calledUrl).toContain("needs_review=false");
    expect(calledUrl).not.toContain("dataset=");
    expect(calledUrl).not.toContain("empty=");
  });

  it("throws an ApiError carrying the real HTTP status and detail on a well-known 503", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Catalog artifact not found." }), { status: 503 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiGet("/api/v1/catalog")).rejects.toMatchObject({
      status: 503,
      detail: "Catalog artifact not found.",
    });
  });

  it("ApiError is distinguishable via instanceof for pages that branch on 503 vs. other failures", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 404, statusText: "Not Found" }));
    vi.stubGlobal("fetch", fetchMock);

    try {
      await apiGet("/api/v1/catalog/x/y/z");
      expect.fail("expected apiGet to throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(404);
    }
  });
});

describe("apiPost", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends a JSON body with a Content-Type header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);

    await apiPost("/api/v1/lifecycle/dataset-versions", { dataset_name: "demo" });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ dataset_name: "demo" }));
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });
});
