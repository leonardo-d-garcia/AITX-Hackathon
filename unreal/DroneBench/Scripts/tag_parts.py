"""Tag imported aircraft actors with part_id. Does not merge meshes."""

import json
import os
import traceback

try:
    import unreal
except Exception as exc:  # not running inside the Unreal editor
    print(
        json.dumps(
            {
                "tagged": 0,
                "samples": [],
                "untagged": [],
                "errors": ["import unreal: %s" % (exc,)],
            }
        )
    )
    raise SystemExit(0)

# Runbook 2.10. Used when DRONEBENCH_PART_MAP / part_map.json is absent.
RUNBOOK_PART_IDS = [
    "fuse_1",
    "fuse_2",
    "fuse_3",
    "fuse_4",
    "fuse_5",
    "canopy_1",
    "canopy_2",
    "hatch_1",
    "hatch_2",
    "motor_mount",
    "wing_1_L",
    "wing_2_L",
    "wing_3_L",
    "wing_4_L",
    "wing_5_L",
    "aileron_L",
    "wing_bay_plate_L",
    "wing_1_R",
    "wing_2_R",
    "wing_3_R",
    "wing_4_R",
    "wing_5_R",
    "aileron_R",
    "wing_bay_plate_R",
    "vtail_1_L",
    "vtail_2_L",
    "taileron_L",
    "vtail_1_R",
    "vtail_2_R",
    "taileron_R",
]

PART_ID_TAG_PREFIX = "part_id="
DEFAULT_MAP_REL = os.path.join(
    "..", "..", "..", "..", "fixtures", "c", "titan_avenger_cad", "part_map.json"
)


def _emit(payload):
    print(json.dumps(payload, default=str))


def _err(context, exc):
    return "%s: %s\n%s" % (context, exc, traceback.format_exc())


def _script_dir():
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except (NameError, TypeError, AttributeError):
        pass
    try:
        # dir(unreal.Paths)  # project_dir, convert_relative_path_to_full
        return os.path.normpath(os.path.join(unreal.Paths.project_dir(), "Scripts"))
    except Exception:
        return os.getcwd()


def _part_ids_from_payload(payload):
    if isinstance(payload, dict):
        if isinstance(payload.get("occurrences"), list):
            ids = []
            for row in payload["occurrences"]:
                if isinstance(row, dict) and row.get("part_id"):
                    ids.append(str(row["part_id"]))
            if ids:
                return ids
        return [str(k) for k in payload.keys()]
    if isinstance(payload, list):
        ids = []
        for item in payload:
            if isinstance(item, str) and item:
                ids.append(item)
            elif isinstance(item, dict) and item.get("part_id"):
                ids.append(str(item["part_id"]))
        return ids
    return []


def _load_part_ids(errors):
    candidates = []
    env_path = os.environ.get("DRONEBENCH_PART_MAP") or ""
    if env_path:
        candidates.append(env_path)
        if not os.path.isfile(env_path):
            errors.append("DRONEBENCH_PART_MAP is not a file: %s" % env_path)
    candidates.append(os.path.normpath(os.path.join(_script_dir(), DEFAULT_MAP_REL)))

    for path in candidates:
        try:
            if not path or not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            ids = _part_ids_from_payload(payload)
            if ids:
                return ids
            errors.append("no part ids in %s" % path)
        except Exception as exc:
            errors.append(_err("load part map %s" % path, exc))
    return list(RUNBOOK_PART_IDS)


def _tag_string(part_id):
    return PART_ID_TAG_PREFIX + part_id


def _as_str_list(values):
    out = []
    try:
        for item in list(values or []):
            text = str(item)
            if text and text not in out:
                out.append(text)
    except Exception:
        pass
    return out


def _apply_name_tags(obj, property_name, part_id, errors, context):
    wanted = _tag_string(part_id)
    try:
        # dir(obj)  # get_editor_property, set_editor_property, tags / component_tags, modify
        current = _as_str_list(obj.get_editor_property(property_name))
    except Exception as exc:
        errors.append(_err("%s get %s" % (context, property_name), exc))
        current = []

    kept = [tag for tag in current if not str(tag).startswith(PART_ID_TAG_PREFIX)]
    if wanted not in kept:
        kept.append(wanted)
    if kept == current:
        return

    try:
        try:
            obj.modify()
        except Exception:
            pass
        # set_editor_property (not raw assignment) so the editor dirties the level
        obj.set_editor_property(property_name, kept)
    except Exception as exc:
        errors.append(_err("%s set %s" % (context, property_name), exc))


