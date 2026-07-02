import { describe, expect, it } from "vitest";
import { prepareSpec, parseSpec } from "./prepare-spec";
import type { VLSpec } from "./types";

describe("AVA-inspired visual linter rules", () => {
  it("Legend-Linter: suppresses legend when distinct groups exceed 8", () => {
    const rawSpec: VLSpec = {
      data: {
        values: [
          { country: "C1", groupField: "G1", value: 10 },
          { country: "C2", groupField: "G2", value: 10 },
          { country: "C3", groupField: "G3", value: 10 },
          { country: "C4", groupField: "G4", value: 10 },
          { country: "C5", groupField: "G5", value: 10 },
          { country: "C6", groupField: "G6", value: 10 },
          { country: "C7", groupField: "G7", value: 10 },
          { country: "C8", groupField: "G8", value: 10 },
          { country: "C9", groupField: "G9", value: 10 },
          { country: "C10", groupField: "G10", value: 10 },
        ],
      },
      encoding: {
        x: { field: "country", type: "nominal" },
        y: { field: "value", type: "quantitative" },
        color: { field: "groupField", type: "nominal" },
      },
    };

    const parsed = parseSpec(rawSpec, ["blue", "red"]);
    expect(parsed.colorField).toBeNull(); // Suppressed because 10 groups > 8
    expect(parsed.distinctGroups).toEqual([]);
  });

  it("Legend-Linter: keeps legend when distinct groups are 8 or fewer", () => {
    const rawSpec: VLSpec = {
      data: {
        values: [
          { country: "C1", groupField: "G1", value: 10 },
          { country: "C2", groupField: "G2", value: 10 },
          { country: "C3", groupField: "G3", value: 10 },
        ],
      },
      encoding: {
        x: { field: "country", type: "nominal" },
        y: { field: "value", type: "quantitative" },
        color: { field: "groupField", type: "nominal" },
      },
    };

    const parsed = parseSpec(rawSpec, ["blue", "red"]);
    expect(parsed.colorField).toBe("groupField"); // Kept because 3 groups <= 8
    expect(parsed.distinctGroups).toEqual(["G1", "G2", "G3"]);
  });

  it("Outlier-Scale: applies log scale if positive values span > 2 orders of magnitude", () => {
    const rawSpec: VLSpec = {
      data: {
        values: [
          { country: "ZAF", value: 380000 },
          { country: "TUV", value: 60 }, // Ratio = 6333x
        ],
      },
      encoding: {
        x: { field: "country", type: "nominal" },
        y: { field: "value", type: "quantitative" },
      },
    };

    const prepared = prepareSpec(rawSpec);
    expect(prepared.encoding?.y?.scale?.type).toBe("log");
  });

  it("Outlier-Scale: does not apply log scale if values contain zero or negative numbers", () => {
    const rawSpec: VLSpec = {
      data: {
        values: [
          { country: "ZAF", value: 380000 },
          { country: "TUV", value: 0 }, // Contains zero
        ],
      },
      encoding: {
        x: { field: "country", type: "nominal" },
        y: { field: "value", type: "quantitative" },
      },
    };

    const prepared = prepareSpec(rawSpec);
    expect(prepared.encoding?.y?.scale?.type).toBeUndefined();
  });

  it("Chronological-Timeline: automatically sorts timeline field ascending", () => {
    const rawSpec: VLSpec = {
      data: {
        values: [
          { year: "2024", value: 10 },
          { year: "2020", value: 5 },
        ],
      },
      encoding: {
        x: { field: "year", type: "ordinal" },
        y: { field: "value", type: "quantitative" },
      },
    };

    const prepared = prepareSpec(rawSpec);
    expect(prepared.encoding?.x?.sort).toBe("ascending");
  });
});
