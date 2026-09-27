"use client";

import { useEffect, useRef, useState } from "react";
import type { ResidueRef } from "@/lib/contracts";
import type { ViewerCommand } from "@/lib/viewer-agent";
import { cameraChanged } from "@/lib/viewer-scene";
import { bindingMatches, exactResidue, nativeOperationBound, nativeRepresentationIntentCurrent,
  nativeTokenAfterBinding, sceneMatches,
  type NativeCameraState, type NativeSceneState } from "@/lib/saved-scene";
import { alignmentMat4, atomPickFailure, catalogSelectionReadback, nativeDeadline, nativeIntentCurrent,
  ordinaryFocusCurrent, residueFromNativeSites,
  rowsForAuthoritativeResidue, sameAtomRef, sameResidueRef, transformPoint, validateReadyCatalog,
  type AtomCatalog, type AtomRefV1, type RigidAlignment } from "@/lib/comparison";
import type { AtomDistance } from "@/lib/comparison";

export type ViewerRepresentation = "cartoon" | "ball-and-stick" | "surface";
export interface ViewerSource {
  /** Stable opaque handle. Text must originate from a local file or loopback bytes endpoint. */
  handle: string;
  text: string;
  format: "pdb" | "mmcif";
  modelIndex?: number;
}
export interface MolstarViewerProps {
  source?: ViewerSource | null;
  representation: ViewerRepresentation;
  highlight?: ResidueRef | null;
  residues?: ResidueRef[];
  onSelect?: (residue: ResidueRef | null) => void;
  onLoadState?: (source: ViewerSource, state: "loading" | "ready" | "error", message?: string) => void;
  onFocusResult?: (source: ViewerSource, residue: ResidueRef, found: boolean) => void;
  onBridge?: (bridge: ViewerBridge | null) => void;
  onManualInteraction?: () => void;
  emptyMessage?: string;
  emptyIsError?: boolean;
  atomCatalog?: AtomCatalog | null;
  measureMode?: boolean;
  onAtomPick?: (ref: AtomRefV1, layer: "reference" | "moving") => void;
  comparison?: { source: ViewerSource; catalog: AtomCatalog; alignment: RigidAlignment;
    aligned: boolean; referenceVisible: boolean; movingVisible: boolean } | null;
  focusPair?: { reference: AtomRefV1; moving: AtomRefV1; token: number } | null;
  selectedAtoms?: AtomRefV1[];
  distanceResult?: AtomDistance | null;
}

type Plugin = import("molstar/lib/mol-plugin/context").PluginContext;
type StructureSelector = Awaited<ReturnType<Plugin["builders"]["structure"]["createStructure"]>>;
type RepresentationSelector = Awaited<ReturnType<Plugin["builders"]["structure"]["representation"]["addRepresentation"]>>;
type ImagePass = ReturnType<NonNullable<Plugin["canvas3d"]>["getImagePass"]>;
export interface ViewerBinding { sessionId: string; clientId: string; generation: number; sourceHandle: string; catalogHash: string; actionRevision: number }
export interface ViewerQaSnapshot {
  ready: boolean; sourceHandle: string | null; sessionId: string | null; generation: number | null;
  representation: ViewerRepresentation | null; molstarRepresentation: string | null;
  selection: ResidueRef | null;
  selectionError: string | null;
  camera: { position: number[]; target: number[]; radius: number; distance: number } | null;
  nativeCamera: NativeCameraState | null; theme: "dark" | "light";
  backgroundColor: number | null;
  lastAck: { commandId: string; status: "applied" | "no_change" | "failed"; reasonCode: string | null } | null;
  measureMode: boolean; lastAtomPick: { layer: "reference" | "moving"; ref: AtomRefV1; nativeSourceIndex: number;
    worldCoordinate_A: number[] } | null;
  catalogReady: boolean;
  atomPickRevision: number;
  nativeBusy: boolean; nativeUpdating: boolean; nativeAnimating: boolean;
  cameraTransitioning: boolean; m10QueuePending: number;
  nativeClickRevision: number;
  lastNativeClick: { kind: string; size: number | null; pluginBusy: boolean; measureMode: boolean;
    accepted: boolean; reason: string } | null;
  qaAtoms: { layer: "reference" | "moving"; ref: AtomRefV1; worldCoordinate_A: number[];
    canvasPixel: [number, number]; depth: number }[];
  layers: { layer: "reference" | "moving"; sourceHandle: string; visible: boolean;
    transform: number[]; nativeAtomCount: number }[];
}
export interface ViewerBridge {
  bind(binding: ViewerBinding | null): void;
  snapshot(): ViewerQaSnapshot;
  apply(command: ViewerCommand): Promise<{ status: "applied" | "no_change" | "failed"; reasonCode: string | null }>;
  captureScene(expected: ViewerBinding): Promise<NativeSceneState>;
  restoreScene(expected: ViewerBinding, scene: NativeSceneState): Promise<NativeSceneState>;
  captureFigure(expected: ViewerBinding, scene: NativeSceneState): Promise<{ state: NativeSceneState; pngBase64: string; width: number; height: number }>;
  invalidate(): void;
  cancelNative(): void;
}
type Instance = { plugin: Plugin; structure: StructureSelector; source: ViewerSource; ligand?: StructureSelector;
  repr?: RepresentationSelector; ligandRepr?: RepresentationSelector; queue: Promise<void>;
  representation: ViewerRepresentation; binding: ViewerBinding | null; selected: ResidueRef | null;
  selectionError: string | null;
  readSelected: () => ResidueRef | null; suppressSelectionCallback: boolean; lastAck: ViewerQaSnapshot["lastAck"];
  canvas: HTMLCanvasElement; contextLost: boolean; manualRevision: number; operationToken: number;
  ownThemeMutation: "dark" | "light" | null; imagePass: ImagePass | null;
  movingStructure?: StructureSelector; movingRepr?: RepresentationSelector; movingTransformRef?: string;
  alignmentMatrix: number[]; lastAtomPick: ViewerQaSnapshot["lastAtomPick"]; overlayError?: string;
  atomPickRevision: number;
  nativeClickRevision: number; lastNativeClick: ViewerQaSnapshot["lastNativeClick"]; m10QueuePending: number;
  distanceAnnotationRef?: string; validatedCatalogs: Map<string, { hash: string; catalog: AtomCatalog }> };

function nativeMainRepresentationReady(current: Instance): boolean {
  return !!current.repr?.ref && !!current.plugin.state.data.cells.get(current.repr.ref)?.obj?.data?.repr;
}

declare global { interface Window { __protviewQaSnapshot?: () => ViewerQaSnapshot } }

function requireCatalog(current: Instance, candidate: AtomCatalog | null | undefined): AtomCatalog {
  const catalog = validatedCatalog(current, candidate);
  if (!catalog) throw new Error("원자 목록 검증이 끝나지 않았습니다. 다시 읽은 뒤 선택하세요.");
  return catalog;
}

function validatedCatalog(current: Instance, catalog: AtomCatalog | null | undefined): AtomCatalog | null {
  if (!catalog) return null;
  const validated = current.validatedCatalogs.get(catalog.structure_handle);
  return validated?.catalog === catalog && validated.hash === catalog.viewer_source_sha256 ? catalog : null;
}

function cameraSnapshot(plugin: Plugin): ViewerQaSnapshot["camera"] {
  const state = plugin.canvas3d?.camera.getSnapshot();
  if (!state) return null;
  const position = Array.from(state.position), target = Array.from(state.target);
  const distance = Math.hypot(...position.map((value, index) => value - target[index]));
  if (![...position, ...target, state.radius, distance].every(Number.isFinite)) return null;
  return { position, target, radius: state.radius, distance };
}

function nativeCamera(plugin: Plugin): NativeCameraState | null {
  const state = plugin.canvas3d?.camera.getSnapshot();
  if (!state) return null;
  return { mode: state.mode, fov: state.fov, position: Array.from(state.position),
    up: Array.from(state.up), target: Array.from(state.target), radius: state.radius,
    radiusMax: state.radiusMax, fog: state.fog, clipFar: state.clipFar,
    minNear: state.minNear, minFar: state.minFar };
}

