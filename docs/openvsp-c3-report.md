# C3 OpenVSP feasibility report

- installed: yes
- host: wsl-ubuntu
- interpreter: `/root/openvsp-c3/venv/bin/python` — Python 3.14.4 (main, Aug 20 2026, 10:41:58) [GCC 15.2.0] on Ubuntu 26.04 LTS (resolute). Windows host interpreter is `C:\Users\leona\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\python.exe` (3.11.9); it was not used for the bindings.
- wheel/build Python ABI: cp314 (`openvsp-3.51.3-cp314-cp314-linux_x86_64.whl`; `_vsp.so` links `libpython3.14.so.1.0`; official `environment.yml` pins `python=3.14`). Matches the WSL interpreter. Would not match Windows 3.11.9.
- OpenVSP version: OpenVSP 3.51.3
- VSPAERO version: VSPAERO v.7.2.2 --- Compiled on: Aug 17 2026 at 20:47:37 PST
- shipped example path: `/opt/OpenVSP/python/openvsp/openvsp/tests/test.py` (canonical file in the 3.51.3 Ubuntu 26.04 deb). First verification also ran the identical file after `pip install -r requirements.txt`: `/root/openvsp-c3/venv/lib/python3.14/site-packages/openvsp/tests/test.py`.
- shipped example ran: yes
- analysis inputs (runtime):
  - FeaMeshAnalysis: BaseLen, CADLabelDelim, CADLabelID, CADLabelName, CADLabelSplitNo, CADLabelSurfNo, CADLenUnit, CALCULIXFileFlag, CALCULIXFileName, CURVFileFlag, CURVFileName, ExportRawFlag, GMSHFileFlag, GMSHFileName, GrowthRatio, HalfMeshFlag, IGESFileFlag, IGESFileName, MASSFileFlag, MASSFileName, MaxGap, MinLen, NASTRANFileFlag, NASTRANFileName, NCircSeg, NKEYFileFlag, NKEYFileName, P3DFileFlag, P3DFileName, RelCurveTol, RigorLimit, SRFFileFlag, SRFFileName, STEPFileFlag, STEPFileName, STEPRepresentation, STEPTol, STLFileFlag, STLFileName, XYZIntCurveFlag
  - CfdMeshAnalysis: BaseLen, ExportRawFlag, FACETFileFlag, FACETFileName, GMSHFileFlag, GMSHFileName, GenerateHalfMesh, GrowthRatio, IntersectSubSurfs, MaxGap, MinLen, ModeID, NCircSeg, OBJFileFlag, OBJFileName, POLYFileFlag, POLYFileName, RelCurveTol, RigorLimit, STLFileFlag, STLFileName, SelectedDegenSetIndex, SelectedSetIndex, TRIFileFlag, TRIFileName, TaggedMultiSolid, UseMode, XYZIntCurveFlag
  - ParasiteDrag: AltLengthUnit, Altitude, DeltaTemp, Density, DynaVisc, ExportSubCompFlag, FileName, FreestreamPropChoice, GeomSet, KineVisc, LamCfEqnChoice, LengthUnit, Mach, ModeID, PresUnit, Pressure, Re_L, RecomputeGeom, RefFlag, SpecificHeatRatio, Sref, TempUnit, Temperature, TurbCfEqnChoice, UseModeFlag, VelocityUnit, Vinf, WingID
  - VSPAEROReadPreviousAnalysis: (none)
  - VSPAEROSinglePoint: (none)
  - PlanarSlice: AutoBoundFlag, EndVal, MeasureDuct, ModeID, Norm, NumSlices, Set, StartVal, UseModeFlag
  - CompGeom: DegenSet, HalfMeshFlag, ModeID, Set, SubSurfFlag, UseModeFlag, WriteCSVFlag, WriteTXTFlag
  - CpSlicer: XSlicePosVec, YSlicePosVec, ZSlicePosVec
  - VSPAEROSweep: 2DFEMFlag, AdjointGMRESConvergenceFactor, AlphaEnd, AlphaNpts, AlphaStart, AutoTimeNumRevs, AutoTimeStepFlag, BetaEnd, BetaNpts, BetaStart, CGDegenSet, CGGeomSet, CGModeID, CLMax2D, Clo2D, CoreSizeFactor, FarAway, FarDist, FarDistToggle, FixedWakeFlag, ForwardGMRESConvergenceFactor, FreezeMultiPoleAtIteration, FreezeWakeAtIteration, FreezeWakeRootVortices, FromSteadyState, GeomSet, GroundEffect, GroundEffectToggle, HoverRamp, HoverRampFlag, ImplicitWake, ImplicitWakeStartIteration, MACFlag, MachEnd, MachNpts, MachStart, Machref, ManualVrefFlag, MassSliceDir, ModeID, NCPU, NoiseCalcFlag, NoiseCalcType, NoiseUnits, NonLinearConvergenceFactor, NumMassSlice, NumTimeSteps, NumWakeNodes, PropBladesMode, QuadTreeBufferLevels, ReCref, ReCrefEnd, ReCrefNpts, RedirectFile, RefFlag, Rho, ScurveFlag, Sref, StallModel, StartAveragingTimeStep, StopBeforeRun, Symmetry, TecplotFlag, ThinGeomSet, TimeStepSize, UnsteadyType, UpdateMatrixPreconditioner, UseCGModeFlag, UseModeFlag, UseWakeNodeMatrixPreconditioner, Vinf, Vref, WakeNumIter, WakeRelax, WingID, Xcg, Ycg, Zcg, bref, cref
  - SurfacePatches: Set
  - SurfaceIntersection: CADLabelDelim, CADLabelID, CADLabelName, CADLabelSplitNo, CADLabelSurfNo, CADLenUnit, CURVFileFlag, CURVFileName, ExportRawFlag, IGESFileFlag, IGESFileName, IntersectSubSurfs, ModeID, P3DFileFlag, P3DFileName, RelCurveTol, SRFFileFlag, SRFFileName, STEPFileFlag, STEPFileName, STEPRepresentation, STEPTol, SelectedDegenSetIndex, SelectedSetIndex, UseMode
  - DegenGeom: ModeID, Set, UseModeFlag, WriteCSVFlag, WriteMFileFlag
  - VSPAEROComputeGeometry: CullFrac, CullFracFlag, FindBodyWakesFlag, GeomSet, ModeID, NRef, SingleGeomID, Symmetry, ThinGeomSet, UseModeFlag
  - DegenGeomMesh: DegenGeomMeshType, Set
  - EmintonLord: Area_vec, X_vec
  - VSPAERODegenGeom: (none)
  - GeometryAnalysis: CaseID
  - BladeElement: BEMFileName, ExportBEMFlag, PropID
  - MassProp: DegenSet, MassSliceDir, ModeID, NumMassSlices, Set, UseModeFlag
  - WaveDrag: Mach, ModeID, NumRotSects, NumSlices, SSFlow_vec, Set, SymmFlag, UseModeFlag
  - Projection: BoundaryGeomID, BoundaryHullFlag, BoundarySet, BoundaryType, Direction, DirectionGeomID, DirectionType, DiskSegmentBreakdown, TargetGeomID, TargetHullFlag, TargetModeID, TargetSet, TargetType
