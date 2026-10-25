import syms
rows = syms.enum("*")
with open("allsyms.tsv","w",encoding="utf-8") as f:
    for rva,size,tag,name in sorted(rows):
        f.write(f"{rva:x}\t{size}\t{tag}\t{name}\n")
print(len(rows))
