/* Generado por scripts/gen-types.mjs desde engine/schema/rpc-1.schema.json. No editar. */

/**
 * Contrato JSON-RPC 1 entre la app y el engine de PROMPT STUDIO.
 */
export interface Rpc {
  methods: Methods;
  events: Events;
}
export interface Methods {
  "asset.apply_plan": {
    params: ApplyPlanParams;
    result: StackState;
  };
  "asset.export": {
    params: ExportParams;
    result: Exported;
  };
  "asset.history": {
    params: AssetParams;
    result: History;
  };
  "asset.jump": {
    params: JumpParams;
    result: StackState;
  };
  "asset.redo": {
    params: AssetParams;
    result: StackState;
  };
  "asset.reset": {
    params: AssetParams;
    result: StackState;
  };
  "asset.set_stack": {
    params: SetStackParams;
    result: StackState;
  };
  "asset.state": {
    params: AssetParams;
    result: StackState;
  };
  "asset.undo": {
    params: AssetParams;
    result: StackState;
  };
  "asset.undo_group": {
    params: GroupParams;
    result: UndoGroupResult;
  };
  "engine.version": {
    params: NoParams;
    result: EngineVersion;
  };
  "image.info": {
    params: PathParams;
    result: ImageInfo;
  };
  ping: {
    params: NoParams;
    result: string;
  };
  "plan.create": {
    params: PlanParams;
    result: PlanCreated;
  };
  "plan.draft": {
    params: DraftParams;
    result: PlanDraft;
  };
  "preview.render": {
    params: PreviewParams;
    result: PreviewImage;
  };
  "project.close": {
    params: NoParams;
    result: null;
  };
  "project.create": {
    params: CreateParams;
    result: ProjectInfo;
  };
  "project.import": {
    params: ImportParams;
    result: ImportResult;
  };
  "project.info": {
    params: NoParams;
    result: ProjectInfo;
  };
  "project.open": {
    params: OpenParams;
    result: ProjectInfo;
  };
  "project.relink": {
    params: RelinkParams;
    result: AssetSummary;
  };
  "recent.forget": {
    params: ForgetParams;
    result: RecentList;
  };
  "recent.list": {
    params: NoParams;
    result: RecentList;
  };
  "thumbnail.get": {
    params: ThumbParams;
    result: Thumbnail;
  };
}
export interface ApplyPlanParams {
  asset: string;
  plan: EditPlan;
  label?: string | null;
  group_id?: string | null;
}
export interface EditPlan {
  schema_version?: "1.0";
  /**
   * Id del asset en el proyecto
   */
  asset?: string | null;
  source_prompt?: string | null;
  operations?: (
    | Exposure
    | AutoExposure
    | Contrast
    | Highlights
    | Shadows
    | Whites
    | Blacks
    | WhiteBalance
    | AutoWhiteBalance
    | Saturation
    | Vibrance
    | Crop
    | Rotate
    | Straighten
    | Resize
    | Sharpen
    | Denoise
    | Vignette
  )[];
  export?: Export | null;
  explanation?: string | null;
  unsupported?: Unsupported[];
  clarification?: string | null;
}
export interface Exposure {
  op: "exposure";
  /**
   * Pasos de exposición (EV)
   */
  ev?: number;
}
export interface AutoExposure {
  op: "auto_exposure";
  strength?: number;
}
export interface Contrast {
  /**
   * -100…100; 0 = sin cambio
   */
  amount?: number;
  op: "contrast";
}
export interface Highlights {
  /**
   * -100…100; 0 = sin cambio
   */
  amount?: number;
  op: "highlights";
}
export interface Shadows {
  /**
   * -100…100; 0 = sin cambio
   */
  amount?: number;
  op: "shadows";
}
export interface Whites {
  /**
   * -100…100; 0 = sin cambio
   */
  amount?: number;
  op: "whites";
}
export interface Blacks {
  /**
   * -100…100; 0 = sin cambio
   */
  amount?: number;
  op: "blacks";
}
export interface WhiteBalance {
  op: "white_balance";
  /**
   * Negativo = más frío (azul)
   */
  temperature_shift?: number;
  /**
   * Negativo = más verde, positivo = más magenta
   */
  tint_shift?: number;
}
export interface AutoWhiteBalance {
  op: "auto_white_balance";
  method?: "gray_world" | "white_patch";
}
export interface Saturation {
  /**
   * -100…100; 0 = sin cambio
   */
  amount?: number;
  op: "saturation";
}
export interface Vibrance {
  /**
   * -100…100; 0 = sin cambio
   */
  amount?: number;
  op: "vibrance";
}
export interface Crop {
  op: "crop";
  aspect_ratio?: ("1:1" | "4:5" | "5:4" | "3:2" | "2:3" | "4:3" | "3:4" | "16:9" | "9:16") | null;
  rect?: Rect | null;
  anchor?: "center" | "subject_or_center" | "top" | "bottom" | "left" | "right";
}
/**
 * Rectángulo en fracciones de la imagen (0…1), con origen arriba a la izquierda.
 */
