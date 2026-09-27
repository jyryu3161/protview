"use client";

import { useEffect, useRef, useState } from "react";
import type { ResidueRef } from "@/lib/contracts";
import type { ViewerCommand } from "@/lib/viewer-agent";
import { cameraChanged } from "@/lib/viewer-scene";
import { sameResidue, sceneMatches, type NativeCameraState, type NativeSceneState } from "@/lib/saved-scene";

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
  camera: { position: number[]; target: number[]; radius: number; distance: number } | null;
  nativeCamera: NativeCameraState | null; theme: "dark" | "light";
  backgroundColor: number | null;
  lastAck: { commandId: string; status: "applied" | "no_change" | "failed"; reasonCode: string | null } | null;
}
export interface ViewerBridge {
  bind(binding: ViewerBinding | null): void;
  snapshot(): ViewerQaSnapshot;
  apply(command: ViewerCommand): Promise<{ status: "applied" | "no_change" | "failed"; reasonCode: string | null }>;
  captureScene(expected: ViewerBinding): Promise<NativeSceneState>;
  restoreScene(expected: ViewerBinding, scene: NativeSceneState): Promise<NativeSceneState>;
  captureFigure(expected: ViewerBinding, scene: NativeSceneState): Promise<{ state: NativeSceneState; pngBase64: string; width: number; height: number }>;
  invalidate(): void;
}
type Instance = { plugin: Plugin; structure: StructureSelector; source: ViewerSource; ligand?: StructureSelector;
  repr?: RepresentationSelector; ligandRepr?: RepresentationSelector; queue: Promise<void>;
  representation: ViewerRepresentation; binding: ViewerBinding | null; selected: ResidueRef | null;
  readSelected: () => ResidueRef | null; suppressSelectionCallback: boolean; lastAck: ViewerQaSnapshot["lastAck"];
  canvas: HTMLCanvasElement; contextLost: boolean; manualRevision: number; operationToken: number;
  ownThemeMutation: "dark" | "light" | null; imagePass: ImagePass | null };

declare global { interface Window { __protviewQaSnapshot?: () => ViewerQaSnapshot } }

function normalizedRef(ref: ResidueRef): string {
  return [ref.model_number ?? null, ref.chain_auth, ref.chain_label ?? null, ref.seq_auth,
    ref.seq_label ?? null, ref.icode ?? "", ref.resname].join("|");
}

