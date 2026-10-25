import kismet, pickle, os
PKGS = ["BitReactorGame","BitReactorCore","Bruno","GameplayAbilities","GameplayTasks","Engine","CoreUObject","GameplayTags","AIModule",
        "UMG","Niagara","AkAudio","CommonUI","ModularGameplay","MotionWarping","EnhancedInput","LevelSequence","MovieScene","SMSystem",
        "DeveloperSettings","SMExtendedRuntime","StateTreeModule","CommonGame","AnimGraphRuntime","NavigationSystem"]
def build():
    if os.path.exists("hashdb.pkl"): return pickle.load(open("hashdb.pkl","rb"))
    classes = set(l.strip() for l in open("uclasses.txt"))
    H = {}
    for c in classes:
        for p in PKGS: H[kismet.script_hash(f"/Script/{p}.{c[1:]}")] = f"{p}.{c[1:]}"
    for l in open("ufuncs.txt"):
        f = l.strip(); parts = f.split("_")
        for k in range(1, len(parts)):
            c = "_".join(parts[:k])
            if c in classes:
                fn = "_".join(parts[k:])
                for p in PKGS: H[kismet.script_hash(f"/Script/{p}.{c[1:]}:{fn}")] = f"{c[1:]}:{fn}"
    pickle.dump(H, open("hashdb.pkl","wb")); return H
if __name__ == "__main__":
    import time; t=time.time(); H=build(); print(len(H), "hashes", round(time.time()-t,1), "s")
    for k,v in H.items():
        if v.endswith("BRPresentableGameplayAbility:StopPresentation") or v.endswith("IPresentationElement:StopPresentation"): print(hex(k), v)
