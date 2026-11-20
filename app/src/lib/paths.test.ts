import { describe, expect, it } from "vitest";
import { baseName, classifyDrop, isProjectPath, parentDir, projectFolder, suggestProjectName } from "./paths";

describe("rutas", () => {
  it("baseName y parentDir con barras de Windows y POSIX", () => {
    expect(baseName("C:\\Fotos\\Viaje\\a.jpg")).toBe("a.jpg");
    expect(baseName("/home/u/Viaje/")).toBe("Viaje");
    expect(parentDir("C:\\Fotos\\Viaje\\a.jpg")).toBe("C:\\Fotos\\Viaje");
    expect(parentDir("/home/u/a.jpg")).toBe("/home/u");
  });

  it("reconoce carpetas de proyecto y su project.json", () => {
    expect(isProjectPath("D:\\P\\Verano.pstudio")).toBe(true);
    expect(isProjectPath("D:\\P\\Verano.PSTUDIO\\")).toBe(true);
    expect(isProjectPath("D:\\P\\Verano.pstudio\\project.json")).toBe(true);
    expect(isProjectPath("D:\\P\\foto.jpg")).toBe(false);
    expect(isProjectPath("D:\\P\\project.json")).toBe(false);
    expect(projectFolder("D:\\P\\Verano.pstudio\\project.json")).toBe("D:\\P\\Verano.pstudio");
  });

  it("propone el nombre de la carpeta de las fotos", () => {
    expect(suggestProjectName(["C:\\Fotos\\Boda Ana\\a.jpg", "C:\\Fotos\\Boda Ana\\b.png"])).toBe("Boda Ana");
    expect(suggestProjectName(["C:\\Fotos\\Boda Ana"])).toBe("Boda Ana"); // carpeta soltada
    expect(suggestProjectName(["C:\\a.jpg"])).toBe("Nuevo proyecto"); // raíz de una unidad
    expect(suggestProjectName(["C:\\x\\Fotos: 2026?\\a.jpg"])).toBe("Fotos 2026");
    expect(suggestProjectName([])).toBe("Nuevo proyecto");
  });

  it("soltar un proyecto lo abre; soltar fotos propone crear uno", () => {
    expect(classifyDrop(["D:\\P\\Verano.pstudio"])).toEqual({ kind: "open", path: "D:\\P\\Verano.pstudio" });
    expect(classifyDrop(["D:\\a.jpg", "D:\\P\\Verano.pstudio\\project.json"])).toEqual({
      kind: "open",
      path: "D:\\P\\Verano.pstudio",
    });
    expect(classifyDrop(["D:\\Viaje\\a.jpg", "D:\\Viaje\\b.jpg"])).toEqual({
      kind: "create",
      photos: ["D:\\Viaje\\a.jpg", "D:\\Viaje\\b.jpg"],
      name: "Viaje",
    });
    expect(classifyDrop([])).toEqual({ kind: "none" });
  });
});
