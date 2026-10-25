import zen, kismet, sys
H = {}
for c in ["BRPresentableGameplayAbility","BitReactorGameplayAbility","IPresentationElement","PresentationMgr","GameplayAbility","AbilitySystemBlueprintLibrary","KismetSystemLibrary","AbilityTask_WaitGameplayEvent","BitReactorGameStatics"]:
    for f in ["StopPresentation","BeginPresentation","IsPresentationFinished","IsLongRunning","RefreshStartTime","SignalAbilityPresentationEnded","EndAbility","K2_EndAbility","IsReadyForPresentation","SelfDestructOnFinishedOrStop","CancelPresentation","K2_CancelAbility","IsValid","WaitGameplayEvent","K2_CommitAbility","Delay","GetPresentationMgr","RequestStartPresentation","RegisterPresentationElement"]:
        for pk in ["BitReactorGame","GameplayAbilities","Bruno","Engine"]:
            H[kismet.script_hash(f"/Script/{pk}.{c}:{f}")] = f"{c}:{f}"
TOK = {0x04:"Return",0x06:"Jump",0x07:"JumpIfNot",0x4C:"PushFlow",0x4D:"PopFlow",0x4F:"PopFlowIfNot",0x4E:"ComputedJump",0x53:"EndOfScript",0x0F:"Let",0x14:"LetBool",0x5F:"LetObj",0x19:"Context",0x1B:"VirtualCall",0x1C:"FinalCall",0x46:"LocalFinal",0x45:"LocalVirtual",0x68:"CallMath",0x5E:"Tracepoint",0x5A:"WireTracepoint",0x44:"LetDelegate",0x5C:"AddMcDelegate",0x63:"CallMcDelegate",0x09:"Assert",0x6A:"Instrument"}
def name(t): return H.get(t[1], f"import {t[1]:#x}") if isinstance(t, tuple) else t
def dump(pkg, ex, lo=0, hi=10**9):
    r, st = kismet.disassemble(pkg, ex)
    calls = sorted(r.calls)
    ci = 0
    for i, (at, t) in enumerate(st):
        nxt = st[i+1][0] if i+1 < len(st) else 10**9
        cs = []
        while ci < len(calls) and calls[ci][0] < nxt:
            if calls[ci][0] >= at: cs.append(f"{calls[ci][1]}:{name(calls[ci][2])}")
            ci += 1
        if lo <= at <= hi:
            print(f"  {at:5d} {TOK.get(t, hex(t)):12s} {'; '.join(cs)}")
    return r, st
if __name__ == "__main__":
    p = zen.Pkg(open(sys.argv[1],'rb').read())
    for e in p.exports:
        if e['name'] in sys.argv[2:] or (sys.argv[2:] == ['*'] and e['size'] < 100000):
            print(f"== {e['name']}")
            try: dump(p, e)
            except Exception as x: print("  ERR", x)
