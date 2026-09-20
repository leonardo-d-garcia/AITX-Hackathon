/// <reference types="vite/client" />

declare module "@telemetry" {
  import type { SimulationRun } from "./telemetry";
  const run: SimulationRun;
  export default run;
}
