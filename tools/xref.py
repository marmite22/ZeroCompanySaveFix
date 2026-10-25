import zdis, sys
import numpy as np
p = zdis.pe()
text = [s for s in p.sections if s.Name.startswith(b'.text')][0]
raw = zdis._data[text.PointerToRawData:text.PointerToRawData+text.SizeOfRawData]
base = text.VirtualAddress
arr = np.frombuffer(raw, dtype=np.uint8)
n = len(raw) - 4
# rel32 values at each offset
rel = (arr[1:n+1].astype(np.int64) | (arr[2:n+2].astype(np.int64) << 8) | (arr[3:n+3].astype(np.int64) << 16) | (arr[4:n+4].astype(np.int64) << 24))
rel = np.where(rel >= 2**31, rel - 2**32, rel)
pos = np.arange(n, dtype=np.int64) + base
for a in sys.argv[1:]:
    t = zdis.find(a) if not a.startswith('0x') else int(a, 16)
    print(f"== xrefs to {zdis.name_at(t)} {t:#x}")
    # E8/E9: target = pos + 5 + rel  (opcode at pos)
    hits = np.nonzero(((arr[:n] == 0xE8) | (arr[:n] == 0xE9)) & (pos + 5 + rel == t))[0]
    for h in hits: print(f"  call/jmp @ {h+base:#x}  in {zdis.name_at(h+base)}")
    # rip-relative disp32 ending 4 bytes before next instr: approximate: disp at offset d, instr end = d+4 (+imm). check d+4+disp == t
    disp = rel  # value at offset i+1..i+4 -> treat i+1 as disp start
    hits2 = np.nonzero(pos + 1 + 4 + disp == t)[0]
    for h in hits2:
        if arr[h] in (0xE8, 0xE9): continue
        print(f"  riprel @ {h+1+base:#x}  in {zdis.name_at(h+1+base)}")
