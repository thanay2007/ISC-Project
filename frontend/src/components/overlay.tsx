"use client";
import { Layer, Rect, Stage } from "react-konva";
import type { Box } from "@/lib/types";

export default function Overlay({ width, height, boxes }: {
  width: number; height: number; boxes: { box: Box; color: string; active?: boolean }[];
}) {
  return <div className="annotation-layer" aria-hidden="true"><Stage width={width} height={height} listening={false}>
    <Layer>{boxes.map(({ box: [x0, y0, x1, y1], color, active }, index) =>
      <Rect key={index} x={x0 * width} y={y0 * height} width={(x1 - x0) * width} height={(y1 - y0) * height}
        stroke={color} strokeWidth={active ? 3 : 1.3} cornerRadius={2} dash={active ? undefined : [4, 3]}
        fill={color + (active ? "40" : "13")} />)}</Layer>
  </Stage></div>;
}