export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}
export interface Rotate {
  op: "rotate";
  /**
   * Positivo = horario
   */
  degrees?: number;
}
export interface Straighten {
  op: "straighten";
  degrees?: number;
}
export interface Resize {
  op: "resize";
  width?: number | null;
  height?: number | null;
  /**
   * contain: entra en la caja; cover: la cubre y recorta; exact: deforma
   */
  fit?: "contain" | "cover" | "exact";
}
export interface Sharpen {
  op: "sharpen";
  amount?: number;
  radius?: number;
}
export interface Denoise {
  op: "denoise";
  strength?: number;
}
export interface Vignette {
  op: "vignette";
  /**
   * Negativo = oscurece los bordes
   */
  amount?: number;
  midpoint?: number;
}
/**
 * Lo que no se indica sale del preset (docs/EXPORT_PRESETS.md) o de la fuente.
 */
export interface Export {
  preset?:
    | ("original" | "high_quality" | "web" | "catalog_square" | "social_vertical" | "story_9x16")
    | null;
  format?: ("jpeg" | "png" | "webp" | "tiff") | null;
  quality?: number | null;
  color_space?: ("sRGB" | "Display P3") | null;
  metadata?: ("keep" | "strip" | "strip_gps") | null;
}
export interface Unsupported {
  /**
   * Parte del pedido que no se puede hacer
   */
  request: string;
  reason: string;
  alternative?: string | null;
}
export interface StackState {
  asset: string;
  stack: EditPlan;
  cursor: number;
  label: string;
  can_undo: boolean;
  can_redo: boolean;
  changed: boolean;
  export_hint: Resize | null;
}
export interface ExportParams {
  asset: string;
  preset?:
    "original" | "high_quality" | "web" | "catalog_square" | "social_vertical" | "story_9x16";
  out_dir?: string | null;
}
export interface Exported {
  path: string;
  out_dir: string;
  ms: number;
}
export interface AssetParams {
  asset: string;
}
export interface History {
  cursor: number;
  entries: HistoryItem[];
}
export interface HistoryItem {
  label: string;
  group_id: string | null;
  at: string;
}
export interface JumpParams {
  asset: string;
  index: number;
}
export interface SetStackParams {
  asset: string;
  stack: EditPlan;
  label: string;
  group_id?: string | null;
}
export interface GroupParams {
  group_id: string;
}
export interface UndoGroupResult {
  undone: string[];
  skipped: string[];
}
export interface NoParams {}
export interface EngineVersion {
  pstudio: string;
  python: string;
  libvips: string;
}
export interface PathParams {
  path: string;
}
export interface ImageInfo {
  width: number;
  height: number;
  bands: number;
  format: string;
}
export interface PlanParams {
  prompt: string;
  asset?: string | null;
  provider?: "auto" | "rules" | "local_llm";
}
export interface PlanCreated {
  plan: EditPlan | null;
  provider: string;
  ms: number;
  warnings: string[];
  errors: string[];
  draft: EditPlan | null;
  export_hint: Resize | null;
}
export interface DraftParams {
  asset: string;
  plan: EditPlan;
  stack?: EditPlan | null;
}
export interface PlanDraft {
  draft: EditPlan;
  export_hint: Resize | null;
}
export interface PreviewParams {
  asset: string;
  stack?: EditPlan | null;
  long_side?: number;
}
export interface PreviewImage {
  path: string;
  width: number;
  height: number;
  proxy_ms: number;
  render_ms: number;
  encode_ms: number;
}
export interface CreateParams {
  dir: string;
  name: string;
}
export interface ProjectInfo {
  path: string;
  name: string;
  cache_dir: string;
  assets: AssetSummary[];
}
export interface AssetSummary {
  id: string;
  file: string;
  edited: boolean;
  missing: boolean;
}
export interface ImportParams {
  /**
   * @minItems 1
   */
  paths: [string, ...string[]];
  recursive?: boolean;
}
export interface ImportResult {
  added: AssetSummary[];
  duplicates: number;
  unsupported: string[];
}
export interface OpenParams {
  path: string;
}
export interface RelinkParams {
  asset: string;
  path: string;
}
export interface ForgetParams {
  path: string;
}
export interface RecentList {
  items: RecentProject[];
}
export interface RecentProject {
  path: string;
  name: string;
  opened_at: string;
  exists: boolean;
}
export interface ThumbParams {
  asset: string;
}
export interface Thumbnail {
  asset: string;
  path: string | null;
}
export interface Events {
  "thumbnail.ready": ThumbnailReady;
}
export interface ThumbnailReady {
  asset: string;
  path: string | null;
  error: string | null;
}
