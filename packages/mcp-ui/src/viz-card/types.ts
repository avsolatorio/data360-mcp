import type { ReactNode } from "react";
import type { VegaChartCardBaseProps } from "@data360/mcp-viz-core";

export type {
  Annotation,
  MarkType,
  VegaChartCardBaseProps,
  VLEncoding,
  VLSpec,
} from "@data360/mcp-viz-core";

/**
 * React chart card props: base fields plus an optional slot for the right-rail top.
 */
export interface VegaChartCardProps extends VegaChartCardBaseProps {
  /**
   * Optional control at the top of the right rail (e.g. “expand” in chat).
   * The PNG export stays at the bottom; when set, the rail uses vertical space-between.
   */
  railTopSlot?: ReactNode;
}
