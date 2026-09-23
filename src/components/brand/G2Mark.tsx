/**
 * The G2 mark.
 *
 * A heart drawn as a single continuous line, split down the middle so each half
 * carries one character of the name: the left half is a "G" (the bowl is the
 * left lobe, plus its crossbar), and the right half is a "2" (the lobe is its
 * top arc, the steep inner edge its diagonal, and the flattened run into the
 * tip its base). Two strokes total — the outline and the G's bar — because the
 * bar branches off the bowl and cannot be reached without lifting the pen.
 *
 * Stroke-only in `currentColor`, so it inherits colour and size from whatever
 * places it. The favicon at `src/app/icon.svg` carries the same geometry with
 * explicit colours; change both together.
 */
export function G2Mark({
  className,
  strokeWidth = 1.8,
}: {
  className?: string;
  strokeWidth?: number;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <path d="M12 20.8C8.5 18.4 4.5 14.9 3.2 11.5 1.8 7.9 4.3 4.5 7.6 4.5 9.7 4.5 11.2 6 12 7.9 12.8 6 14.3 4.5 16.4 4.5 19.7 4.5 22.2 7.9 20.8 11.5 20 14.4 17.9 17 15.8 18.8 14.7 19.8 13.3 20.5 12 20.8Z" />
      <path d="M11.3 11.8H7.7" />
    </svg>
  );
}