function matchesAuthoritative(actual: ResidueRef, target: ResidueRef): boolean {
  return actual.model_number === target.model_number && actual.chain_auth === target.chain_auth &&
    actual.seq_auth === target.seq_auth && (actual.icode ?? "") === (target.icode ?? "") &&
    actual.resname === target.resname &&
    (target.chain_label == null || actual.chain_label === target.chain_label) &&
    (target.seq_label == null || actual.seq_label === target.seq_label);
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

function residueSchema(ref: ResidueRef) {
  const items: Record<string, string | number> = {
    auth_asym_id: ref.chain_auth,
    auth_seq_id: ref.seq_auth,
    auth_comp_id: ref.resname,
    pdbx_PDB_ins_code: ref.icode || "",
  };
  if (ref.chain_label) items.label_asym_id = ref.chain_label;
  if (ref.seq_label != null) items.label_seq_id = ref.seq_label;
  return items;
}

/** Canvas-only Mol*: no download action, remote extension, or automatic property service. */
export function MolstarViewer({ source, representation, highlight, residues, onSelect, onLoadState, onFocusResult, onBridge, onManualInteraction, emptyMessage, emptyIsError }: MolstarViewerProps) {
  const host = useRef<HTMLDivElement>(null);
  const instance = useRef<Instance | null>(null);
  const requestedRepresentation = useRef(representation);
  const selectedCallback = useRef(onSelect);
  const loadCallback = useRef(onLoadState);
  const focusCallback = useRef(onFocusResult);
  const bridgeCallback = useRef(onBridge);
  const manualCallback = useRef(onManualInteraction);
  const authoritativeRows = useRef(residues);
  const [state, setState] = useState<"empty" | "loading" | "ready" | "error">("empty");
  const [error, setError] = useState("");
  requestedRepresentation.current = representation;
  selectedCallback.current = onSelect;
  loadCallback.current = onLoadState;
  focusCallback.current = onFocusResult;
  bridgeCallback.current = onBridge;
  manualCallback.current = onManualInteraction;
  authoritativeRows.current = residues;

  useEffect(() => {
    const parent = host.current;
    if (!parent || !source) { setState("empty"); return; }
    let cancelled = false;
    let plugin: Plugin | undefined;
    let selectionSubscription: { unsubscribe(): void } | undefined;
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
      const [{ PluginContext }, { DefaultPluginSpec, PluginSpec }, { PluginConfig }, { PluginBehaviors }, { StructureElement, StructureProperties }, { Color }, { Binding }, { ButtonsType }] = await Promise.all([
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

      const data = await plugin.builders.data.rawData({ data: source.text, label: source.handle });
      const trajectory = await plugin.builders.structure.parseTrajectory(data, source.format);
      const model = await plugin.builders.structure.createModel(trajectory, { modelIndex: source.modelIndex ?? 0 });
      const structure = await plugin.builders.structure.createStructure(model, { name: "model", params: {} });
      if (cancelled) return;
      if (!structure.obj?.data || structure.obj.data.elementCount === 0) throw new Error("표시할 원자가 없습니다.");
      const ligand = await plugin.builders.structure.tryCreateComponentStatic(structure, "ligand");
      const current: Instance = { plugin, structure, source, ligand, queue: Promise.resolve(),
        representation: requestedRepresentation.current, binding: null, selected: null,
        readSelected: () => null, suppressSelectionCallback: false, lastAck: null,
        canvas, contextLost: false, manualRevision: 0, operationToken: 0,
        ownThemeMutation: null, imagePass: null };
      instance.current = current;
      current.repr = await addRepresentation(plugin, structure, requestedRepresentation.current);
      if (ligand && requestedRepresentation.current !== "ball-and-stick")
        current.ligandRepr = await addRepresentation(plugin, ligand, "ball-and-stick");
      if (cancelled) return;
      plugin.managers.camera.reset();
      current.readSelected = () => {
        const keys = new Map<string, ResidueRef>();
        for (const entry of plugin!.managers.structure.selection.entries.values()) {
          StructureElement.Loci.forEachLocation(entry.selection, loc => {
            const ref: ResidueRef = {
              model_number: loc.unit.model.modelNum,
              chain_auth: StructureProperties.chain.auth_asym_id(loc),
              chain_label: StructureProperties.chain.label_asym_id(loc) || null,
              seq_auth: StructureProperties.residue.auth_seq_id(loc),
              seq_label: StructureProperties.residue.label_seq_id(loc) || null,
              icode: StructureProperties.residue.pdbx_PDB_ins_code(loc) || "",
              resname: StructureProperties.atom.label_comp_id(loc),
            };
            keys.set(normalizedRef(ref), ref);
          });
        }
        return keys.size === 1 ? [...keys.values()][0] : null;
      };
      let selectionNotificationQueued = false;
      selectionSubscription = plugin.managers.structure.selection.events.changed.subscribe(() => {
        if (cancelled) return;
        current.selected = current.readSelected();
        if (current.suppressSelectionCallback || selectionNotificationQueued) return;
        current.manualRevision += 1;
        // selectOnly can emit an intermediate deselection before its final
        // selection. Report the settled native state once per click so manual
        // scene revision advances only once.
        selectionNotificationQueued = true;
        queueMicrotask(() => {
          selectionNotificationQueued = false;
          if (cancelled || instance.current !== current || current.suppressSelectionCallback) return;
          current.selected = current.readSelected();
          selectedCallback.current?.(current.selected);
        });
      });
      const bindingMatches = (actual: ViewerBinding | null, expected: ViewerBinding) => !!actual &&
        actual.sessionId === expected.sessionId && actual.clientId === expected.clientId &&
        actual.generation === expected.generation && actual.sourceHandle === expected.sourceHandle &&
        actual.catalogHash === expected.catalogHash && actual.actionRevision === expected.actionRevision;
      const attached = (expected: ViewerBinding, token: number) => instance.current === current &&
        !current.contextLost && !current.canvas.getContext("webgl2")?.isContextLost() &&
        bindingMatches(current.binding, expected) && current.source.handle === expected.sourceHandle &&
        current.operationToken === token;
      const bound = (expected: ViewerBinding, token: number) => attached(expected, token) &&
        !!current.repr?.obj?.data?.repr;
      const exactSelection = () => {
        const actual = current.readSelected();
        if (!actual) return null;
        const matches = authoritativeRows.current?.filter(ref => matchesAuthoritative(actual, ref));
        if (matches?.length !== 1) throw new Error("선택한 잔기의 원본 식별자를 확인할 수 없습니다.");
        return matches[0];
      };
      const observedSelection = () => { try { return exactSelection(); } catch { return null; } };
      const readScene = (): NativeSceneState => {
        const camera = nativeCamera(plugin!);
        if (!camera) throw new Error("Mol* camera is unavailable");
        return { structure_handle: current.source.handle, selection: exactSelection(),
          representation: current.representation === "ball-and-stick" ? "ball_and_stick" : current.representation,
          camera, theme: currentTheme() };
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
        bind: binding => { if (instance.current === current) { current.operationToken += 1; current.binding = binding; } },
        snapshot: () => {
          const ready = instance.current === current && !current.contextLost &&
            !current.canvas.getContext("webgl2")?.isContextLost() && !!current.repr?.obj?.data?.repr;
          return { ready, sourceHandle: ready ? current.source.handle : null,
            sessionId: current.binding?.sessionId ?? null, generation: current.binding?.generation ?? null,
            representation: ready ? current.representation : null,
            molstarRepresentation: ready ? current.repr?.obj?.data?.repr?.label ?? null : null,
            selection: ready ? observedSelection() : null,
            camera: ready ? cameraSnapshot(plugin!) : null,
            nativeCamera: ready ? nativeCamera(plugin!) : null,
            theme: currentTheme(), backgroundColor: plugin!.canvas3d?.props.renderer.backgroundColor ?? null,
            lastAck: current.lastAck };
        },
        apply: async command => {
          const execute = async () => {
            const binding = current.binding;
            const stillBound = () => instance.current === current && !current.contextLost &&
              !current.canvas.getContext("webgl2")?.isContextLost() &&
              !!binding && current.binding === binding && command.schema === "viewer_plan@1" &&
              command.viewer_session_id === binding.sessionId && command.client_instance_id === binding.clientId &&
              command.scene_generation === binding.generation && command.structure_handle === binding.sourceHandle &&
              command.catalog_hash === binding.catalogHash && command.action_revision === binding.actionRevision &&
              current.source.handle === binding.sourceHandle;
            const fail = (reasonCode: string) => ({ status: "failed" as const, reasonCode });
            if (!stillBound() || !current.repr?.obj?.data?.repr) return fail("stale_or_not_ready");
            const before = cameraSnapshot(plugin!);
            if (!before) return fail("camera_unavailable");
            try {
              if (command.axis === "representation") {
                const next = command.value === "ball_and_stick" ? "ball-and-stick" : command.value;
                if (next !== "cartoon" && next !== "ball-and-stick" && next !== "surface") return fail("unsupported_command");
                if (next === current.representation) return { status: "no_change" as const, reasonCode: null };
                if (current.repr) await plugin!.state.data.build().delete(current.repr.ref).commit();
                current.repr = await addRepresentation(plugin!, current.structure, next);
                if (current.ligandRepr) await plugin!.state.data.build().delete(current.ligandRepr.ref).commit();
                current.ligandRepr = current.ligand && next !== "ball-and-stick"
                  ? await addRepresentation(plugin!, current.ligand, "ball-and-stick") : undefined;
                if (!current.repr?.obj?.data?.repr || !stillBound()) return fail("representation_unavailable");
                current.representation = next;
              } else if (command.axis === "selection" || command.value === "focus_selected") {
                if (command.value === "clear") {
                  current.suppressSelectionCallback = true;
                  try { plugin!.managers.interactivity.lociSelects.deselectAll(); }
                  finally { current.suppressSelectionCallback = false; }
                  if (current.readSelected()) return fail("selection_not_cleared");
                } else {
                  if (!command.target) return fail("target_missing");
                  const structure = current.structure.obj?.data;
                  if (!structure || structure.models[0]?.modelNum !== command.target.model_number) return fail("target_model_mismatch");
                  const loci = StructureElement.Loci.fromSchema(structure, residueSchema(command.target) as Parameters<typeof StructureElement.Loci.fromSchema>[1]);
                  if (StructureElement.Loci.isEmpty(loci)) return fail("target_not_found");
                  const identities = new Set<string>();
                  StructureElement.Loci.forEachLocation(loci, loc => identities.add(normalizedRef({
                    model_number: loc.unit.model.modelNum,
                    chain_auth: StructureProperties.chain.auth_asym_id(loc),
                    chain_label: StructureProperties.chain.label_asym_id(loc) || null,
                    seq_auth: StructureProperties.residue.auth_seq_id(loc),
                    seq_label: StructureProperties.residue.label_seq_id(loc) || null,
                    icode: StructureProperties.residue.pdbx_PDB_ins_code(loc) || "",
                    resname: StructureProperties.atom.label_comp_id(loc),
                  })));
                  if (identities.size !== 1) return fail("target_ambiguous");
                  const first = StructureElement.Loci.getFirstLocation(loci);
                  if (!first || !matchesAuthoritative({
                    model_number: first.unit.model.modelNum,
                    chain_auth: StructureProperties.chain.auth_asym_id(first),
                    chain_label: StructureProperties.chain.label_asym_id(first) || null,
                    seq_auth: StructureProperties.residue.auth_seq_id(first),
                    seq_label: StructureProperties.residue.label_seq_id(first) || null,
                    icode: StructureProperties.residue.pdbx_PDB_ins_code(first) || "",
                    resname: StructureProperties.atom.label_comp_id(first),
                  }, command.target)) return fail("target_ambiguous");
                  if (command.axis === "selection") {
                    current.suppressSelectionCallback = true;
                    try { plugin!.managers.interactivity.lociSelects.deselectAll(); plugin!.managers.interactivity.lociSelects.select({ loci }); }
                    finally { current.suppressSelectionCallback = false; }
                    const selected = current.readSelected();
                    if (!selected || !matchesAuthoritative(selected, command.target)) return fail("selection_not_applied");
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
              if (!stillBound() || !current.repr?.obj?.data?.repr) return fail("stale_or_not_ready");
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
          current.lastAck = { commandId: command.command_id, status: outcome.status, reasonCode: outcome.reasonCode };
          return outcome;
        },
        invalidate: () => { current.operationToken += 1; current.binding = null; },
        captureScene: expected => guarded(expected, async token => {
          if (!bound(expected, token)) throw new Error("구조를 표시한 뒤 보기를 저장하세요.");
          const revision = current.manualRevision;
          await settledFrame();
          if (!bound(expected, token) || revision !== current.manualRevision)
            throw new Error("캡처 중 장면이 바뀌었습니다. 다시 시도하세요.");
          const state = readScene();
          if (!bound(expected, token) || revision !== current.manualRevision)
            throw new Error("캡처 중 장면이 바뀌었습니다. 다시 시도하세요.");
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
          current.suppressSelectionCallback = true;
          try {
            plugin!.managers.interactivity.lociSelects.deselectAll();
            if (scene.selection) {
              const structure = current.structure.obj?.data;
              if (!structure || structure.models[0]?.modelNum !== scene.selection.model_number)
                throw new Error("저장된 잔기 모델이 표시된 구조와 다릅니다.");
              const loci = StructureElement.Loci.fromSchema(structure,
                residueSchema(scene.selection) as Parameters<typeof StructureElement.Loci.fromSchema>[1]);
              if (StructureElement.Loci.isEmpty(loci)) throw new Error("저장된 잔기를 찾지 못했습니다.");
              plugin!.managers.interactivity.lociSelects.select({ loci });
            }
          } finally { current.suppressSelectionCallback = false; }
          if (!sameResidue(exactSelection(), scene.selection)) throw new Error("저장된 잔기 선택을 복원하지 못했습니다.");
          if (!bound(expected, token) || current.manualRevision !== revision) throw new Error("복원 중 장면이 변경되었습니다.");
          if (currentTheme() !== scene.theme) {
            current.ownThemeMutation = scene.theme;
            document.documentElement.dataset.theme = scene.theme;
          }
          updateBackground();
          await settledFrame();
          if (!bound(expected, token) || current.manualRevision !== revision || currentTheme() !== scene.theme)
            throw new Error("복원 중 장면이 변경되었습니다.");
          const camera = plugin!.canvas3d!.camera;
          camera.setState(scene.camera as Parameters<typeof camera.setState>[0], 0);
          await settledFrame();
          if (!bound(expected, token) || current.manualRevision !== revision)
            throw new Error("복원 중 수동 장면 변경이 발생했습니다.");
          const restored = readScene();
          if (!sceneMatches(restored, scene)) throw new Error("Mol* 복원 상태가 저장된 보기와 일치하지 않습니다.");
          return restored;
        }),
        captureFigure: (expected, scene) => guarded(expected, async token => {
          if (!bound(expected, token)) throw new Error("구조를 표시한 뒤 이미지를 내보내세요.");
          const revision = current.manualRevision;
          await settledFrame();
          const before = readScene();
          if (!sceneMatches(before, scene) || !bound(expected, token) || revision !== current.manualRevision)
            throw new Error("현재 장면이 저장된 보기와 다릅니다. 먼저 복원하세요.");
          const { Task } = await import("molstar/lib/mol-task");
          if (!bound(expected, token) || revision !== current.manualRevision) throw new Error("이미지 캡처 중 장면이 변경되었습니다.");
          const imageData = await plugin!.runTask(Task.create("Capture molecular viewport", async ctx => {
            if (!bound(expected, token) || revision !== current.manualRevision) throw new Error("이미지 캡처 중 장면이 변경되었습니다.");
            plugin!.animationLoop.stop({ noDraw: true });
            try {
              const pass = current.imagePass ?? (current.imagePass = plugin!.canvas3d!.getImagePass({}));
              await pass.updateBackground();
              if (!bound(expected, token) || revision !== current.manualRevision) throw new Error("이미지 캡처 중 장면이 변경되었습니다.");
              return await pass.getImageData(ctx, 1200, 800);
            } finally { if (instance.current === current && !current.contextLost) plugin!.animationLoop.start({ immediate: true }); }
          }));
          if (!bound(expected, token) || revision !== current.manualRevision) throw new Error("이미지 캡처 중 장면이 변경되었습니다.");
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

  useEffect(() => {
    const current = instance.current;
    if (!current) return;
    current.queue = current.queue.then(async () => {
      if (instance.current !== current) return;
      if (current.representation === representation && current.repr?.obj?.data?.repr) return;
      if (current.repr) await current.plugin.state.data.build().delete(current.repr.ref).commit();
      current.repr = undefined;
      if (current.ligandRepr) await current.plugin.state.data.build().delete(current.ligandRepr.ref).commit();
      current.ligandRepr = undefined;
      if (instance.current !== current) return;
      current.repr = await addRepresentation(current.plugin, current.structure, representation);
      if (current.ligand && representation !== "ball-and-stick")
        current.ligandRepr = await addRepresentation(current.plugin, current.ligand, "ball-and-stick");
      if (current.repr?.obj?.data?.repr) current.representation = representation;
    }).catch(e => {
      if (instance.current === current) {
        const message = e instanceof Error ? e.message : String(e);
        setError(message); setState("error");
        if (source) loadCallback.current?.(source, "error", message);
      }
    });
  }, [representation]);

  useEffect(() => {
    const current = instance.current;
    if (!current || state !== "ready") return;
    let active = true;
    import("molstar/lib/mol-model/structure").then(({ StructureElement }) => {
      if (!active || instance.current !== current) return;
      current.suppressSelectionCallback = true;
      try {
        current.plugin.managers.interactivity.lociSelects.deselectAll();
        if (!highlight) return;
        const structure = current.structure.obj?.data;
        if (!structure || (highlight.model_number != null && structure.models[0]?.modelNum !== highlight.model_number)) {
          if (source) focusCallback.current?.(source, highlight, false);
          return;
        }
        const loci = StructureElement.Loci.fromSchema(structure, residueSchema(highlight) as Parameters<typeof StructureElement.Loci.fromSchema>[1]);
        if (StructureElement.Loci.isEmpty(loci)) {
          if (source) focusCallback.current?.(source, highlight, false);
          return;
        }
        current.plugin.managers.interactivity.lociSelects.select({ loci });
        current.plugin.managers.camera.focusLoci(loci);
        if (source) focusCallback.current?.(source, highlight, true);
      } finally { current.suppressSelectionCallback = false; }
    }).catch(() => {
      if (active && instance.current === current && highlight && source) focusCallback.current?.(source, highlight, false);
    });
    return () => { active = false; };
  }, [highlight, state, source]);

  return (
    <div className="mw-molstar" aria-label="단백질 구조 뷰어">
      <div ref={host} className="mw-molstar-host" />
      {state === "empty" && <div className={`mw-molstar-message${emptyIsError ? " mw-molstar-error" : ""}`} role={emptyIsError ? "alert" : "status"}>{emptyMessage ?? "로컬 PDB 또는 mmCIF 파일을 업로드하세요."}</div>}
      {state === "loading" && <div className="mw-molstar-message" role="status">구조를 불러오는 중…</div>}
      {state === "error" && <div className="mw-molstar-message mw-molstar-error" role="alert">{error}</div>}
    </div>
  );
}

async function addRepresentation(plugin: Plugin, structure: StructureSelector, representation: ViewerRepresentation) {
  const type = representation === "surface" ? "molecular-surface" : representation;
  return plugin.builders.structure.representation.addRepresentation(structure, { type });
}
