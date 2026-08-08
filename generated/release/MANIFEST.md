# Fabrication release manifest

- generated: 2026-08-08T04:30:43.117853+00:00
- kicad: 10.0.5
- constraint profile: jlcpcb-4layer-assembled
- source closure sha256: `5dc6c32bc8c90ca28a9b9d106a345316209367427222f2a1803dbf6f21dab39f`

## command

    kicad-cli.exe sch erc --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T043024Z-4e3a170d\work\clean_run\reports\erc.json --format json --severity-all --severity-exclusions --exit-code-violations C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T043024Z-4e3a170d\work\clean_run\fixture\project\microphone_array_v2.kicad_sch
    kicad-cli.exe pcb drc --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T043024Z-4e3a170d\work\clean_run\reports\drc.json --format json --severity-all --severity-exclusions --all-track-errors --schematic-parity --refill-zones --save-board --exit-code-violations C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T043024Z-4e3a170d\work\clean_run\fixture\project\microphone_array_v2.kicad_pcb
    kicad-cli.exe pcb export gerbers --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T043024Z-4e3a170d\work\clean_run\generated\gerbers --layers F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts --no-x2 --no-netlist --use-drill-file-origin --subtract-soldermask C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T043024Z-4e3a170d\work\clean_run\fixture\project\microphone_array_v2.kicad_pcb
    kicad-cli.exe pcb export drill --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T043024Z-4e3a170d\work\clean_run\generated\gerbers --format excellon --excellon-separate-th --drill-origin plot C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T043024Z-4e3a170d\work\clean_run\fixture\project\microphone_array_v2.kicad_pcb
    kicad-cli.exe pcb export pos --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T043024Z-4e3a170d\build\cpl.csv --format csv --units mm --side both --exclude-dnp C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T043024Z-4e3a170d\work\clean_run\fixture\project\microphone_array_v2.kicad_pcb
    kicad-cli.exe sch export bom --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T043024Z-4e3a170d\build\bom.csv --fields ${QUANTITY},Reference,Value,Footprint,LCSC --labels "Quantity,Designator,Comment,Footprint,LCSC Part #" --group-by Value,Footprint,LCSC --exclude-dnp --ref-range-delimiter  C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T043024Z-4e3a170d\work\clean_run\fixture\project\microphone_array_v2.kicad_sch
    rename "13 file(s)"
    relabel cpl.csv
    relabel bom.csv

## artifacts

- `microphone_array_v2-revA-fabrication.zip` sha256 `15a1666e5d07a24b0576465a4c0842783cc92df9d2b90d6cd0ddcf86ca5294ab`
- `bom.csv` sha256 `a3970d865b3b76677afe0b11b6061156e3be633a50613167887ef8a54fe14563`
- `cpl.csv` sha256 `49d74d87ea8ab56fc187e916bd535c119c798f6744d08fc222e989418c47bfb3`

## excluded from the archive

- `(none)`: every exported layer was approved