def _actor_label(actor):
    try:
        # dir(actor)  # get_actor_label, get_name
        label = actor.get_actor_label()
        if label:
            return str(label)
    except Exception:
        pass
    try:
        return str(actor.get_name())
    except Exception:
        return "<unknown>"


def _mesh_names(actor, errors):
    names = []
    comps = []
    try:
        # dir(actor)  # get_components_by_class
        # dir(unreal.MeshComponent)  # get_name, component_tags
        comps = list(actor.get_components_by_class(unreal.MeshComponent) or [])
    except Exception:
        try:
            comps = list(actor.get_components_by_class(unreal.StaticMeshComponent) or [])
        except Exception as exc:
            errors.append(_err("get_components_by_class %s" % _actor_label(actor), exc))
            return names, []

    for comp in comps:
        try:
            names.append(str(comp.get_name()))
        except Exception as exc:
            errors.append(_err("component get_name", exc))
        try:
            # dir(unreal.StaticMeshComponent)  # static_mesh editor property; no get_static_mesh()
            mesh = comp.get_editor_property("static_mesh")
            if mesh is not None:
                names.append(str(mesh.get_name()))
        except Exception:
            try:
                mesh = getattr(comp, "static_mesh", None)
                if mesh is not None:
                    names.append(str(mesh.get_name()))
            except Exception:
                pass
    return names, comps


def _match_part_id(haystacks, part_ids_longest_first):
    # Longest first: "taileron_L" contains "aileron_L".
    best = None
    for raw in haystacks:
        if not raw:
            continue
        text = str(raw).lower()
        for part_id in part_ids_longest_first:
            needle = part_id.lower()
            if needle and needle in text:
                if best is None or len(part_id) > len(best):
                    best = part_id
                break
    return best


def tag_parts():
    report = {
        "tagged": 0,
        "samples": [],
        "untagged": [],
        "errors": [],
    }
    errors = report["errors"]

    try:
        part_ids = _load_part_ids(errors)
        part_ids_longest_first = sorted(part_ids, key=len, reverse=True)
    except Exception as exc:
        errors.append(_err("load part ids", exc))
        part_ids_longest_first = sorted(RUNBOOK_PART_IDS, key=len, reverse=True)

    try:
        # dir(unreal.EditorActorSubsystem)  # get_all_level_actors
        actor_subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        actors = list(actor_subsys.get_all_level_actors() or [])
    except Exception as exc:
        errors.append(_err("get_all_level_actors", exc))
        return report

    samples = []
    untagged = []
    tagged = 0

    for actor in actors:
        try:
            label = _actor_label(actor)
            haystacks = [label]
            try:
                haystacks.append(str(actor.get_name()))
            except Exception:
                pass
            mesh_names, mesh_comps = _mesh_names(actor, errors)
            haystacks.extend(mesh_names)

            part_id = _match_part_id(haystacks, part_ids_longest_first)
            if not part_id:
                untagged.append(label)
                continue

            _apply_name_tags(actor, "tags", part_id, errors, "actor %s" % label)
            for comp in mesh_comps:
                try:
                    _apply_name_tags(
                        comp,
                        "component_tags",
                        part_id,
                        errors,
                        "component %s" % label,
                    )
                except Exception as exc:
                    errors.append(_err("component_tags %s" % label, exc))

            tagged += 1
            samples.append([label, part_id])
        except Exception as exc:
            errors.append(_err("actor", exc))
            try:
                untagged.append(_actor_label(actor))
            except Exception:
                untagged.append("<unknown>")

    report["tagged"] = tagged
    report["samples"] = samples
    report["untagged"] = untagged
    return report


# ExecuteFile and stdin-exec both need one JSON object, never "done".
try:
    _emit(tag_parts())
except Exception as exc:
    _emit(
        {
            "tagged": 0,
            "samples": [],
            "untagged": [],
            "errors": [_err("tag_parts", exc)],
        }
    )
