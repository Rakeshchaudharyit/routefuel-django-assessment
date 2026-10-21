// Keep backend decimal strings intact. No floating point money conversion or calculations.
export function decimal(value: string | null | undefined): string {
  if (value == null || !/^-?\d+(\.\d+)?$/.test(value)) return "—";
  const [whole, fraction] = value.split(".");
  return (
    whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",") +
    (fraction ? `.${fraction}` : "")
  );
}
export const usd = (value: string | null | undefined) =>
  value == null ? "—" : `$${decimal(value)}`;
export const miles = (value: number | undefined) =>
  value == null
    ? "—"
    : `${value.toLocaleString("en-US", { maximumFractionDigits: 1 })} mi`;
export function duration(minutes: number | undefined) {
  if (minutes == null) return "—";
  const rounded = Math.round(minutes);
  return `${Math.floor(rounded / 60)}h ${rounded % 60}m`;
}
