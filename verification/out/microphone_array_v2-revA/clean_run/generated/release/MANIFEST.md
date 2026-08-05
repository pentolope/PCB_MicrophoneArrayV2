# Fabrication release manifest

- generated: 2026-08-05T00:41:04.539712+00:00
- kicad: 10.0.5
- constraint profile: jlcpcb-4layer-assembled
- source closure sha256: `c6b444a46f21e9c69597686dca165b8a30bee214fe9e9c59ee740aefd0974b4d`

## command

    kicad-cli.exe sch erc --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone_array_v2-revA\clean_run\reports\erc.json --format json --severity-all --exit-code-violations C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone_array_v2-revA\clean_run\fixture\project\microphone_array_v2.kicad_sch
    kicad-cli.exe pcb drc --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone_array_v2-revA\clean_run\reports\drc.json --format json --severity-all --all-track-errors --schematic-parity --exit-code-violations C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone_array_v2-revA\clean_run\fixture\project\microphone_array_v2.kicad_pcb
    kicad-cli.exe pcb export gerbers --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone_array_v2-revA\clean_run\generated\gerbers --layers F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts --no-protel-ext --use-drill-file-origin --subtract-soldermask C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone_array_v2-revA\clean_run\fixture\project\microphone_array_v2.kicad_pcb
    kicad-cli.exe pcb export drill --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone_array_v2-revA\clean_run\generated\gerbers --format excellon --excellon-separate-th --drill-origin plot C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone_array_v2-revA\clean_run\fixture\project\microphone_array_v2.kicad_pcb
    kicad-cli.exe pcb export pos --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone_array_v2-revA\clean_run\generated\release\cpl.csv --format csv --units mm --side both --exclude-dnp C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone_array_v2-revA\clean_run\fixture\project\microphone_array_v2.kicad_pcb
    kicad-cli.exe sch export bom --output C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone_array_v2-revA\clean_run\generated\release\bom.csv --fields ${QUANTITY},Reference,Value,Footprint,LCSC --labels "Quantity,Designator,Comment,Footprint,LCSC Part #" --group-by Value,Footprint,LCSC --exclude-dnp --ref-range-delimiter  C:\Users\pentolope\Documents\GitHub\PCB_MicrophoneArrayV2\verification\out\microphone_array_v2-revA\clean_run\fixture\project\microphone_array_v2.kicad_sch

## artifacts

- `microphone_array_v2-revA-fabrication.zip` sha256 `fd4feebc551ac12c84ff2310154449c8b7c5c442f1473620142a2f10d9bc2014`
- `bom.csv` sha256 `ff6691d246c62303dc07639948ab3731fd0691413a4c6d61ad19d65f4d625d9b`
- `cpl.csv` sha256 `305e391553aad2e0ea7647e4b7571495a5777fe80d91dce5947bfa2ee623b964`

## excluded from the archive

- `(none)` (-): every exported layer was approved
