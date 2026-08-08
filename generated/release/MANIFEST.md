# Fabrication release manifest

- generated: 2026-08-08T03:23:02.225062+00:00
- kicad: 10.0.5
- constraint profile: jlcpcb-4layer-assembled
- source closure sha256: `8105cf3c1de45829c704c76f0cff6833479cb85a681300d3777db205602f5437`

## command

    kicad-cli.exe sch erc --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T032242Z-3052fdfe\work\clean_run\reports\erc.json --format json --severity-all --severity-exclusions --exit-code-violations C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T032242Z-3052fdfe\work\clean_run\fixture\project\microphone_array_v2.kicad_sch
    kicad-cli.exe pcb drc --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T032242Z-3052fdfe\work\clean_run\reports\drc.json --format json --severity-all --severity-exclusions --all-track-errors --schematic-parity --refill-zones --save-board --exit-code-violations C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T032242Z-3052fdfe\work\clean_run\fixture\project\microphone_array_v2.kicad_pcb
    kicad-cli.exe pcb export gerbers --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T032242Z-3052fdfe\work\clean_run\generated\gerbers --layers F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts --no-x2 --no-netlist --disable-aperture-macros --use-drill-file-origin --subtract-soldermask C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T032242Z-3052fdfe\work\clean_run\fixture\project\microphone_array_v2.kicad_pcb
    kicad-cli.exe pcb export drill --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T032242Z-3052fdfe\work\clean_run\generated\gerbers --format excellon --excellon-separate-th --drill-origin plot C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T032242Z-3052fdfe\work\clean_run\fixture\project\microphone_array_v2.kicad_pcb
    kicad-cli.exe pcb export pos --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T032242Z-3052fdfe\build\cpl.csv --format csv --units mm --side both --exclude-dnp C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T032242Z-3052fdfe\work\clean_run\fixture\project\microphone_array_v2.kicad_pcb
    kicad-cli.exe sch export bom --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T032242Z-3052fdfe\build\bom.csv --fields ${QUANTITY},Reference,Value,Footprint,LCSC --labels "Quantity,Designator,Comment,Footprint,LCSC Part #" --group-by Value,Footprint,LCSC --exclude-dnp --ref-range-delimiter  C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260808T032242Z-3052fdfe\work\clean_run\fixture\project\microphone_array_v2.kicad_sch
    rename "13 file(s)"
    relabel cpl.csv
    relabel bom.csv

## artifacts

- `microphone_array_v2-revA-fabrication.zip` sha256 `fe6b9c90ddea0b3f21fe0214b70754645938b585f6b35bf7fa67eac281dc9f14`
- `bom.csv` sha256 `a3970d865b3b76677afe0b11b6061156e3be633a50613167887ef8a54fe14563`
- `cpl.csv` sha256 `49d74d87ea8ab56fc187e916bd535c119c798f6744d08fc222e989418c47bfb3`

## excluded from the archive

- `(none)`: every exported layer was approved
