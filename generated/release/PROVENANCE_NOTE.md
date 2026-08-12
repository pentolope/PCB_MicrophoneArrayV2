# Why validation.json is newer than the archive beside it

`validation.json` and `clean_room.json` in this directory were produced by a
later clean-room run than the Gerbers, drills and fabrication archive. That is
deliberate, and this note records exactly what it does and does not mean.

## What happened

The orientation registry gained frozen raw evidence, strict review-status
enforcement, a half-open range check and a source-closure gate. None of those
change the board, so a fresh clean-room run reproduces the same manufacturing
output - but the old validation report described the older validator, which
made it stale as evidence.

Re-exporting the Gerbers produces files that differ from the committed ones
**only** in KiCad's own timestamp comments:

    G04 #@! TF.CreationDate,...
    G04 Created by KiCad (PCBNEW 10.0.5) date ...

Every other line of every layer, and every drill file, is byte-identical. That
was checked member by member, not assumed. Re-installing them would rewrite the
whole fabrication package to change two comment lines per file, so they were
left alone.

## What this means for the digests

`bom.csv` and `cpl.csv` are byte-identical between the two runs:

| File | SHA-256 |
|---|---|
| `bom.csv` | `a3970d865b3b76677afe0b11b6061156e3be633a50613167887ef8a54fe14563` |
| `cpl.csv` | `28091e4dbf5a05e30af72f833839194c67c0aa0f90c6f797d0434fce84e7e807` |

The **archive digest differs**, because a zip of files whose timestamp comments
differ is a different zip. `MANIFEST.md` records the digest of the archive that
is actually in this directory, and is the file to trust for that. The archive
digest that appears inside `validation.json` is the one the validating run
built and then discarded; it is not the archive here.

Everything `validation.json` asserts about the *design* - DRC, ERC, stackup,
vias, net topology, placement, BOM and CPL parity, layer identity, orientation -
was measured against the same design and the same BOM and CPL that ship here.

## To make the two agree

Run the release and install the whole package, archive included:

    "C:/Program Files/KiCad/10.0/bin/python.exe" verification/run.py release verification/boards/live.json

That is the right thing to do before ordering. It is not worth doing to change
a timestamp.
