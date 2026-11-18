import { describe, expect, it } from "vitest";
import { chartTime, dmy, dmyhm, hm, hms, inr, inrShort, num, pct, pnlClass, signed } from "../utils/format";

describe("number formatting", () => {
  it("uses Indian digit grouping and a dash for missing values", () => {
    expect(num(1234567.891)).toBe("12,34,567.89");
    expect(num(null)).toBe("—");
    expect(num(undefined)).toBe("—");
    expect(num(Number.NaN)).toBe("—");
  });

  it("formats rupees with an optional sign and a real minus", () => {
    expect(inr(1234.5)).toBe("₹1,234.50");
    expect(inr(-1234.5)).toBe("−₹1,234.50");
    expect(inr(10, true)).toBe("+₹10.00");
    expect(inr(0, true)).toBe("₹0.00");
    expect(inr(null)).toBe("—");
  });

  it("shortens large rupee amounts to lakh / crore", () => {
    expect(inrShort(180326)).toBe("+₹1.80L");
    expect(inrShort(-25000000)).toBe("−₹2.50Cr");
    expect(inrShort(4500, false)).toBe("₹4,500");
  });

  it("formats percentages and signed numbers", () => {
    expect(pct(12.345)).toBe("12.3%");
    expect(pct(null)).toBe("—");
    expect(signed(5)).toBe("+5.00");
    expect(signed(-5.5, 1)).toBe("−5.5");
    expect(signed(0)).toBe("0.00");
  });

  it("picks the gain/loss colour class from the sign", () => {
    expect(pnlClass(10)).toBe("text-gain");
    expect(pnlClass(-1)).toBe("text-loss");
    expect(pnlClass(0)).toBe("");
    expect(pnlClass(null)).toBe("");
  });
});

describe("date and time formatting", () => {
  it("slices wall-clock ISO strings without timezone conversion", () => {
    expect(hm("2026-11-11T10:15:00")).toBe("10:15");
    expect(hms("2026-11-11T10:15:30")).toBe("10:15:30");
    expect(hm(null)).toBe("—");
  });

  it("formats dates the same way regardless of the browser timezone", () => {
    expect(dmy("2026-11-17")).toBe("17 Nov 2026");
    expect(dmy("2026-11-17T23:59:00")).toBe("17 Nov 2026");
    expect(dmyhm("2026-11-17T10:15")).toBe("17 Nov 10:15");
    expect(dmy(undefined)).toBe("—");
  });

  it("converts IST wall clock to chart seconds as if it were UTC", () => {
    expect(chartTime("2026-11-17T00:00:00")).toBe(Date.UTC(2026, 10, 17) / 1000);
    expect(chartTime("2026-11-17")).toBe(Date.UTC(2026, 10, 17) / 1000);
  });
});
