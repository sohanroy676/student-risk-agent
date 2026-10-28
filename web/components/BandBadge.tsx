// The band is shown as words as well as colour, so it reads without colour vision.
export default function BandBadge({ band }: { band: "amber" | "red" }) {
  return (
    <span className={`badge badge-${band}`}>
      {band === "red" ? "Red band" : "Amber band"}
    </span>
  );
}