function currentTheme(): "dark" | "light" {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

async function settledFrame(): Promise<void> {
  await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
}

async function sourceHash(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

async function atomLoci(current: Instance, ref: AtomRefV1, catalog: AtomCatalog) {
  const [{ StructureElement }, { OrderedSet }] = await Promise.all([
    import("molstar/lib/mol-model/structure"), import("molstar/lib/mol-data/int")]);
  const mapped = catalog.rows.filter(row => sameAtomRef(row.ref, ref));
  if (mapped.length !== 1) throw new Error("원자 목록에서 정확한 site를 찾지 못했습니다.");
  const moving = ref.structure_handle !== current.source.handle;
  const structure = (moving ? current.plugin.state.data.cells.get(current.movingTransformRef ?? "")?.obj?.data :
    current.structure.obj?.data) as import("molstar/lib/mol-model/structure").Structure | undefined;
  if (!structure) throw new Error("원자 표시 구조가 준비되지 않았습니다.");
  const hits: { unit: typeof structure.units[number]; indices: ReturnType<typeof OrderedSet.ofSingleton> }[] = [];
  for (const unit of structure.units) {
    for (let index = 0; index < unit.elements.length; index++) {
      const element = unit.elements[index];
      if (unit.model.atomicHierarchy.atomSourceIndex.value(element) === mapped[0].viewer_source_index)
        hits.push({ unit, indices: OrderedSet.ofSingleton(index) });
    }
  }
  if (hits.length !== 1) throw new Error("Mol* 원자 site가 없거나 모호합니다.");
  return StructureElement.Loci(structure, hits as Parameters<typeof StructureElement.Loci>[1]);
}

async function authoritativeResidueLoci(current: Instance, target: ResidueRef, candidate: AtomCatalog | null | undefined) {
  const catalog = requireCatalog(current, candidate);
  if (catalog.structure_handle !== current.source.handle || target.model_number !== catalog.model_number)
    throw new Error("잔기 원본 구조 또는 모델이 표시된 구조와 다릅니다.");
  const rows = rowsForAuthoritativeResidue(catalog, target);
  if (!rows.length) throw new Error("원본 잔기 전체 site를 찾지 못했습니다.");
  const structure = current.structure.obj?.data;
  if (!structure) throw new Error("표시된 구조가 없습니다.");
  const [{ StructureElement, Unit }, { OrderedSet }] = await Promise.all([
    import("molstar/lib/mol-model/structure"), import("molstar/lib/mol-data/int")]);
  const expected = new Set(rows.map(row => row.viewer_source_index));
  const seen = new Set<number>();
  const elements: { unit: typeof structure.units[number]; indices: ReturnType<typeof OrderedSet.ofSortedArray> }[] = [];
  for (const unit of structure.units) {
    if (!Unit.isAtomic(unit) || unit.model.modelNum !== catalog.model_number)
      throw new Error("Mol* 구조에 다른 원본 모델이 섞여 있습니다.");
    const indices: number[] = [];
    for (let index = 0; index < unit.elements.length; index++) {
      const sourceIndex = unit.model.atomicHierarchy.atomSourceIndex.value(unit.elements[index]);
      if (!expected.has(sourceIndex)) continue;
      if (seen.has(sourceIndex)) throw new Error("Mol* 원자 site가 중복되었습니다.");
      seen.add(sourceIndex); indices.push(index);
    }
    if (indices.length) elements.push({ unit, indices: OrderedSet.ofSortedArray(indices) });
  }
  if (seen.size !== expected.size || !elements.length)
    throw new Error("Mol* 잔기 site가 누락되었습니다.");
  const loci = StructureElement.Loci(structure, elements as Parameters<typeof StructureElement.Loci>[1]);
  if (StructureElement.Loci.size(loci) !== rows.length) throw new Error("Mol* 잔기 site 수가 다릅니다.");
  return loci;
}

async function validateNativeCatalog(structure: import("molstar/lib/mol-model/structure").Structure,
                                     catalog: AtomCatalog): Promise<void> {
  const { StructureElement, StructureProperties, Unit } = await import("molstar/lib/mol-model/structure");
  const mapped = new Map(catalog.rows.map(row => [row.viewer_source_index, row]));
  if (catalog.offset !== 0 || catalog.rows.length !== catalog.total ||
      mapped.size !== catalog.total || structure.elementCount !== catalog.total ||
      new Set(catalog.rows.map(row => row.ref.site_index)).size !== catalog.total ||
      catalog.rows.some(row => row.ref.structure_handle !== catalog.structure_handle ||
        row.ref.residue.model_number !== catalog.model_number))
    throw new Error("Mol* 원자 수/인덱스가 원본 목록과 다릅니다.");
  const seen = new Set<number>();
  for (const unit of structure.units) {
    if (!Unit.isAtomic(unit)) throw new Error("비원자 Mol* 단위는 AtomRef에 사용할 수 없습니다.");
    for (let elementIndex = 0; elementIndex < unit.elements.length; elementIndex++) {
      const element = unit.elements[elementIndex];
      const loc = StructureElement.Location.create(structure, unit, element);
      const sourceIndex = StructureProperties.atom.sourceIndex(loc);
      const row = mapped.get(sourceIndex);
      if (!row || seen.has(sourceIndex)) throw new Error("Mol* sourceIndex가 없거나 중복되었습니다.");
      seen.add(sourceIndex);
      const ref = row.ref, alt = StructureProperties.atom.label_alt_id(loc);
      const source = unit.model.atomicConformation;
      if (ref.residue.model_number !== unit.model.modelNum ||
          ref.residue.chain_auth !== StructureProperties.chain.auth_asym_id(loc) ||
          ref.residue.seq_auth !== StructureProperties.residue.auth_seq_id(loc) ||
          ref.residue.icode !== (StructureProperties.residue.pdbx_PDB_ins_code(loc) || "") ||
          ref.residue.resname !== StructureProperties.atom.auth_comp_id(loc) ||
          ref.atom_name !== StructureProperties.atom.auth_atom_id(loc) ||
          ref.altloc !== (alt === "." || alt === "?" ? "" : alt || "") ||
          ref.element !== StructureProperties.atom.type_symbol(loc).toUpperCase() ||
          [source.x[element], source.y[element], source.z[element]].some((value, i) =>
            !Number.isFinite(value) || Math.abs(value - row.coordinate_A[i]) > 1e-4))
        throw new Error("Mol* 원자 식별자 또는 원본 좌표가 AtomRef와 다릅니다.");
    }
  }
  if (seen.size !== catalog.total) throw new Error("Mol* 원자 목록이 완전하지 않습니다.");
}

async function verifyOverlay(current: Instance, alignment: RigidAlignment, catalog: AtomCatalog,
                             aligned: boolean): Promise<void> {
  const native = (current.plugin.state.data.cells.get(current.movingTransformRef ?? "")?.transform.params as
    { transform?: { params?: { data?: ArrayLike<number> } } } | undefined)?.transform?.params?.data;
  const expected = alignmentMat4(alignment, aligned);
  if (!native || native.length !== 16 || expected.some((value, index) => Math.abs(value - native[index]) > 1e-10))
    throw new Error("Mol* 이동 구조 변환 행렬이 계산 결과와 다릅니다.");
  const anchor = catalog.rows[0];
  if (!anchor) throw new Error("이동 구조에 확인할 원자가 없습니다.");
  const loci = await atomLoci(current, anchor.ref, catalog);
  const { StructureElement } = await import("molstar/lib/mol-model/structure");
  const loc = StructureElement.Loci.getFirstLocation(loci);
  if (!loc) throw new Error("이동 구조의 원자 위치를 읽지 못했습니다.");
  const observed = loc.unit.conformation.position(loc.element,
    new Float64Array(3) as unknown as Parameters<typeof loc.unit.conformation.position>[1]);
  const intended = aligned ? transformPoint(alignment, anchor.coordinate_A) : anchor.coordinate_A;
  if (Math.hypot(...intended.map((value, i) => value - observed[i])) > 1e-4)
    throw new Error("Mol* 이동 구조 화면 좌표가 계산 결과와 다릅니다.");
}

function qaAtomScreens(current: Instance, reference: AtomCatalog | null, moving: AtomCatalog | null): ViewerQaSnapshot["qaAtoms"] {
  const camera = current.plugin.canvas3d?.camera;
  if (!camera || !validatedCatalog(current, reference)) return [];
  const result: ViewerQaSnapshot["qaAtoms"] = [];
  for (const [layer, structure, catalog] of [
    ["reference", current.structure.obj?.data, reference],
    ["moving", current.plugin.state.data.cells.get(current.movingTransformRef ?? "")?.obj?.data as
      import("molstar/lib/mol-model/structure").Structure | undefined, moving],
  ] as const) {
    const checked = validatedCatalog(current, catalog);
    if (!structure || !checked) continue;
    for (const row of checked.rows.slice(0, 128)) {
      for (const unit of structure.units) {
        if (unit.kind !== 0) continue;
        const index = Array.from(unit.elements).findIndex(element =>
          unit.model.atomicHierarchy.atomSourceIndex.value(element) === row.viewer_source_index);
        if (index < 0) continue;
        const world = unit.conformation.position(unit.elements[index], new Float64Array(3) as never);
        const pixel = camera.project(new Float64Array(4) as never, world);
        if ([...world, ...pixel].every(Number.isFinite)) result.push({ layer, ref: row.ref,
          worldCoordinate_A: Array.from(world), canvasPixel: [pixel[0], current.canvas.height - pixel[1]], depth: pixel[2] });
        break;
      }
    }
  }
  return result;
}

/** Canvas-only Mol*: no download action, remote extension, or automatic property service. */
export function MolstarViewer({ source, representation, highlight, residues, onSelect, onLoadState, onFocusResult,
  onBridge, onManualInteraction, emptyMessage, emptyIsError, atomCatalog, measureMode = false, onAtomPick,
  comparison, focusPair, selectedAtoms, distanceResult }: MolstarViewerProps) {
  const host = useRef<HTMLDivElement>(null);
  const instance = useRef<Instance | null>(null);
  const requestedRepresentation = useRef(representation);
  const requestedSource = useRef(source);
  const representationIntent = useRef({ source, representation, revision: 0 });
  if (representationIntent.current.source !== source || representationIntent.current.representation !== representation)
    representationIntent.current = { source, representation, revision: representationIntent.current.revision + 1 };
  const selectedCallback = useRef(onSelect);
  const loadCallback = useRef(onLoadState);
  const focusCallback = useRef(onFocusResult);
  const bridgeCallback = useRef(onBridge);
  const manualCallback = useRef(onManualInteraction);
  const atomRows = useRef(atomCatalog);
  const comparisonRef = useRef(comparison);
  const overlayIntent = useRef({ key: "", revision: 0 });
  const overlayKey = JSON.stringify([comparison?.source.handle, comparison?.alignment,
    comparison?.aligned, comparison?.referenceVisible, comparison?.movingVisible]);
  if (overlayIntent.current.key !== overlayKey) overlayIntent.current = { key: overlayKey,
    revision: overlayIntent.current.revision + 1 };
  const focusIntent = useRef({ token: 0, revision: 0 });
  if ((focusPair?.token ?? 0) !== focusIntent.current.token)
    focusIntent.current = { token: focusPair?.token ?? 0, revision: focusIntent.current.revision + 1 };
  const measureRef = useRef(measureMode);
  const atomPickCallback = useRef(onAtomPick);
  const [state, setState] = useState<"empty" | "loading" | "ready" | "error">("empty");
  const [error, setError] = useState("");
  const [pickError, setPickError] = useState("");
  const [catalogRevision, setCatalogRevision] = useState(0);
  requestedRepresentation.current = representation;
  requestedSource.current = source;
  selectedCallback.current = onSelect;
  loadCallback.current = onLoadState;
  focusCallback.current = onFocusResult;
  bridgeCallback.current = onBridge;
  manualCallback.current = onManualInteraction;
  atomRows.current = atomCatalog;
  comparisonRef.current = comparison;
  measureRef.current = measureMode;
  atomPickCallback.current = onAtomPick;

  useEffect(() => {
    const parent = host.current;
    if (!parent || !source) { setState("empty"); return; }
    let cancelled = false;
    let plugin: Plugin | undefined;
    let selectionSubscription: { unsubscribe(): void } | undefined;
    let atomClickSubscription: { unsubscribe(): void } | undefined;
    let themeObserver: MutationObserver | undefined;
    // React Strict Mode may mount twice. Each attempt gets its own detached-safe DOM node.
    const mount = document.createElement("div");
    const canvas = document.createElement("canvas");
    mount.className = "mw-molstar-mount";
    canvas.className = "mw-molstar-canvas";
    mount.appendChild(canvas);
    const lost = (event: Event) => {
      event.preventDefault();
      const current = instance.current;
      if (current?.canvas === canvas) current.contextLost = true;
      setState("error"); setError("WebGL 연결이 끊어졌습니다. 구조를 다시 불러오세요.");
      loadCallback.current?.(source, "error", "WebGL context lost");
    };
    canvas.addEventListener("webglcontextlost", lost);
    const manual = (event: Event) => { if (event.isTrusted) {
      if (instance.current?.canvas === canvas) instance.current.manualRevision += 1;
      manualCallback.current?.();
    } };
    canvas.addEventListener("pointerdown", manual);
    canvas.addEventListener("wheel", manual);
    parent.appendChild(mount);
    setState("loading");
    setError("");
    loadCallback.current?.(source, "loading");

    const start = async () => {
      const [{ PluginContext }, { DefaultPluginSpec, PluginSpec }, { PluginConfig }, { PluginBehaviors }, { StructureElement, StructureProperties, Unit }, { Color }, { Binding }, { ButtonsType }] = await Promise.all([
        import("molstar/lib/mol-plugin/context"),
        import("molstar/lib/mol-plugin/spec"),
        import("molstar/lib/mol-plugin/config"),
        import("molstar/lib/mol-plugin/behavior"),
        import("molstar/lib/mol-model/structure"),
        import("molstar/lib/mol-util/color"),
        import("molstar/lib/mol-util/binding"),
        import("molstar/lib/mol-util/input/input-observer"),
      ]);
      if (cancelled) return;
      const spec = DefaultPluginSpec();
      spec.actions = [];
      // Every primary click replaces one selection. Modifier clicks use the
      // same binding; toggle/extend would permit ambiguous multi-residue loci.
      const primary = Binding([Binding.Trigger(ButtonsType.Flag.Primary)]);
      spec.behaviors = [
        PluginSpec.Behavior(PluginBehaviors.Representation.HighlightLoci),
        PluginSpec.Behavior(PluginBehaviors.Representation.SelectLoci, {
          bindings: { clickSelect: Binding.Empty, clickSelectOnly: primary,
            clickToggle: Binding.Empty, clickToggleExtend: Binding.Empty,
            clickDeselect: Binding.Empty, clickDeselectAllOnEmpty: primary },
          preferAtoms: true,
        }),
        PluginSpec.Behavior(PluginBehaviors.Representation.DefaultLociLabelProvider),
        PluginSpec.Behavior(PluginBehaviors.Representation.FocusLoci),
        PluginSpec.Behavior(PluginBehaviors.Camera.FocusLoci),
        PluginSpec.Behavior(PluginBehaviors.Camera.CameraControls),
        PluginSpec.Behavior(PluginBehaviors.CustomProps.StructureInfo),
        PluginSpec.Behavior(PluginBehaviors.CustomProps.SecondaryStructure),
        PluginSpec.Behavior(PluginBehaviors.CustomProps.ValenceModel),
      ];
      spec.config = [
        [PluginConfig.VolumeStreaming.Enabled, false],
        [PluginConfig.State.DefaultServer, ""],
        [PluginConfig.State.CurrentServer, ""],
      ];
      plugin = new PluginContext(spec);
      await plugin.init();
      if (cancelled) return;
      if (!(await plugin.initViewerAsync(canvas, mount))) throw new Error("Mol* WebGL 초기화에 실패했습니다.");
      if (cancelled) return;
      plugin.selectionMode = true;
      plugin.managers.interactivity.setProps({ granularity: "residue" });
      const updateBackground = () => {
        const canvasColor = getComputedStyle(document.documentElement).getPropertyValue("--canvas").trim();
        if (/^#[0-9a-fA-F]{6}$/.test(canvasColor))
          plugin?.canvas3d?.setProps({ renderer: { backgroundColor: Color(Number.parseInt(canvasColor.slice(1), 16)) } });
      };
      updateBackground();
      themeObserver = new MutationObserver(() => {
        if (instance.current?.canvas === canvas) {
          const current = instance.current;
          if (current.ownThemeMutation === currentTheme()) current.ownThemeMutation = null;
          else { current.ownThemeMutation = null; current.manualRevision += 1; }
        }
        updateBackground();
      });
      themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
      if (!source.text.trim()) throw new Error("구조 파일이 비어 있습니다.");
      const initialCatalog = atomRows.current;
      if (initialCatalog && (initialCatalog.structure_handle !== source.handle ||
          initialCatalog.viewer_source_sha256 !== await sourceHash(source.text)))
        throw new Error("원자 목록이 표시 구조 바이트와 일치하지 않습니다.");
      if (comparisonRef.current && (comparisonRef.current.catalog.structure_handle !== comparisonRef.current.source.handle ||
          comparisonRef.current.catalog.viewer_source_sha256 !== await sourceHash(comparisonRef.current.source.text)))
        throw new Error("이동 구조 원자 목록이 표시 바이트와 일치하지 않습니다.");

      const data = await plugin.builders.data.rawData({ data: source.text, label: source.handle });
      const trajectory = await plugin.builders.structure.parseTrajectory(data, source.format);
      const model = await plugin.builders.structure.createModel(trajectory, { modelIndex: source.modelIndex ?? 0 });
      const structure = await plugin.builders.structure.createStructure(model, { name: "model", params: {} });
      if (cancelled) return;
      if (!structure.obj?.data || structure.obj.data.elementCount === 0) throw new Error("표시할 원자가 없습니다.");
      const ligand = await plugin.builders.structure.tryCreateComponentStatic(structure, "ligand");
      const current: Instance = { plugin, structure, source, ligand, queue: Promise.resolve(),
        representation: requestedRepresentation.current, binding: null, selected: null, selectionError: null,
        readSelected: () => null, suppressSelectionCallback: false, lastAck: null,
        canvas, contextLost: false, manualRevision: 0, operationToken: 0,
        ownThemeMutation: null, imagePass: null,
        alignmentMatrix: alignmentMat4(comparisonRef.current?.alignment as RigidAlignment,
        !!comparisonRef.current?.aligned), lastAtomPick: null, atomPickRevision: 0,
        nativeClickRevision: 0, lastNativeClick: null, m10QueuePending: 0,
        validatedCatalogs: new Map() };
      instance.current = current;
      if (initialCatalog) {
        await validateNativeCatalog(structure.obj.data, initialCatalog);
        if (cancelled || instance.current !== current) return;
        current.validatedCatalogs.set(source.handle, { hash: initialCatalog.viewer_source_sha256,
          catalog: initialCatalog });
        setCatalogRevision(value => value + 1);
      }
      current.repr = await addRepresentation(plugin, structure,
        comparisonRef.current ? "ball-and-stick" : requestedRepresentation.current,
        comparisonRef.current ? "reference" : undefined);
      if (comparisonRef.current) current.representation = "ball-and-stick";
      if (!comparisonRef.current && ligand && requestedRepresentation.current !== "ball-and-stick")
        current.ligandRepr = await addRepresentation(plugin, ligand, "ball-and-stick");
      if (comparisonRef.current) {
        const moving = comparisonRef.current;
        const [{ StateTransforms }, { Mat4 }] = await Promise.all([
          import("molstar/lib/mol-plugin-state/transforms"), import("molstar/lib/mol-math/linear-algebra")]);
        const data2 = await plugin.builders.data.rawData({ data: moving.source.text, label: moving.source.handle });
        const trajectory2 = await plugin.builders.structure.parseTrajectory(data2, moving.source.format);
        const model2 = await plugin.builders.structure.createModel(trajectory2, { modelIndex: moving.source.modelIndex ?? 0 });
        const structure2 = await plugin.builders.structure.createStructure(model2, { name: "model", params: {} });
        if (cancelled || !structure2.obj?.data?.elementCount) throw new Error("비교 이동 구조를 불러오지 못했습니다.");
        current.movingStructure = structure2;
        await validateNativeCatalog(structure2.obj.data, moving.catalog);
        current.validatedCatalogs.set(moving.source.handle, { hash: moving.catalog.viewer_source_sha256,
          catalog: moving.catalog });
        const matrix = alignmentMat4(moving.alignment, moving.aligned);
        const params = { transform: { name: "matrix" as const,
          params: { data: matrix as unknown as ReturnType<typeof Mat4>, transpose: false } } };
        const builder = plugin.state.data.build().to(structure2).insert(StateTransforms.Model.TransformStructureConformation, params);
        await plugin.runTask(plugin.state.data.updateTree(builder));
        current.movingTransformRef = plugin.state.data.selectQ(q => q.byRef(structure2.ref).subtree()
          .withTransformer(StateTransforms.Model.TransformStructureConformation))[0]?.transform.ref;
        if (!current.movingTransformRef) throw new Error("비교 좌표 변환을 확인할 수 없습니다.");
        current.movingRepr = await addRepresentation(plugin, current.movingTransformRef, "ball-and-stick", "moving");
        current.alignmentMatrix = matrix;
        const { setSubtreeVisibility } = await import("molstar/lib/mol-plugin/behavior/static/state");
        setSubtreeVisibility(plugin.state.data, structure.ref, !moving.referenceVisible);
        setSubtreeVisibility(plugin.state.data, structure2.ref, !moving.movingVisible);
        await verifyOverlay(current, moving.alignment, moving.catalog, moving.aligned);
      }
      if (cancelled) return;
      plugin.managers.camera.reset();
      current.readSelected = () => {
        if (comparisonRef.current) throw new Error("비교 화면의 원자 선택은 레이어별로 읽어야 합니다.");
        const sourceIndices: number[] = [];
        for (const entry of plugin!.managers.structure.selection.entries.values()) {
          StructureElement.Loci.forEachLocation(entry.selection, loc => {
            if (!Unit.isAtomic(loc.unit) || loc.unit.model !== current.structure.obj?.data?.models[0])
              throw new Error("선택에 다른 원본 구조 또는 모델이 섞여 있습니다.");
            sourceIndices.push(StructureProperties.atom.sourceIndex(loc));
          });
        }
        const catalog = requireCatalog(current, atomRows.current);
        return residueFromNativeSites(catalog, sourceIndices);
      };
      let selectionNotificationQueued = false;
      selectionSubscription = plugin.managers.structure.selection.events.changed.subscribe(() => {
        if (cancelled) return;
        try { current.selected = current.readSelected(); current.selectionError = null; }
        catch (e) { current.selected = null; current.selectionError = e instanceof Error ? e.message : String(e); }
        if (current.suppressSelectionCallback || measureRef.current || comparisonRef.current || selectionNotificationQueued) return;
        current.manualRevision += 1;
        // selectOnly can emit an intermediate deselection before its final
        // selection. Report the settled native state once per click so manual
        // scene revision advances only once.
        selectionNotificationQueued = true;
        queueMicrotask(() => {
          selectionNotificationQueued = false;
          if (cancelled || instance.current !== current || current.suppressSelectionCallback ||
              measureRef.current || comparisonRef.current) return;
          try { current.selected = current.readSelected(); current.selectionError = null;
            setPickError(""); selectedCallback.current?.(current.selected); }
          catch (e) { current.selectionError = e instanceof Error ? e.message : String(e);
            setPickError(current.selectionError); }
        });
      });
      atomClickSubscription = plugin.behaviors.interaction.click.subscribe(({ current: hit }) => {
        const observed: NonNullable<ViewerQaSnapshot["lastNativeClick"]> = {
          kind: hit.loci.kind,
          size: StructureElement.Loci.is(hit.loci) ? StructureElement.Loci.size(hit.loci) : null,
          pluginBusy: plugin!.isBusy, measureMode: measureRef.current,
          accepted: false, reason: "inactive",
        };
        current.nativeClickRevision += 1; current.lastNativeClick = observed;
        if (!measureRef.current || cancelled || instance.current !== current || current.contextLost) return;
        if (hit.loci.kind === "empty-loci") { observed.reason = "empty_loci"; return; }
        const elementLocus = StructureElement.Loci.is(hit.loci);
        const loc = StructureElement.Loci.is(hit.loci) ? StructureElement.Loci.getFirstLocation(hit.loci) : undefined;
        const failure = atomPickFailure(current.representation, elementLocus,
          StructureElement.Loci.is(hit.loci) ? StructureElement.Loci.size(hit.loci) : 0,
          !!loc && Unit.isAtomic(loc.unit));
        if (failure) {
          observed.reason = failure;
          setPickError({
            representation: "원자 거리 측정에는 ball-and-stick 표시가 필요합니다. 표시 방식을 바꾼 뒤 다시 클릭하세요.",
            locus: "원자 하나를 직접 클릭하세요. 결합이나 표면 선택은 거리 측정에 사용할 수 없습니다.",
            multi: "여러 원자가 한 번에 선택되었습니다. ball-and-stick에서 원자 하나를 다시 클릭하세요.",
            non_atomic: "원자 하나를 정확히 선택할 수 없습니다.",
          }[failure]); return;
        }
        if (!loc) { observed.reason = "missing_location"; return; }
        const moving = !!current.movingStructure && loc.unit.model === current.movingStructure.obj?.data?.models[0];
        const layer = moving ? "moving" as const : "reference" as const;
        if (!moving && loc.unit.model !== current.structure.obj?.data?.models[0]) {
          observed.reason = "foreign_model"; return; }
        const catalog = validatedCatalog(current, moving ? comparisonRef.current?.catalog : atomRows.current);
        if (!catalog) {
          observed.reason = "catalog_unvalidated";
          setPickError("원자 목록 검증이 끝난 뒤 다시 선택하세요."); return; }
        const nativeSourceIndex = StructureProperties.atom.sourceIndex(loc);
        const matches = catalog.rows.filter(row => row.viewer_source_index === nativeSourceIndex);
        if (matches.length !== 1) { observed.reason = "ambiguous_source_index";
          setPickError("원자 인덱스가 원본과 모호합니다. 구조를 다시 불러오세요."); return; }
        const row = matches[0], ref = row.ref;
        const alt = StructureProperties.atom.label_alt_id(loc);
        if (ref.residue.model_number !== loc.unit.model.modelNum ||
            ref.residue.chain_auth !== StructureProperties.chain.auth_asym_id(loc) ||
            ref.residue.seq_auth !== StructureProperties.residue.auth_seq_id(loc) ||
            ref.residue.icode !== (StructureProperties.residue.pdbx_PDB_ins_code(loc) || "") ||
            ref.residue.resname !== StructureProperties.atom.auth_comp_id(loc) ||
            ref.atom_name !== StructureProperties.atom.auth_atom_id(loc) ||
            ref.altloc !== (alt === "." || alt === "?" ? "" : alt || "") ||
            ref.element !== StructureProperties.atom.type_symbol(loc).toUpperCase()) {
          observed.reason = "atom_identity_mismatch";
          setPickError("Mol* 원자 정보가 원본 AtomRef와 일치하지 않습니다. 구조를 다시 불러오세요."); return;
        }
        const world = loc.unit.conformation.position(loc.element,
          new Float64Array(3) as unknown as Parameters<typeof loc.unit.conformation.position>[1]);
        current.lastAtomPick = { layer, ref, nativeSourceIndex,
          worldCoordinate_A: Array.from(world) };
        setPickError("");
        observed.accepted = true; observed.reason = "accepted";
        current.atomPickRevision += 1;
        atomPickCallback.current?.(ref, layer);
      });
      const attached = (expected: ViewerBinding, token: number) => instance.current === current &&
        !current.contextLost && !current.canvas.getContext("webgl2")?.isContextLost() &&
        bindingMatches(current.binding, expected) && current.source.handle === expected.sourceHandle &&
        current.operationToken === token;
      const bound = (expected: ViewerBinding, token: number) => attached(expected, token) &&
        nativeMainRepresentationReady(current);
      const exactSelection = () => {
        requireCatalog(current, atomRows.current);
        const actual = current.readSelected();
        if (!actual) return null;
        return exactResidue(actual);
      };
      const observedSelection = () => { try { const selected = exactSelection(); current.selectionError = null;
        return selected; } catch (e) { current.selectionError = e instanceof Error ? e.message : String(e); return null; } };
      const readScene = (): NativeSceneState => {
        const camera = nativeCamera(plugin!);
        if (!camera) throw new Error("Mol* camera is unavailable");
        return { structure_handle: current.source.handle, selection: exactSelection(),
          representation: current.representation === "ball-and-stick" ? "ball_and_stick" : current.representation,
          camera, theme: currentTheme() };
      };
      const checkOperation = (expected: ViewerBinding, token: number, revision: number) => {
        if (!bound(expected, token) || current.manualRevision !== revision)
          throw new Error("수동 장면 변경으로 뷰어 작업이 취소되었습니다.");
      };
      const waitCameraSettled = async (expected: ViewerBinding, token: number, revision: number) => {
        const started = performance.now();
        let previous = "", stable = 0;
        while (performance.now() - started < 5000) {
          await settledFrame();
          checkOperation(expected, token, revision);
          const camera = plugin!.canvas3d?.camera;
          const snapshot = nativeCamera(plugin!);
          if (!camera || !snapshot) throw new Error("Mol* 카메라를 읽을 수 없습니다.");
          const serialized = JSON.stringify(snapshot);
          stable = !camera.transition.inTransition && serialized === previous ? stable + 1 : 0;
          if (stable >= 2) return;
          previous = serialized;
        }
        throw new Error("Mol* 카메라가 5초 안에 안정되지 않았습니다.");
      };
      const waitSceneRestored = async (expected: ViewerBinding, token: number, revision: number,
                                       scene: NativeSceneState): Promise<NativeSceneState> => {
        const started = performance.now();
        let stable = 0;
        while (performance.now() - started < 5000) {
          await settledFrame();
          checkOperation(expected, token, revision);
          const restored = readScene();
          stable = sceneMatches(restored, scene) && !plugin!.canvas3d!.camera.transition.inTransition ? stable + 1 : 0;
          if (stable >= 2) return restored;
        }
        throw new Error("Mol* 복원 상태가 저장된 보기와 일치하지 않습니다.");
      };
      const enqueue = <T,>(work: () => Promise<T>): Promise<T> => {
        const task = current.queue.then(work);
        current.queue = task.then(() => undefined, () => undefined);
        return task;
      };
      const guarded = <T,>(expected: ViewerBinding, work: (token: number) => Promise<T>, timeoutMs = 15000): Promise<T> => {
        const token = current.operationToken;
        // A timed-out native operation stays in the queue until it settles.
        // Every continuation must reject its invalidated token before mutating.
        const operation = enqueue(() => work(token));
        let timeout: ReturnType<typeof setTimeout> | undefined;
        const deadline = new Promise<never>((_, reject) => {
          timeout = setTimeout(() => { current.operationToken += 1; reject(new Error("뷰어 작업 시간이 초과되었습니다.")); }, timeoutMs);
        });
        return Promise.race([operation, deadline]).finally(() => clearTimeout(timeout)).then(value => {
          if (!bound(expected, token)) throw new Error("장면이 변경되어 작업 결과를 사용할 수 없습니다.");
          return value;
        });
      };
      const bridge: ViewerBridge = {
        bind: binding => { if (instance.current === current) {
          current.operationToken = nativeTokenAfterBinding(current.operationToken, current.binding, binding);
          current.binding = binding;
        } },
        snapshot: () => {
          const ready = instance.current === current && !current.contextLost &&
            !current.canvas.getContext("webgl2")?.isContextLost() && nativeMainRepresentationReady(current);
          const selection = ready && !comparisonRef.current && !measureRef.current ? observedSelection() : null;
          if (comparisonRef.current || measureRef.current) current.selectionError = null;
          return { ready, sourceHandle: ready ? current.source.handle : null,
            sessionId: current.binding?.sessionId ?? null, generation: current.binding?.generation ?? null,
            representation: ready ? current.representation : null,
            molstarRepresentation: ready ? current.repr?.obj?.data?.repr?.label ?? null : null,
            selection, selectionError: current.selectionError,
            camera: ready ? cameraSnapshot(plugin!) : null,
            nativeCamera: ready ? nativeCamera(plugin!) : null,
            theme: currentTheme(), backgroundColor: plugin!.canvas3d?.props.renderer.backgroundColor ?? null,
            lastAck: current.lastAck, measureMode: measureRef.current, lastAtomPick: current.lastAtomPick,
            nativeBusy: plugin!.isBusy,
            nativeUpdating: plugin!.behaviors.state.isUpdating.value,
            nativeAnimating: plugin!.behaviors.state.isAnimating.value,
            cameraTransitioning: !!plugin!.canvas3d?.camera.transition.inTransition,
            m10QueuePending: current.m10QueuePending,
            nativeClickRevision: current.nativeClickRevision, lastNativeClick: current.lastNativeClick,
            catalogReady: !!validatedCatalog(current, atomRows.current) &&
              (!comparisonRef.current || !!validatedCatalog(current, comparisonRef.current.catalog)),
            atomPickRevision: current.atomPickRevision, qaAtoms: qaAtomScreens(current, atomRows.current ?? null,
              comparisonRef.current?.catalog ?? null),
            layers: [
              { layer: "reference" as const, sourceHandle: current.source.handle,
                visible: !current.plugin.state.data.cells.get(current.structure.ref)?.state.isHidden,
                transform: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
                nativeAtomCount: current.structure.obj?.data?.elementCount ?? 0 },
              ...(current.movingStructure && comparisonRef.current ? [{ layer: "moving" as const,
                sourceHandle: comparisonRef.current.source.handle,
                visible: !current.plugin.state.data.cells.get(current.movingStructure.ref)?.state.isHidden,
                transform: Array.from((current.plugin.state.data.cells.get(current.movingTransformRef ?? "")?.transform.params as
                  { transform?: { params?: { data?: ArrayLike<number> } } } | undefined)?.transform?.params?.data ?? [], Number),
                nativeAtomCount: current.movingStructure.obj?.data?.elementCount ?? 0 }] : []),
            ] };
        },
        apply: async command => {
          // The command's intent belongs to admission, not to the time an older
          // queued native operation happens to release the queue.
          const binding = current.binding;
          const actionToken = current.operationToken;
          const actionManualRevision = current.manualRevision;
          let representationTouched = false;
          const execute = async () => {
            const stillBound = () => instance.current === current && !current.contextLost &&
              current.manualRevision === actionManualRevision &&
              !current.canvas.getContext("webgl2")?.isContextLost() &&
              nativeOperationBound(actionToken, current.operationToken, current.binding, binding) &&
              !!binding && command.schema === "viewer_plan@1" &&
              command.viewer_session_id === binding.sessionId && command.client_instance_id === binding.clientId &&
              command.scene_generation === binding.generation && command.structure_handle === binding.sourceHandle &&
              command.catalog_hash === binding.catalogHash && command.action_revision === binding.actionRevision &&
              current.source.handle === binding.sourceHandle;
            const fail = (reasonCode: string) => ({ status: "failed" as const, reasonCode });
            if (!stillBound() || !nativeMainRepresentationReady(current)) return fail("stale_or_not_ready");
            const before = cameraSnapshot(plugin!);
            if (!before) return fail("camera_unavailable");
            try {
              if (command.axis === "representation") {
                const next = command.value === "ball_and_stick" ? "ball-and-stick" : command.value;
                if (next !== "cartoon" && next !== "ball-and-stick" && next !== "surface") return fail("unsupported_command");
                if (next === current.representation) return { status: "no_change" as const, reasonCode: null };
                if (current.repr) {
                  representationTouched = true;
                  await plugin!.state.data.build().delete(current.repr.ref).commit();
                  current.repr = undefined;
                  if (!stillBound()) return fail("stale_or_not_ready");
                }
                representationTouched = true;
                current.repr = await addRepresentation(plugin!, current.structure, next);
                if (!stillBound()) return fail("stale_or_not_ready");
                if (current.ligandRepr) {
                  await plugin!.state.data.build().delete(current.ligandRepr.ref).commit();
                  current.ligandRepr = undefined;
                  if (!stillBound()) return fail("stale_or_not_ready");
                }
                current.ligandRepr = current.ligand && next !== "ball-and-stick"
                  ? await addRepresentation(plugin!, current.ligand, "ball-and-stick") : undefined;
                if (!stillBound()) return fail("stale_or_not_ready");
                if (!nativeMainRepresentationReady(current)) return fail("representation_unavailable");
                current.representation = next;
              } else if (command.axis === "selection" || command.value === "focus_selected") {
                if (!validatedCatalog(current, atomRows.current)) return fail("catalog_unavailable");
                if (command.value === "clear") {
                  current.suppressSelectionCallback = true;
                  try { plugin!.managers.interactivity.lociSelects.deselectAll(); }
                  finally { current.suppressSelectionCallback = false; }
                  if (current.readSelected()) return fail("selection_not_cleared");
                } else {
                  if (!command.target) return fail("target_missing");
                  const structure = current.structure.obj?.data;
                  if (!structure || structure.models[0]?.modelNum !== command.target.model_number) return fail("target_model_mismatch");
                  const loci = await authoritativeResidueLoci(current, command.target, atomRows.current);
                  if (!stillBound()) return fail("stale_or_not_ready");
                  if (command.axis === "selection") {
                    current.suppressSelectionCallback = true;
                    try { plugin!.managers.interactivity.lociSelects.deselectAll(); plugin!.managers.interactivity.lociSelects.select({ loci }); }
                    finally { current.suppressSelectionCallback = false; }
                    const selected = current.readSelected();
                    if (!selected || !sameResidueRef(selected, command.target)) return fail("selection_not_applied");
                  } else plugin!.managers.camera.focusLoci(loci, { durationMs: 0 });
                }
              } else if (command.axis === "camera") {
                if (command.value === "reset") plugin!.managers.camera.reset(undefined, 0);
                else if (command.value === "zoom_in" || command.value === "zoom_out") {
                  const factor = command.value === "zoom_in" ? 0.8 : 1.25;
                  const next = before.target.map((value, index) => value + (before.position[index] - value) * factor);
                  const camera = plugin!.canvas3d!.camera;
                  camera.setState({ position: next as typeof camera.state.position }, 0);
                } else return fail("unsupported_command");
              } else return fail("unsupported_command");
              await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
              if (!stillBound() || !nativeMainRepresentationReady(current)) return fail("stale_or_not_ready");
              const after = cameraSnapshot(plugin!);
              if (!after) return fail("camera_unavailable");
              if (command.axis === "camera") {
                if (!cameraChanged(before, after)) return { status: "no_change" as const, reasonCode: null };
                if (command.value === "zoom_in" && after.distance >= before.distance ||
                    command.value === "zoom_out" && after.distance <= before.distance) return fail("camera_direction_invalid");
              }
              return { status: "applied" as const, reasonCode: null };
            } catch { return fail("molstar_operation_failed"); }
          };
          const result = current.queue.then(execute);
          current.queue = result.then(() => undefined, () => undefined);
          const outcome = await result;
          if (instance.current === current && requestedSource.current === current.source && !current.contextLost &&
              requestedRepresentation.current === current.representation &&
              (representationTouched && outcome.status === "failed" || !nativeMainRepresentationReady(current))) {
            const message = "분자 표현이 중단되어 표시할 수 없습니다. 구조 다시 시도를 눌러 다시 불러오세요.";
            setError(message); setState("error"); loadCallback.current?.(current.source, "error", message);
          }
          current.lastAck = { commandId: command.command_id, status: outcome.status, reasonCode: outcome.reasonCode };
          return outcome;
        },
        invalidate: () => { current.operationToken += 1; current.binding = null; },
        cancelNative: () => { current.operationToken += 1; },
        captureScene: expected => guarded(expected, async token => {
          if (!bound(expected, token)) throw new Error("구조를 표시한 뒤 보기를 저장하세요.");
          const revision = current.manualRevision;
          await waitCameraSettled(expected, token, revision);
          const state = readScene();
          checkOperation(expected, token, revision);
          return state;
        }),
        restoreScene: (expected, scene) => guarded(expected, async token => {
          if (!bound(expected, token) || scene.structure_handle !== current.source.handle)
            throw new Error("저장된 장면의 구조가 현재 뷰어와 다릅니다.");
          const revision = current.manualRevision;
          const next = scene.representation === "ball_and_stick" ? "ball-and-stick" : scene.representation;
          if (current.representation !== next) {
            if (current.repr) await plugin!.state.data.build().delete(current.repr.ref).commit();
            if (!attached(expected, token) || current.manualRevision !== revision) throw new Error("복원 중 장면이 변경되었습니다.");
            current.repr = await addRepresentation(plugin!, current.structure, next);
            if (!attached(expected, token) || current.manualRevision !== revision) throw new Error("복원 중 장면이 변경되었습니다.");
            if (current.ligandRepr) await plugin!.state.data.build().delete(current.ligandRepr.ref).commit();
            if (!attached(expected, token) || current.manualRevision !== revision) throw new Error("복원 중 장면이 변경되었습니다.");
            current.ligandRepr = current.ligand && next !== "ball-and-stick"
              ? await addRepresentation(plugin!, current.ligand, "ball-and-stick") : undefined;
            if (!attached(expected, token) || current.manualRevision !== revision) throw new Error("복원 중 장면이 변경되었습니다.");
            current.representation = next;
          }
          if (!bound(expected, token) || current.manualRevision !== revision) throw new Error("복원 중 장면이 변경되었습니다.");
          const selectedLoci = scene.selection
            ? await authoritativeResidueLoci(current, scene.selection, atomRows.current) : null;
          if (!bound(expected, token) || current.manualRevision !== revision) throw new Error("복원 중 장면이 변경되었습니다.");
          current.suppressSelectionCallback = true;
          try {
            plugin!.managers.interactivity.lociSelects.deselectAll();
            if (selectedLoci) plugin!.managers.interactivity.lociSelects.select({ loci: selectedLoci });
          } finally { current.suppressSelectionCallback = false; }
          if (!bound(expected, token) || current.manualRevision !== revision) throw new Error("복원 중 장면이 변경되었습니다.");
          if (currentTheme() !== scene.theme) {
            current.ownThemeMutation = scene.theme;
            document.documentElement.dataset.theme = scene.theme;
          }
          updateBackground();
          await settledFrame();
          if (!bound(expected, token) || current.manualRevision !== revision || currentTheme() !== scene.theme)
            throw new Error("복원 중 장면이 변경되었습니다.");
          await waitCameraSettled(expected, token, revision);
          const camera = plugin!.canvas3d!.camera;
          camera.setState(scene.camera as Parameters<typeof camera.setState>[0], 0);
          return waitSceneRestored(expected, token, revision, scene);
        }),
        captureFigure: (expected, scene) => guarded(expected, async token => {
          if (!bound(expected, token)) throw new Error("구조를 표시한 뒤 이미지를 내보내세요.");
          const revision = current.manualRevision;
          await waitCameraSettled(expected, token, revision);
          const before = readScene();
          if (!sceneMatches(before, scene) || !bound(expected, token) || revision !== current.manualRevision)
            throw new Error("현재 장면이 저장된 보기와 다릅니다. 먼저 복원하세요.");
          const { Task } = await import("molstar/lib/mol-task");
          if (!bound(expected, token) || revision !== current.manualRevision) throw new Error("이미지 캡처 중 장면이 변경되었습니다.");
          const imageData = await plugin!.runTask(Task.create("Capture molecular viewport", async ctx => {
            if (!bound(expected, token) || revision !== current.manualRevision) throw new Error("이미지 캡처 중 장면이 변경되었습니다.");
            plugin!.animationLoop.stop({ noDraw: true });
            try {
              plugin!.canvas3d!.commit(true);
              const pass = current.imagePass ?? (current.imagePass = plugin!.canvas3d!.getImagePass({}));
              const canvas3d = plugin!.canvas3d!;
              const { colorBufferFloat, textureFloat } = canvas3d.webgl.extensions;
              // Mol*'s native screenshot path forces a complete multisample
              // render. The default temporal mode can return a blank target.
              pass.setProps({ multiSample: { ...canvas3d.props.multiSample, mode: "on",
                sampleLevel: colorBufferFloat && textureFloat ? 4 : 2, reuseOcclusion: false },
                postprocessing: { ...canvas3d.props.postprocessing },
                marking: { ...canvas3d.props.marking },
                illumination: { ...canvas3d.props.illumination, enabled: false } });
              await pass.updateBackground();
              if (!bound(expected, token) || revision !== current.manualRevision) throw new Error("이미지 캡처 중 장면이 변경되었습니다.");
              return await pass.getImageData(ctx, 1200, 800);
            } finally { if (instance.current === current && !current.contextLost) plugin!.animationLoop.start({ immediate: true }); }
          }));
          if (!bound(expected, token) || revision !== current.manualRevision) throw new Error("이미지 캡처 중 장면이 변경되었습니다.");
          let visible = 0;
          for (let i = 3; i < imageData.data.length; i += 4) if (imageData.data[i] > 0) { visible++; break; }
          if (!visible) throw new Error("Mol*가 빈 이미지를 반환했습니다. 다시 렌더링한 뒤 내보내세요.");
          const encoding = document.createElement("canvas");
          encoding.width = imageData.width; encoding.height = imageData.height;
          const context = encoding.getContext("2d");
          if (!context) throw new Error("PNG 인코딩 캔버스를 만들 수 없습니다.");
          context.putImageData(imageData, 0, 0);
          const blob = await new Promise<Blob>((resolve, reject) => encoding.toBlob(value =>
            value ? resolve(value) : reject(new Error("PNG 인코딩에 실패했습니다.")), "image/png"));
          if (blob.size > 8 * 1024 * 1024) throw new Error("PNG 크기가 8 MiB 제한을 초과했습니다.");
          const bytes = new Uint8Array(await blob.arrayBuffer());
          let binary = "";
          for (let i = 0; i < bytes.length; i += 32768)
            binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
          const after = readScene();
          if (!bound(expected, token) || revision !== current.manualRevision || !sceneMatches(after, scene))
            throw new Error("이미지 인코딩 중 장면이 변경되었습니다.");
          return { state: after, pngBase64: btoa(binary), width: imageData.width, height: imageData.height };
        }),
      };
      window.__protviewQaSnapshot = bridge.snapshot;
      bridgeCallback.current?.(bridge);
      setState("ready");
      loadCallback.current?.(source, "ready");
    };
    start().catch(e => {
      if (!cancelled) {
        const message = e instanceof Error ? e.message : String(e);
        setError(message); setState("error"); loadCallback.current?.(source, "error", message);
      }
    });
    return () => {
      cancelled = true;
      themeObserver?.disconnect();
      selectionSubscription?.unsubscribe();
      atomClickSubscription?.unsubscribe();
      canvas.removeEventListener("webglcontextlost", lost);
      canvas.removeEventListener("pointerdown", manual);
      canvas.removeEventListener("wheel", manual);
      if (window.__protviewQaSnapshot) delete window.__protviewQaSnapshot;
      bridgeCallback.current?.(null);
      if (instance.current?.plugin === plugin) instance.current = null;
      plugin?.dispose();
      mount.remove();
    };
  }, [source]);

  const queueM10 = (current: Instance, work: () => Promise<void>, stillRelevant: () => boolean = () => true,
                    onFailure?: (error: unknown) => void) => {
    const token = current.operationToken;
    let timedOut = false;
    current.m10QueuePending += 1;
    current.queue = current.queue.then(() => {
      if (instance.current !== current || current.contextLost || current.operationToken !== token || !stillRelevant()) return;
      return nativeDeadline(work(), 15000, () => {
        if (instance.current === current) { timedOut = true; current.operationToken += 1; current.contextLost = true; }
      });
    }).catch(e => {
      if (instance.current !== current || (!timedOut &&
          (current.operationToken !== token || !stillRelevant()))) return;
      if (!timedOut && onFailure) { onFailure(e); return; }
      current.contextLost = true;
      const message = e instanceof Error ? e.message : String(e);
      setError(`Mol* 비교 작업 실패: ${message}. 구조 다시 읽기를 사용하세요.`);
      setState("error"); loadCallback.current?.(current.source, "error", message);
    }).finally(() => { current.m10QueuePending -= 1; });
  };

  useEffect(() => {
    const current = instance.current;
    if (!current) return;
    setPickError("");
    current.plugin.managers.interactivity.setProps({ granularity: measureMode ? "element" : "residue" });
    if (measureMode) {
      current.suppressSelectionCallback = true;
      try { current.plugin.managers.interactivity.lociSelects.deselectAll(); }
      finally { current.suppressSelectionCallback = false; }
    }
  }, [measureMode, state]);

  useEffect(() => {
    const current = instance.current;
    if (!source || !atomCatalog) return;
    let active = true;
    void validateReadyCatalog(state, source.handle, current?.source.handle ?? null, atomCatalog,
      current ? validatedCatalog(current, atomCatalog) : null,
      async catalog => {
        const hash = await sourceHash(source.text);
        if (catalog.structure_handle !== source.handle || catalog.viewer_source_sha256 !== hash)
          throw new Error("표시 바이트와 원자 목록의 SHA-256이 다릅니다.");
        const structure = current?.structure.obj?.data;
        if (!structure) throw new Error("Mol* 구조가 준비되지 않았습니다.");
        await validateNativeCatalog(structure, catalog);
      },
      () => active && !!current && instance.current === current && !current.contextLost && current.source === source,
      catalog => {
        if (!current) return;
        current.validatedCatalogs.set(source.handle, { hash: catalog.viewer_source_sha256, catalog });
        setCatalogRevision(value => value + 1);
        if (!comparisonRef.current && !measureRef.current) {
          const observed = catalogSelectionReadback(current.readSelected);
          current.selected = observed.selection;
          current.selectionError = observed.error;
        }
        loadCallback.current?.(source, "ready");
      }).catch(e => { if (active && current && instance.current === current) {
      current.contextLost = true; const message = e instanceof Error ? e.message : String(e);
      setError(message); setState("error"); loadCallback.current?.(source, "error", message);
    } });
    return () => { active = false; };
  }, [source, atomCatalog, state]);

  useEffect(() => {
    const current = instance.current;
    if (!current || !comparison || !current.movingStructure || !current.movingTransformRef) return;
    const token = current.operationToken;
    const intentRevision = overlayIntent.current.revision;
    queueM10(current, async () => {
      if (instance.current !== current || current.contextLost || current.operationToken !== token ||
          overlayIntent.current.revision !== intentRevision ||
          comparisonRef.current?.source.handle !== comparison.source.handle) return;
      const [{ StateTransforms }, { Mat4 }, { setSubtreeVisibility }] = await Promise.all([
        import("molstar/lib/mol-plugin-state/transforms"), import("molstar/lib/mol-math/linear-algebra"),
        import("molstar/lib/mol-plugin/behavior/static/state")]);
      if (instance.current !== current || current.contextLost || current.operationToken !== token ||
          overlayIntent.current.revision !== intentRevision) return;
      const matrix = alignmentMat4(comparison.alignment, comparison.aligned);
      const transform = current.plugin.state.data.selectQ(q => q.byRef(current.movingStructure!.ref).subtree()
        .withTransformer(StateTransforms.Model.TransformStructureConformation))[0];
      if (!transform || transform.transform.ref !== current.movingTransformRef) throw new Error("비교 변환이 유실되었습니다.");
      const builder = current.plugin.state.data.build().to(transform).update({ transform: { name: "matrix",
        params: { data: matrix as unknown as ReturnType<typeof Mat4>, transpose: false } } });
      await current.plugin.runTask(current.plugin.state.data.updateTree(builder));
      if (instance.current !== current || current.contextLost || current.operationToken !== token ||
          overlayIntent.current.revision !== intentRevision) return;
      current.alignmentMatrix = matrix;
      setSubtreeVisibility(current.plugin.state.data, current.structure.ref, !comparison.referenceVisible);
      setSubtreeVisibility(current.plugin.state.data, current.movingStructure!.ref, !comparison.movingVisible);
      await settledFrame();
      if (instance.current !== current || current.contextLost || current.operationToken !== token ||
          overlayIntent.current.revision !== intentRevision) return;
      await verifyOverlay(current, comparison.alignment, comparison.catalog, comparison.aligned);
      if (instance.current !== current || current.contextLost || current.operationToken !== token ||
          overlayIntent.current.revision !== intentRevision ||
          !current.plugin.state.data.cells.get(current.movingTransformRef)?.obj) throw new Error("비교 변환 적용을 확인할 수 없습니다.");
    }, () => overlayIntent.current.revision === intentRevision);
  }, [comparison?.source.handle, comparison?.alignment, comparison?.aligned,
    comparison?.referenceVisible, comparison?.movingVisible]);

  useEffect(() => {
    const current = instance.current;
    if (!current || state !== "ready") return;
    const token = current.operationToken;
    const revision = current.manualRevision;
    queueM10(current, async () => {
      if (instance.current !== current || current.operationToken !== token || current.contextLost ||
          current.manualRevision !== revision) return;
      const plugin = current.plugin;
      current.suppressSelectionCallback = true;
      try {
        plugin.managers.interactivity.lociSelects.deselectAll();
        for (const ref of selectedAtoms ?? []) {
          const catalog = ref.structure_handle === current.source.handle ? atomRows.current : comparisonRef.current?.catalog;
          if (!catalog) throw new Error("선택 원자 목록이 없습니다.");
          const loci = await atomLoci(current, ref, catalog);
          if (instance.current !== current || current.operationToken !== token ||
              current.manualRevision !== revision || current.contextLost) return;
          plugin.managers.interactivity.lociSelects.select({ loci }, false);
        }
      } finally { current.suppressSelectionCallback = false; }
    });
  }, [state, selectedAtoms?.map(ref => `${ref.structure_handle}:${ref.site_index}`).join("|")]);

  useEffect(() => {
    const current = instance.current;
    if (!current || !focusPair || state !== "ready") return;
    const token = current.operationToken;
    const intentRevision = focusIntent.current.revision;
    const revision = current.manualRevision;
    const currentFocus = () => nativeIntentCurrent({ token, revision, intent: intentRevision },
      { token: current.operationToken, revision: current.manualRevision, intent: focusIntent.current.revision }) &&
      instance.current === current && !current.contextLost;
    queueM10(current, async () => {
      if (!currentFocus() || !comparisonRef.current) return;
      const a = await atomLoci(current, focusPair.reference, atomRows.current!);
      if (!currentFocus() || !comparisonRef.current) return;
      const b = await atomLoci(current, focusPair.moving, comparisonRef.current.catalog);
      if (!currentFocus()) return;
      current.suppressSelectionCallback = true;
      try {
        current.plugin.managers.interactivity.lociSelects.deselectAll();
        current.plugin.managers.interactivity.lociSelects.select({ loci: a }, false);
        current.plugin.managers.interactivity.lociSelects.select({ loci: b }, false);
      } finally { current.suppressSelectionCallback = false; }
      const { StructureElement } = await import("molstar/lib/mol-model/structure");
      if (!currentFocus()) return;
      const first = StructureElement.Loci.getFirstLocation(a), second = StructureElement.Loci.getFirstLocation(b);
      if (!first || !second) throw new Error("대응 원자 초점을 찾지 못했습니다.");
      const p = first.unit.conformation.position(first.element,
        new Float64Array(3) as unknown as Parameters<typeof first.unit.conformation.position>[1]);
      const q = second.unit.conformation.position(second.element,
        new Float64Array(3) as unknown as Parameters<typeof second.unit.conformation.position>[1]);
      const radius = Math.max(2, Math.hypot(...[0, 1, 2].map(i => p[i] - q[i])) / 2 + 2);
      if (!currentFocus()) return;
      current.plugin.managers.camera.focusLoci([a, b], { durationMs: 0, minRadius: radius });
    }, currentFocus);
  }, [state, focusPair?.token]);

  useEffect(() => {
    const current = instance.current;
    if (!current || state !== "ready") return;
    const token = current.operationToken;
    queueM10(current, async () => {
      if (instance.current !== current || current.operationToken !== token || current.contextLost) return;
      if (current.distanceAnnotationRef) {
        await current.plugin.state.data.build().delete(current.distanceAnnotationRef).commit();
        if (instance.current !== current || current.operationToken !== token || current.contextLost) return;
        current.distanceAnnotationRef = undefined;
      }
      if (!distanceResult) return;
      const catalog = distanceResult.structure_handle === current.source.handle ? atomRows.current : comparisonRef.current?.catalog;
      if (!catalog) throw new Error("측정 원자 목록이 표시된 구조와 다릅니다.");
      const a = await atomLoci(current, distanceResult.first, catalog);
      if (instance.current !== current || current.operationToken !== token || current.contextLost) return;
      const b = await atomLoci(current, distanceResult.second, catalog);
      if (instance.current !== current || current.operationToken !== token || current.contextLost) return;
      const annotation = await current.plugin.managers.structure.measurement.addDistance(a, b,
        { customText: `${distanceResult.distance_A.toFixed(3)} Å` });
      if (instance.current !== current || current.operationToken !== token || current.contextLost) return;
      if (!annotation) throw new Error("거리 표시를 만들지 못했습니다.");
      current.distanceAnnotationRef = annotation.representation.ref;
    });
  }, [state, distanceResult?.first.site_index, distanceResult?.second.site_index, distanceResult?.structure_handle]);

  useEffect(() => {
    const current = instance.current;
    if (!current || comparisonRef.current) return;
    const intentRevision = representationIntent.current.revision;
    let live = true;
    let mutated = false, completed = false;
    const active = () => live && instance.current === current && requestedSource.current === source &&
      current.source === source && !current.contextLost &&
      nativeRepresentationIntentCurrent({ revision: intentRevision, source, representation },
        { revision: representationIntent.current.revision, source: requestedSource.current ?? null,
          representation: requestedRepresentation.current, comparison: !!comparisonRef.current });
    current.queue = current.queue.then(async () => {
      if (!active()) return;
      if (current.representation === representation && nativeMainRepresentationReady(current)) return;
      if (current.repr) {
        mutated = true;
        await current.plugin.state.data.build().delete(current.repr.ref).commit();
        current.repr = undefined;
        if (!active()) return;
      }
      if (current.ligandRepr) {
        mutated = true;
        await current.plugin.state.data.build().delete(current.ligandRepr.ref).commit();
        current.ligandRepr = undefined;
        if (!active()) return;
      }
      if (!active()) return;
      mutated = true;
      current.repr = await addRepresentation(current.plugin, current.structure, representation);
      if (!active()) return;
      if (current.ligand && representation !== "ball-and-stick") {
        current.ligandRepr = await addRepresentation(current.plugin, current.ligand, "ball-and-stick");
        if (!active()) return;
      }
      if (!nativeMainRepresentationReady(current)) throw new Error("분자 표현을 표시하지 못했습니다.");
      current.representation = representation;
      completed = true;
    }).catch(e => {
      if (instance.current === current && requestedSource.current === source) {
        const message = e instanceof Error ? e.message : String(e);
        setError(message); setState("error");
        if (source) loadCallback.current?.(source, "error", message);
      }
    }).finally(() => {
      if (mutated && !completed && instance.current === current &&
          requestedSource.current === source && requestedRepresentation.current === representation &&
          representationIntent.current.revision === intentRevision &&
          !current.contextLost) {
        const message = "분자 표현이 중단되어 표시할 수 없습니다. 구조 다시 시도를 눌러 다시 불러오세요.";
        setError(message); setState("error");
        if (source) loadCallback.current?.(source, "error", message);
      }
    });
    return () => { live = false; };
  }, [representation]);

  useEffect(() => {
    const current = instance.current;
    if (!current || state !== "ready") return;
    let active = true;
    const focusCatalog = validatedCatalog(current, atomRows.current);
    if (!highlight || comparisonRef.current || measureRef.current || !focusCatalog) return;
    const token = current.operationToken, revision = current.manualRevision;
    const stillCurrent = () => active && instance.current === current && !current.contextLost &&
      !measureRef.current && !comparisonRef.current &&
      ordinaryFocusCurrent({ token, revision, sourceHandle: source?.handle ?? "", catalog: focusCatalog },
        { token: current.operationToken, revision: current.manualRevision,
          sourceHandle: current.source.handle, catalog: validatedCatalog(current, atomRows.current) });
    queueM10(current, async () => {
      const loci = await authoritativeResidueLoci(current, highlight, atomRows.current);
      if (!stillCurrent()) return;
      current.suppressSelectionCallback = true;
      try {
        current.plugin.managers.interactivity.lociSelects.deselectAll();
        current.plugin.managers.interactivity.lociSelects.select({ loci });
        current.plugin.managers.camera.focusLoci(loci);
      } finally { current.suppressSelectionCallback = false; }
      setPickError("");
      if (highlight && source) focusCallback.current?.(source, highlight, true);
    }, stillCurrent, e => {
      if (stillCurrent() && highlight && source) {
        setPickError(e instanceof Error ? e.message : String(e));
        focusCallback.current?.(source, highlight, false);
      }
    });
    return () => { active = false; };
  }, [highlight, state, source, atomCatalog, catalogRevision]);

  return (
    <div className="mw-molstar" aria-label="단백질 구조 뷰어">
      <div ref={host} className="mw-molstar-host" />
      {state === "empty" && <div className={`mw-molstar-message${emptyIsError ? " mw-molstar-error" : ""}`} role={emptyIsError ? "alert" : "status"}>{emptyMessage ?? "로컬 PDB 또는 mmCIF 파일을 업로드하세요."}</div>}
      {state === "loading" && <div className="mw-molstar-message" role="status">구조를 불러오는 중…</div>}
      {state === "error" && <div className="mw-molstar-message mw-molstar-error" role="alert">{error}</div>}
      {state === "ready" && pickError && <div className="mw-molstar-pick-error" role="alert">{pickError}</div>}
    </div>
  );
}

async function addRepresentation(plugin: Plugin, structure: StructureSelector | string, representation: ViewerRepresentation,
                                 layer?: "reference" | "moving") {
  const type = representation === "surface" ? "molecular-surface" : representation;
  return plugin.builders.structure.representation.addRepresentation(structure,
    layer ? { type, color: "uniform", colorParams: { value: layer === "reference" ? 0x4aa8f0 : 0xf0804a } } : { type });
}
