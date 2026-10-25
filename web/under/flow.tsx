import { Fragment, memo, useEffect, useMemo, useRef } from "react";
import {
  Background,
  BackgroundVariant,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  getBezierPath,
  getViewportForBounds,
  useReactFlow,
  useStore,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { Check, Lock, RotateCw, X, type LucideIcon } from "lucide-react";

/* The «Под капотом» canvas, after the n8n canvas: custom nodes, particles along edges,
   and a camera that follows the active node while a trace replays. */

export type RunState = "idle" | "wait" | "running" | "success" | "error" | "retry" | "locked";
export type Side = "l" | "r" | "t" | "b";

export type FNode = {
  id: string;
  x: number;
  y: number;
  icon: LucideIcon;
  color: string;
  title: string;
  sub?: string;
  state?: RunState;
  badge?: string | number;
  size?: "lg" | "md" | "sm";
  dim?: boolean;
};

export type FEdge = {
  id: string;
  from: string;
  to: string;
  out?: Side;
  in?: Side;
  /** pulse number: a new value starts a new particle */
  pulse?: number;
  reverse?: boolean;
  error?: boolean;
  /** the edge was already passed in the current run */
  lit?: boolean;
  dashed?: boolean;
  /** running dashes: work in progress */
  flow?: boolean;
  /** error branch */
  danger?: boolean;
  label?: string;
};

type ND = FNode & { selected: boolean };
type ED = Omit<FEdge, "id" | "from" | "to" | "out" | "in">;

const SIZE = { lg: 76, md: 64, sm: 50 };

const FlowNode = memo(function FlowNode({ data }: NodeProps<Node<ND>>) {
  const Icon = data.icon;
  const state = data.state || "idle";
  const px = SIZE[data.size || "md"];
  return (
    <div
      className={`fx-node fx-${state} ${data.selected ? "fx-selected" : ""} ${data.dim ? "fx-dim" : ""}`}
      style={{ ["--c" as any]: data.color, width: Math.max(px + 60, 128) }}
    >
      <div className="fx-tile" style={{ width: px, height: px }}>
        {/* handles are absolutely positioned without wrappers, otherwise wrappers become grid cells and shift the icon */}
        {(["l", "r", "t", "b"] as Side[]).map((s) => (
          <Fragment key={s}>
            <Handle id={"t" + s} type="target" position={pos[s]} />
            <Handle id={"s" + s} type="source" position={pos[s]} />
          </Fragment>
        ))}
        <Icon size={Math.round(px * 0.38)} strokeWidth={1.7} />
        {["success", "error", "retry", "locked"].includes(state) && (
          <span className="fx-mark">
            {state === "success" ? (
              <Check size={12} strokeWidth={3} />
            ) : state === "error" ? (
              <X size={12} strokeWidth={3} />
            ) : state === "locked" ? (
              <Lock size={11} strokeWidth={2.6} />
            ) : (
              <RotateCw size={11} strokeWidth={3} />
            )}
          </span>
        )}
        {data.badge !== undefined && <span className="fx-badge">{data.badge}</span>}
      </div>
      <div className="fx-title">{data.title}</div>
      {data.sub && <div className="fx-sub">{data.sub}</div>}
    </div>
  );
});

const pos: Record<Side, Position> = {
  l: Position.Left,
  r: Position.Right,
  t: Position.Top,
  b: Position.Bottom,
};

function FlowEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
}: EdgeProps<Edge<ED>>) {
  const [path, lx, ly] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    curvature: 0.32,
  });
  const lit = data?.lit || !!data?.pulse;
  const err = data?.error;
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        className={`fx-edge ${lit ? "lit" : ""} ${err ? "err" : ""} ${data?.dashed ? "dashed" : ""} ${data?.flow ? "flow" : ""} ${data?.danger ? "danger" : ""}`}
      />
      {!!data?.pulse && (
        <g key={data.pulse}>
          <circle r={0} className={`fx-particle ${err ? "err" : ""}`}>
            {/* r=0 before the start, otherwise the dot flashes at the origin */}
            <set attributeName="r" to="4.5" begin="0s" fill="freeze" />
            <animateMotion
              dur="0.75s"
              repeatCount="1"
              fill="freeze"
              path={path}
              {...(data.reverse ? { keyPoints: "1;0", keyTimes: "0;1", calcMode: "linear" } : {})}
            />
          </circle>
          <circle r={0} className={`fx-particle trail ${err ? "err" : ""}`}>
            <set attributeName="r" to="2.5" begin="0.09s" fill="freeze" />
            <animateMotion
              dur="0.75s"
              begin="0.09s"
              repeatCount="1"
              fill="freeze"
              path={path}
              {...(data.reverse ? { keyPoints: "1;0", keyTimes: "0;1", calcMode: "linear" } : {})}
            />
          </circle>
        </g>
      )}
      {data?.label && (
        <EdgeLabelRenderer>
          <div
            className={`fx-edge-label nodrag nopan ${lit ? "lit" : ""} ${err ? "err" : ""}`}
            style={{ transform: `translate(-50%,-50%) translate(${lx}px,${ly}px)` }}
          >
            {data.label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const nodeTypes = { fx: FlowNode };
const edgeTypes = { fx: FlowEdge };

export type CanvasProps = {
  nodes: FNode[];
  edges: FEdge[];
  /** the node the camera follows; null means the whole diagram */
  focus?: string | null;
  selected?: string | null;
  onSelect?: (id: string | null) => void;
  /** scene key: when it changes, the camera fits the diagram again */
  scene?: string;
  zoom?: number;
};

function Canvas(p: CanvasProps) {
  const { setViewport, setCenter } = useReactFlow();
  const width = useStore((s) => s.width);
  const height = useStore((s) => s.height);
  const first = useRef(true);
  const mobile = width > 0 && width < 640;
  // On a phone the diagram turns top-to-bottom: it is larger on a narrow screen that way
  const vertical = mobile;
  const at = (n: FNode) => (vertical ? { x: n.y * 0.85, y: n.x * 0.62 } : { x: n.x, y: n.y });
  const side = (s: Side): Side => (vertical ? ({ l: "t", r: "b", t: "l", b: "r" } as const)[s] : s);

  const nodes: Node<ND>[] = useMemo(
    () =>
      p.nodes.map((n) => ({
        id: n.id,
        type: "fx",
        position: at(n),
        draggable: false,
        data: { ...n, selected: p.selected === n.id },
      })),
    [p.nodes, p.selected, vertical], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const edges: Edge<ED>[] = useMemo(
    () =>
      p.edges.map(({ id, from, to, out, in: inn, ...data }) => ({
        id,
        source: from,
        target: to,
        sourceHandle: "s" + side(out || "r"),
        targetHandle: "t" + side(inn || "l"),
        type: "fx",
        data,
      })),
    [p.edges, vertical], // eslint-disable-line react-hooks/exhaustive-deps
  );

  const fitAll = (duration: number) => {
    if (!p.nodes.length || !width || !height) return;
    const pts = p.nodes.map(at);
    const xs = pts.map((n) => n.x);
    const ys = pts.map((n) => n.y);
    const bounds = {
      x: Math.min(...xs) - 30,
      y: Math.min(...ys) - 70, // room at the top for the scenario panel
      width: Math.max(...xs) - Math.min(...xs) + 190,
      height: Math.max(...ys) - Math.min(...ys) + 200,
    };
    setViewport(getViewportForBounds(bounds, width, height, 0.2, p.zoom || 1.05, 0.04), {
      duration,
    });
  };

  useEffect(() => {
    if (!width || !height) return;
    const n = p.focus ? p.nodes.find((x) => x.id === p.focus) : null;
    const duration = first.current ? 0 : 650;
    first.current = false;
    if (n) {
      const c = at(n);
      setCenter(c.x + 64, c.y + 50, { zoom: mobile ? 0.8 : 1.02, duration: 600 });
    } else fitAll(duration);
  }, [width, height, vertical, p.focus, p.scene]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      minZoom={0.2}
      maxZoom={1.8}
      nodesConnectable={false}
      elementsSelectable
      panOnScroll={false}
      zoomOnScroll={!mobile}
      preventScrolling={!mobile}
      proOptions={{ hideAttribution: true }}
      onNodeClick={(_, n) => p.onSelect?.(n.id)}
      onPaneClick={() => p.onSelect?.(null)}
    >
      <Background variant={BackgroundVariant.Dots} gap={22} size={1.3} color="var(--k-dots)" />
      <Controls showInteractive={false} position="bottom-left" />
    </ReactFlow>
  );
}

export function FlowCanvas(props: CanvasProps) {
  return (
    <div className="fx-canvas">
      <ReactFlowProvider>
        <Canvas {...props} />
      </ReactFlowProvider>
    </div>
  );
}
