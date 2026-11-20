// Rutas tal como llegan del sistema (diálogos, arrastrar y soltar). Solo texto: la verdad sobre
// qué es cada archivo la tiene el engine.

const PROJECT_SUFFIX = ".pstudio";
const PHOTO_EXT = /\.(jpe?g|png|tiff?|webp)$/i;
const FORBIDDEN = /[<>:"/\\|?*\u0000-\u001f]/g; // mismos caracteres que rechaza el engine
const DEFAULT_NAME = "Nuevo proyecto";

function trimSeparators(path: string): string {
  return path.replace(/[\\/]+$/, "");
}

export function baseName(path: string): string {
  const parts = trimSeparators(path).split(/[\\/]/);
  return parts[parts.length - 1] ?? "";
}

export function parentDir(path: string): string {
  const trimmed = trimSeparators(path);
  const i = Math.max(trimmed.lastIndexOf("\\"), trimmed.lastIndexOf("/"));
  return i > 0 ? trimmed.slice(0, i) : trimmed;
}

/** Carpeta `<Nombre>.pstudio` o su `project.json`. */
export function isProjectPath(path: string): boolean {
  const name = baseName(path).toLowerCase();
  if (name === "project.json") return baseName(parentDir(path)).toLowerCase().endsWith(PROJECT_SUFFIX);
  return name.endsWith(PROJECT_SUFFIX);
}

/** La carpeta del proyecto, aunque se haya elegido su `project.json`. */
export function projectFolder(path: string): string {
  return baseName(path).toLowerCase() === "project.json" ? parentDir(path) : trimSeparators(path);
}

function cleanName(name: string): string {
  return name.replace(FORBIDDEN, "").replace(/\s+/g, " ").replace(/^[\s.]+|[\s.]+$/g, "").slice(0, 100);
}

/** Nombre para un proyecto hecho con estas fotos: el de su carpeta (o la carpeta soltada). */
export function suggestProjectName(paths: string[]): string {
  const first = paths[0];
  if (!first) return DEFAULT_NAME;
  const folder = PHOTO_EXT.test(first) ? parentDir(first) : trimSeparators(first);
  if (/^[A-Za-z]:$/.test(folder) || folder === "") return DEFAULT_NAME; // raíz de una unidad
  return cleanName(baseName(folder)) || DEFAULT_NAME;
}

export type Drop =
  | { kind: "none" }
  | { kind: "open"; path: string }
  | { kind: "create"; photos: string[]; name: string };

/** Qué hacer con lo que se soltó en la pantalla de inicio. */
export function classifyDrop(paths: string[]): Drop {
  if (paths.length === 0) return { kind: "none" };
  const project = paths.find(isProjectPath);
  if (project) return { kind: "open", path: projectFolder(project) };
  return { kind: "create", photos: paths, name: suggestProjectName(paths) };
}
