// Íconos de trazo, 20×20, dibujados acá (sin una librería entera para media docena).
const PATHS = {
  plus: "M10 4v12M4 10h12",
  folder: "M3 6.5A1.5 1.5 0 0 1 4.5 5h3l1.5 2h6.5A1.5 1.5 0 0 1 17 8.5v6A1.5 1.5 0 0 1 15.5 16h-11A1.5 1.5 0 0 1 3 14.5z",
  close: "M5.5 5.5l9 9M14.5 5.5l-9 9",
  photo: "M3.5 5h13v10h-13zM3.5 13l3.5-3.5 3 3 2-2 4.5 4.5M12.5 8.25a.75.75 0 1 0 0-.01",
  alert: "M10 3.5l7 12.5H3zM10 8.5v3.5M10 14.2v.1",
  check: "M4.5 10.5l3.5 3.5 7.5-8",
  back: "M12 4.5L6.5 10l5.5 5.5",
  chevron: "M7.5 5l5 5-5 5",
  undo: "M7.5 5L4 8.5 7.5 12M4.5 8.5h7a4 4 0 0 1 0 8H9",
  redo: "M12.5 5L16 8.5 12.5 12M15.5 8.5h-7a4 4 0 0 0 0 8H11",
  compare: "M10 3.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 1 0 0-13zM10 3.5v13M10 6.5l3.5 3.5M10 10.5l3 3",
  rotateLeft: "M4.5 7.5A6 6 0 1 1 4 11M4.5 3.5v4h4",
  rotateRight: "M15.5 7.5A6 6 0 1 0 16 11M15.5 3.5v4h-4",
  crop: "M6 2.5V14h11.5M2.5 6H14v11.5",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
