import { splitBox } from "./ranking";
import type { BBox, Constraints } from "./types";

export function parseBounds(values: string[]): BBox | undefined {
  if (!values.some(Boolean)) return undefined;
  if (values.some(value => !value)) throw new Error("Enter all four bounding box coordinates.");
  const box = values.map(Number) as BBox;
  splitBox(box);
  return box;
}

export function parseDates(start: string, end: string): Pick<Constraints, "start" | "end"> {
  if (start && end && start > end) throw new Error("Start date must be on or before the end date.");
  return {
    start: start ? start + "T00:00:00Z" : undefined,
    end: end ? end + "T23:59:59.999Z" : undefined,
  };
}
