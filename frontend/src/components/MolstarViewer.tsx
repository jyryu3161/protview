"use client";

import { useEffect, useRef, useState } from "react";
import type { ResidueRef } from "@/lib/contracts";

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
  onSelect?: (residue: ResidueRef) => void;
  onLoadState?: (source: ViewerSource, state: "loading" | "ready" | "error", message?: string) => void;
  onFocusResult?: (source: ViewerSource, residue: ResidueRef, found: boolean) => void;
  emptyMessage?: string;
  emptyIsError?: boolean;
}

type Plugin = import("molstar/lib/mol-plugin/context").PluginContext;
type StructureSelector = Awaited<ReturnType<Plugin["builders"]["structure"]["createStructure"]>>;
type RepresentationSelector = Awaited<ReturnType<Plugin["builders"]["structure"]["representation"]["addRepresentation"]>>;
type Instance = { plugin: Plugin; structure: StructureSelector; ligand?: StructureSelector; repr?: RepresentationSelector; ligandRepr?: RepresentationSelector; queue: Promise<void> };

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
export function MolstarViewer({ source, representation, highlight, onSelect, onLoadState, onFocusResult, emptyMessage, emptyIsError }: MolstarViewerProps) {
  const host = useRef<HTMLDivElement>(null);
  const instance = useRef<Instance | null>(null);
  const requestedRepresentation = useRef(representation);
  const selectedCallback = useRef(onSelect);
  const loadCallback = useRef(onLoadState);
  const focusCallback = useRef(onFocusResult);
  const [state, setState] = useState<"empty" | "loading" | "ready" | "error">("empty");
  const [error, setError] = useState("");
  requestedRepresentation.current = representation;
  selectedCallback.current = onSelect;
  loadCallback.current = onLoadState;
  focusCallback.current = onFocusResult;

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
    parent.appendChild(mount);
    setState("loading");
    setError("");
    loadCallback.current?.(source, "loading");

    const start = async () => {
      const [{ PluginContext }, { DefaultPluginSpec, PluginSpec }, { PluginConfig }, { PluginBehaviors }, { Structure, StructureProperties }, { Color }] = await Promise.all([
        import("molstar/lib/mol-plugin/context"),
        import("molstar/lib/mol-plugin/spec"),
        import("molstar/lib/mol-plugin/config"),
        import("molstar/lib/mol-plugin/behavior"),
        import("molstar/lib/mol-model/structure"),
        import("molstar/lib/mol-util/color"),
      ]);
      if (cancelled) return;
      const spec = DefaultPluginSpec();
      spec.actions = [];
      spec.behaviors = [
        PluginSpec.Behavior(PluginBehaviors.Representation.HighlightLoci),
        PluginSpec.Behavior(PluginBehaviors.Representation.SelectLoci),
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
      const updateBackground = () => {
        const canvasColor = getComputedStyle(document.documentElement).getPropertyValue("--canvas").trim();
        if (/^#[0-9a-fA-F]{6}$/.test(canvasColor))
          plugin?.canvas3d?.setProps({ renderer: { backgroundColor: Color(Number.parseInt(canvasColor.slice(1), 16)) } });
      };
      updateBackground();
      themeObserver = new MutationObserver(updateBackground);
      themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
      if (!source.text.trim()) throw new Error("구조 파일이 비어 있습니다.");

      const data = await plugin.builders.data.rawData({ data: source.text, label: source.handle });
      const trajectory = await plugin.builders.structure.parseTrajectory(data, source.format);
      const model = await plugin.builders.structure.createModel(trajectory, { modelIndex: source.modelIndex ?? 0 });
      const structure = await plugin.builders.structure.createStructure(model, { name: "model", params: {} });
      if (cancelled) return;
      if (!structure.obj?.data || structure.obj.data.elementCount === 0) throw new Error("표시할 원자가 없습니다.");
      const ligand = await plugin.builders.structure.tryCreateComponentStatic(structure, "ligand");
      const current: Instance = { plugin, structure, ligand, queue: Promise.resolve() };
      instance.current = current;
      current.repr = await addRepresentation(plugin, structure, requestedRepresentation.current);
      if (ligand && requestedRepresentation.current !== "ball-and-stick")
        current.ligandRepr = await addRepresentation(plugin, ligand, "ball-and-stick");
      if (cancelled) return;
      plugin.managers.camera.reset();
      selectionSubscription = plugin.managers.structure.selection.events.changed.subscribe(() => {
        if (!selectedCallback.current || cancelled) return;
        for (const entry of plugin!.managers.structure.selection.entries.values()) {
          if (!entry.structure) continue;
          let result: ResidueRef | undefined;
          Structure.eachAtomicHierarchyElement(entry.structure, {
            residue: loc => {
              if (result) return;
              result = {
                model_number: loc.unit.model.modelNum,
                chain_auth: StructureProperties.chain.auth_asym_id(loc),
                chain_label: StructureProperties.chain.label_asym_id(loc) || null,
                seq_auth: StructureProperties.residue.auth_seq_id(loc),
                seq_label: StructureProperties.residue.label_seq_id(loc) || null,
                icode: StructureProperties.residue.pdbx_PDB_ins_code(loc) || "",
                resname: StructureProperties.atom.label_comp_id(loc),
              };
            },
          });
          if (result) { selectedCallback.current(result); break; }
        }
      });
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
      if (current.repr) await current.plugin.state.data.build().delete(current.repr.ref).commit();
      current.repr = undefined;
      if (current.ligandRepr) await current.plugin.state.data.build().delete(current.ligandRepr.ref).commit();
      current.ligandRepr = undefined;
      if (instance.current !== current) return;
      current.repr = await addRepresentation(current.plugin, current.structure, representation);
      if (current.ligand && representation !== "ball-and-stick")
        current.ligandRepr = await addRepresentation(current.plugin, current.ligand, "ball-and-stick");
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
