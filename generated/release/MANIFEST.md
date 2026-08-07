# Fabrication release manifest

- generated: 2026-08-07T01:37:58.749545+00:00
- kicad: 10.0.5
- constraint profile: jlcpcb-4layer-assembled
- source closure sha256: `e8aa93bfec59cd6e3772b9187004bb8dedff7568b4fb178c1062e6873b8f8dc1`

## command

    kicad-cli.exe sch erc --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260807T013746Z-87c898fc\work\clean_run\reports\erc.json --format json --severity-all --severity-exclusions --exit-code-violations C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260807T013746Z-87c898fc\work\clean_run\fixture\project\microphone_array_v2.kicad_sch
    kicad-cli.exe pcb drc --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260807T013746Z-87c898fc\work\clean_run\reports\drc.json --format json --severity-all --severity-exclusions --all-track-errors --schematic-parity --refill-zones --save-board --exit-code-violations C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260807T013746Z-87c898fc\work\clean_run\fixture\project\microphone_array_v2.kicad_pcb
    kicad-cli.exe pcb export gerbers --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260807T013746Z-87c898fc\work\clean_run\generated\gerbers --layers F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts --no-protel-ext --use-drill-file-origin --subtract-soldermask C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260807T013746Z-87c898fc\work\clean_run\fixture\project\microphone_array_v2.kicad_pcb
    kicad-cli.exe pcb export drill --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260807T013746Z-87c898fc\work\clean_run\generated\gerbers --format excellon --excellon-separate-th --drill-origin plot C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260807T013746Z-87c898fc\work\clean_run\fixture\project\microphone_array_v2.kicad_pcb
    kicad-cli.exe pcb export pos --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260807T013746Z-87c898fc\build\cpl.csv --format csv --units mm --side both --exclude-dnp C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260807T013746Z-87c898fc\work\clean_run\fixture\project\microphone_array_v2.kicad_pcb
    kicad-cli.exe sch export bom --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260807T013746Z-87c898fc\build\bom.csv --fields ${QUANTITY},Reference,Value,Footprint,LCSC --labels "Quantity,Designator,Comment,Footprint,LCSC Part #" --group-by Value,Footprint,LCSC --exclude-dnp --ref-range-delimiter  C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone-array-v2-live\attempts\20260807T013746Z-87c898fc\work\clean_run\fixture\project\microphone_array_v2.kicad_sch

## artifacts

- `microphone_array_v2-revA-fabrication.zip` sha256 `842651323c1597c33d3a591413818d4bb07d4a0f26117a69bb91d9154a795f32`
- `bom.csv` sha256 `ff6691d246c62303dc07639948ab3731fd0691413a4c6d61ad19d65f4d625d9b`
- `cpl.csv` sha256 `305e391553aad2e0ea7647e4b7571495a5777fe80d91dce5947bfa2ee623b964`

## excluded from the archive

- `(none)` (-): every exported layer was approved
