import { describe, expect, it } from "vitest";
import { formatBytes, formatNumber, formatPercent, titleCase } from "./format";

describe("formatBytes", () => {
  it("formats zero", () => {
    expect(formatBytes(0)).toBe("0 B");
  });

  it("formats decimal (1000-based) units, matching TERABYTE_BYTES's convention", () => {
    expect(formatBytes(1000)).toBe("1.00 KB");
    expect(formatBytes(1_000_000_000_000)).toBe("1.00 TB");
  });

  it("handles exact powers of 1000 without floating-point drift (Math.log10(1000) === 2.9999999999999996 in JS)", () => {
    expect(formatBytes(1_000_000)).toBe("1.00 MB");
    expect(formatBytes(1_000_000_000)).toBe("1.00 GB");
  });

  it("returns an em dash for non-finite input rather than throwing or showing NaN", () => {
    expect(formatBytes(Number.NaN)).toBe("—");
  });
});

describe("formatNumber", () => {
  it("adds thousands separators", () => {
    expect(formatNumber(1234567)).toBe("1,234,567");
  });
});

describe("formatPercent", () => {
  it("converts a fraction to a percentage string", () => {
    expect(formatPercent(0.256)).toBe("25.6%");
  });
});

describe("titleCase", () => {
  it("title-cases a snake_case enum value", () => {
    expect(titleCase("hmac_pseudonymization")).toBe("Hmac Pseudonymization");
  });

  it("handles a single word", () => {
    expect(titleCase("certified")).toBe("Certified");
  });
});