- exact error if not:
- elapsed_minutes: 8
- next: proceed to C4

## How this was verified

1. WSL Ubuntu 26.04 first (not 24.04). Official package: `https://openvsp.org/download.php?file=zips/current/linux/OpenVSP-3.51.3-Ubuntu-26.04_amd64.deb` (Depends: `libpython3.14 >= 3.14.1`).
2. `dpkg -i` failed once: postinst needed `desktop-file-install`. Installed `desktop-file-utils`, then `dpkg --configure -a`. Package status `ii openvsp 3.51.3`.
3. Followed the build's `python/README.md` Linux path without conda: copied `/opt/OpenVSP/python` to `/tmp/vsptemp` and `pip install -r requirements.txt` into a 3.14 venv. Wheel tag confirmed cp314.
4. Ran the shipped `tests/test.py` from this 3.51.3 tree. Exit 0. Created fuse/pod geometry and wrote `apitest1.vsp3` / `apitest2.vsp3`.
5. Enumerated with this build's API: `ListAnalysis()` then `GetAnalysisInputNames(name)` for each analysis. Not copied from a tutorial.
6. `packages/openvsp_worker` is a thin adapter: `available()`, `versions()`, `analysis_inputs()`, `run_shipped_example()`, `status_dict()`. It execs the WSL 3.14 venv; it does not generate aircraft.

C4 must use `/root/openvsp-c3/venv/bin/python` (or the worker) on WSL Ubuntu. Do not import `openvsp` into Windows Python 3.11.9.
