import unreal, json
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
hit = None
for a in sub.get_all_level_actors():
    lab = a.get_actor_label()
    if lab == "titan_avenger_scene_0":
        v = a.get_actor_location()
        hit = {"label": lab, "x": v.x, "y": v.y, "z": v.z}
        break
print(json.dumps(hit, indent=2))
