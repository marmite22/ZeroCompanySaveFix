import zdis, sys, re
# print wide strings referenced (lea rip) in a function
rva = zdis.find(sys.argv[1]) if not sys.argv[1].startswith('0x') else int(sys.argv[1],16)
n = int(sys.argv[2],16) if len(sys.argv)>2 else 0x400
lines=[]; zdis.dis(rva, n, True, lines.append)
for l in lines:
    m = re.search(r"; \[(0x[0-9a-f]+)\]", l)
    if m and 'lea' in l:
        a=int(m.group(1),16); b=zdis.read(a,400)
        try:
            w=b.decode('utf-16le').split('\x00')[0]
        except: w=''
        a8=b.split(b'\x00')[0]
        if len(w)>=3 and w.isprintable(): print(l.split(':')[0], 'W', repr(w))
        elif len(a8)>=4 and all(32<=c<127 for c in a8): print(l.split(':')[0], 'A', repr(a8.decode()))
    if 'call' in l: print('   ', l.split(';')[-1].strip() if ';' in l else l)
