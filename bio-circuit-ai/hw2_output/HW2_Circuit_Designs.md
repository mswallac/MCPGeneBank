# BE552 HW2 -- Genetic Circuit Designs & DAMP Lab Workflows

Generated from MCPGeneBank pipeline using real iGEM BioBrick parts.
Three distinct circuits for three DAMP Lab Canvas workflow submissions.

---

## Circuit 1: Arsenic Biosensor (Green Fluorescence)

**Pattern:** Biosensor
**Total size:** 1,169 bp
**Assembly method:** Gibson Assembly
**Host:** E. coli DH5a
**Backbone:** pSB1C3 (chloramphenicol resistance)

### Parts List

| Role | Part ID | Name | bp | iGEM Registry |
|------|---------|------|----|---------------|
| Promoter | BBa_K1031907 | Pars Arsenic Sensing Promoter | 92 | https://parts.igem.org/Part:BBa_K1031907 |
| RBS | BBa_B0034 | RBS B0034 | 12 | https://parts.igem.org/Part:BBa_B0034 |
| Regulator | BBa_K1031311 | ArsR Transcription Factor | 219 | https://parts.igem.org/Part:BBa_K1031311 |
| Terminator | BBa_B0015 | Double Terminator B0015 | 129 | https://parts.igem.org/Part:BBa_B0015 |
| Reporter | BBa_E0040 | GFP (Green Fluorescent Protein) | 717 | https://parts.igem.org/Part:BBa_E0040 |

### Transcription Units

**TU1 -- Sensor Module (452 bp):**
```
Pars Promoter --> RBS B0034 --> ArsR --> Terminator B0015
```

**TU2 -- Reporter Module (717 bp):**
```
GFP
```

### Regulatory Wiring
```
sensor --[activates]--> regulator
regulator --[activates]--> reporter
```

**How it works:** Arsenic (arsenite ions) binds ArsR, causing it to release from the Pars
promoter. This de-represses transcription, driving GFP expression. More arsenic = more green
fluorescence.

### DAMP Lab Canvas Workflow

**Operations to drag onto Canvas (in order):**

1. **PCR Amplification**
   - Amplify each TU with Gibson-overlap primers (20-40 bp overlaps)
   - Template: iGEM DNA Distribution Kit or IDT gBlock synthesis
   - Primers: 20 bp binding + 20 bp overlap per junction
   - Polymerase: Q5 High-Fidelity (NEB)
   - Cycling: 98C 30s, 30x(98C 10s, 60C 30s, 72C 30s/kb), 72C 5min

2. **Gel Electrophoresis (QC)**
   - 1% agarose gel to verify correct band sizes
   - Expected: TU1 sensor (~452 bp), TU2 reporter (~717 bp)

3. **PCR Cleanup / Gel Extraction**
   - Monarch PCR & DNA Cleanup Kit (NEB) or gel extract if non-specific bands

4. **Gibson Assembly**
   - Combine linearized pSB1C3 backbone + 2 TU inserts
   - Reagent: NEBuilder HiFi DNA Assembly Master Mix (NEB E2621)
   - Incubation: 50C for 60 minutes
   - Molar ratio: 1:2 vector:insert

5. **Transformation**
   - Heat-shock into chemically competent E. coli DH5a
   - Cells: NEB 5-alpha Competent E. coli (NEB C2987)
   - Protocol: Ice 10 min, add 2 uL assembly, ice 30 min, 42C 30s, ice 5 min, 950 uL SOC, 37C 1h, plate
   - Selection: LB + chloramphenicol (25 ug/mL)

6. **Colony PCR Screening**
   - Screen 8-12 colonies with VF2/VR primers
   - Expected size: ~1,169 bp

7. **Plasmid Miniprep**
   - Monarch Plasmid Miniprep Kit (NEB T1010)

8. **Functional Assay -- Fluorescence Plate Reader**
   - Induce with 0, 1, 5, 10, 50 uM sodium arsenite
   - Measure GFP (ex485/em528) at 0, 2, 4, 6h
   - Controls: Empty pSB1C3 (negative), constitutive GFP (positive)
   - Instrument: BioTek Synergy plate reader

### Full Sequences

**TU1 -- Sensor Module (452 bp):**
```
TTGACAAAAAATGGCATCCATTGTCATAAATTTCTTTAATCTTGTTCAACAAAATCGATTTTTCCCCTAACACTTGATACTGTATTACAGAAAAAGAGGAGAAAATGAATATCAACATTTCCGTGAATTTAGCCGCCGAAATCAGCCTGTTCTCCCCGGAACAGGTAATGGGCCTCGGCAGTGTGCTTGCCGCAATCAAAGAGTTTGGCATCACCCACTGGAGCAGCGACTACACCCACATGCTGAGATCTTCCCGCAGACTGGCGTGCCGCCAGCTTCGCTGTCACGTTTCGTCTGTGAAGTGCACCATAACCCGCAACTGACCAGGCATCAAATAAAACGAAAGGCTCAGTCGAAAGACTGGGCCTTTCGTTTTATCTGTTGTTTGTCGGTGAACGCTCTCTACTAGAGTCACACTGGCTCACCTTCGGGTGGGCCTTTCTGCGTTTATA
```

**TU2 -- Reporter / GFP (717 bp):**
```
ATGCGTAAAGGAGAAGAACTTTTCACTGGAGTTGTCCCAATTCTTGTTGAATTAGATGGTGATGTTAATGGGCACAAATTTTCTGTCAGTGGAGAGGGTGAAGGTGATGCAACATACGGAAAACTTACCCTTAAATTTATTTGCACTACTGGAAAACTACCTGTTCCATGGCCAACACTTGTCACTACTTTCGGTTATGGTGTTCAATGCTTTGCGAGATACCCAGATCATATGAAACAGCATGACTTTTTCAAGAGTGCCATGCCCGAAGGTTATGTACAGGAAAGAACTATATTTTTCAAAGATGACGGGAACTACAAGACACGTGCTGAAGTCAAGTTTGAAGGTGATACCCTTGTTAATAGAATCGAGTTAAAAGGTATTGATTTTAAAGAAGATGGAAACATTCTTGGACACAAATTGGAATACAACTATAACTCACACAATGTATACATCATGGCAGACAAACAAAAGAATGGAATCAAAGTTAACTTCAAAATTAGACACAACATTGAAGATGGAAGCGTTCAACTAGCAGACCATTATCAACAAAATACTCCAATTGGCGATGGCCCTGTCCTTTTACCAGACAACCATTACCTGTCCACACAATCTGCCCTTTCGAAAGATCCCAACGAAAAGAGAGACCACATGGTCCTTCTTGAGTTTGTAACAGCTGCTGGGATTACACATGGCATGGATGAACTATACAAATAA
```

---

## Circuit 2: IPTG/Tetracycline Toggle Switch

**Pattern:** Toggle Switch (bistable)
**Total size:** 3,643 bp
**Assembly method:** Golden Gate (BsaI) / MoClo
**Host:** E. coli DH5a
**Backbone:** pSB1C3 or DVA level-1 destination vector

### Parts List

| Role | Part ID | Name | bp | iGEM Registry |
|------|---------|------|----|---------------|
| Promoter A | BBa_R0010 | PLlac/ara Promoter (IPTG-inducible) | 172 | https://parts.igem.org/Part:BBa_R0010 |
| RBS | BBa_B0034 | RBS B0034 | 12 | https://parts.igem.org/Part:BBa_B0034 |
| Repressor A | BBa_C0040 | TetR Repressor | 624 | https://parts.igem.org/Part:BBa_C0040 |
| RBS | BBa_B0034 | RBS B0034 | 12 | https://parts.igem.org/Part:BBa_B0034 |
| Reporter A | BBa_E0040 | GFP (Green Fluorescent Protein) | 717 | https://parts.igem.org/Part:BBa_E0040 |
| Terminator | BBa_B0015 | Double Terminator B0015 | 129 | https://parts.igem.org/Part:BBa_B0015 |
| Promoter B | BBa_R0040 | PLtet Promoter (aTc-inducible) | 54 | https://parts.igem.org/Part:BBa_R0040 |
| RBS | BBa_B0034 | RBS B0034 | 12 | https://parts.igem.org/Part:BBa_B0034 |
| Repressor B | BBa_C0012 | LacI Repressor | 1,092 | https://parts.igem.org/Part:BBa_C0012 |
| RBS | BBa_B0034 | RBS B0034 | 12 | https://parts.igem.org/Part:BBa_B0034 |
| Reporter B | BBa_E1010 | mRFP1 (Red Fluorescent Protein) | 678 | https://parts.igem.org/Part:BBa_E1010 |
| Terminator | BBa_B0015 | Double Terminator B0015 | 129 | https://parts.igem.org/Part:BBa_B0015 |

### Transcription Units

**TU1 -- Module A (1,666 bp):**
```
PLlac Promoter --> RBS --> TetR Repressor --> RBS --> GFP --> Terminator
```

**TU2 -- Module B (1,977 bp):**
```
PLtet Promoter --> RBS --> LacI Repressor --> RBS --> mRFP1 --> Terminator
```

### Regulatory Wiring
```
promoter_a (PLlac) --[activates]--> repressor_a (TetR)
promoter_a (PLlac) --[activates]--> reporter_a (GFP)
repressor_a (TetR)  --[represses]--> promoter_b (PLtet)

promoter_b (PLtet) --[activates]--> repressor_b (LacI)
promoter_b (PLtet) --[activates]--> reporter_b (mRFP1)
repressor_b (LacI)  --[represses]--> promoter_a (PLlac)
```

**How it works:** Two mutually repressing modules form a bistable switch.
- Add IPTG --> releases LacI from PLlac --> Module A ON (TetR + GFP) --> TetR represses PLtet --> Module B OFF
- Add aTc --> releases TetR from PLtet --> Module B ON (LacI + RFP) --> LacI represses PLlac --> Module A OFF
- The circuit stays in whichever state was last induced (memory/bistability).

### DAMP Lab Canvas Workflow

**Operations to drag onto Canvas (in order):**

1. **Part Domestication (BsaI site removal)**
   - Check all parts for internal BsaI sites; remove by silent mutagenesis
   - Tool: Benchling or SnapGene for in-silico BsaI scan

2. **PCR Amplification with BsaI-flanked Primers**
   - Add BsaI recognition sites + 4-nt fusion sites to each part
   - Fusion standard: MoClo / PhytoBrick overhangs (GGAG, AATG, GCTT, etc.)
   - Polymerase: Q5 High-Fidelity (NEB)

3. **Golden Gate Assembly (Level 1 -- TU assembly)**
   - One-pot restriction-ligation with BsaI + T4 ligase for each TU
   - Enzyme: BsaI-HFv2 (NEB R3733)
   - Ligase: T4 DNA Ligase (NEB M0202)
   - Protocol: 30x(37C 2min, 16C 5min), 55C 10min, 80C 10min

4. **Transformation (TU plasmids)**
   - Transform each TU-level assembly separately into DH5a
   - Selection: appropriate antibiotic for destination vector

5. **Level 2 Assembly (Multi-TU into single backbone)**
   - Combine TU-bearing plasmids via BsmBI Golden Gate into final backbone
   - Enzyme: BsmBI-v2 (NEB R0739)

6. **Transformation (Final construct)**
   - Transform level-2 assembly into DH5a
   - Selection: LB + chloramphenicol (25 ug/mL)

7. **Colony PCR + Sanger Sequencing**
   - Screen colonies; send positives for full sequencing

8. **Plasmid Miniprep**
   - Monarch Plasmid Miniprep Kit (NEB T1010)

9. **Functional Assay -- Toggle Switch Bistability**
   - Induce state A: 1 mM IPTG (expect GFP)
   - Wash, induce state B: 200 ng/mL aTc (expect RFP)
   - Measure GFP (ex485/em528) and RFP (ex555/em607) over 8h
   - Controls: uninduced (both off), single-inducer controls
   - Instrument: BioTek Synergy plate reader or flow cytometer

---

## Circuit 3: NOT Gate (IPTG Inverter)

**Pattern:** Logic NOT (inverter)
**Total size:** 2,337 bp
**Assembly method:** Gibson Assembly
**Host:** E. coli DH5a
**Backbone:** pSB1C3 (chloramphenicol resistance)

### Parts List

| Role | Part ID | Name | bp | iGEM Registry |
|------|---------|------|----|---------------|
| Promoter (output) | BBa_R0011 | PLlacIq Promoter | 74 | https://parts.igem.org/Part:BBa_R0011 |
| RBS | BBa_B0034 | RBS B0034 | 12 | https://parts.igem.org/Part:BBa_B0034 |
| Reporter | BBa_E0040 | GFP (Green Fluorescent Protein) | 717 | https://parts.igem.org/Part:BBa_E0040 |
| Terminator | BBa_B0015 | Double Terminator B0015 | 129 | https://parts.igem.org/Part:BBa_B0015 |
| Promoter (input) | BBa_R0010 | PLlac/ara Promoter (IPTG-inducible) | 172 | https://parts.igem.org/Part:BBa_R0010 |
| RBS | BBa_B0034 | RBS B0034 | 12 | https://parts.igem.org/Part:BBa_B0034 |
| Repressor | BBa_C0012 | LacI Repressor | 1,092 | https://parts.igem.org/Part:BBa_C0012 |
| Terminator | BBa_B0015 | Double Terminator B0015 | 129 | https://parts.igem.org/Part:BBa_B0015 |

### Transcription Units

**TU1 -- Output Module (932 bp):**
```
PLlacIq Promoter --> RBS B0034 --> GFP --> Terminator B0015
```

**TU2 -- Input/Inverter Module (1,405 bp):**
```
PLlac/ara Promoter --> RBS B0034 --> LacI Repressor --> Terminator B0015
```

### Regulatory Wiring
```
input_promoter (PLlac)   --[activates]-->  inverter_repressor (LacI)
inverter_repressor (LacI) --[represses]--> output_promoter (PLlacIq)
output_promoter (PLlacIq) --[activates]-->  output_reporter (GFP)
```

**How it works:** This is a genetic inverter (NOT gate).
- No IPTG: PLlac is weakly active, minimal LacI produced. PLlacIq is free --> GFP ON
- Add IPTG: PLlac fully active, lots of LacI --> LacI represses PLlacIq --> GFP OFF
- Input HIGH = Output LOW. Classic Boolean NOT logic.

### DAMP Lab Canvas Workflow

**Operations to drag onto Canvas (in order):**

1. **PCR Amplification**
   - Amplify TUs with Gibson-overlap primers
   - Template: iGEM Distribution Kit or IDT gBlocks
   - Polymerase: Q5 High-Fidelity (NEB)

2. **Gel Electrophoresis (QC)**
   - 1% agarose gel; verify PCR product sizes

3. **DpnI Digestion**
   - Digest template DNA with DpnI (NEB R0176) 1h @ 37C
   - Removes original plasmid template

4. **PCR Cleanup**
   - Monarch PCR & DNA Cleanup Kit (NEB T1030)

5. **Gibson Assembly**
   - Assemble linearized backbone + inserts
   - Reagent: NEBuilder HiFi DNA Assembly Master Mix (NEB E2621)
   - Incubation: 50C for 60 minutes

6. **Transformation**
   - Heat-shock into DH5a competent cells
   - Selection: LB + chloramphenicol (25 ug/mL)

7. **Colony PCR + Sequencing Verification**
   - Screen colonies with VF2/VR; send positives for Sanger sequencing

8. **Plasmid Miniprep**
   - Isolate plasmid from sequence-verified colony

9. **Functional Assay -- Transfer Function (Dose-Response)**
   - IPTG gradient: 0, 0.01, 0.1, 0.5, 1, 5, 10 mM
   - Expect: HIGH GFP at 0 IPTG (inverter ON), LOW GFP at high IPTG (inverter OFF)
   - Plot transfer function curve (input vs output)
   - Timepoints: 0, 2, 4, 6, 8 hours post-induction
   - Controls: constitutive GFP (positive max), empty vector (negative)
   - Instrument: BioTek Synergy plate reader

---

## Summary: Three Variations for DAMP Lab Canvas

| | Circuit 1 | Circuit 2 | Circuit 3 |
|---|-----------|-----------|-----------|
| **Type** | Arsenic Biosensor | Toggle Switch | NOT Gate |
| **Size** | 1,169 bp | 3,643 bp | 2,337 bp |
| **Parts** | 5 | 12 | 8 |
| **Assembly** | Gibson Assembly | Golden Gate / MoClo | Gibson Assembly |
| **Assay** | Fluorescence vs [arsenite] | Bistability switching | Dose-response transfer fn |
| **Distinct because** | Different circuit | Different assembly method | Different assay type |

All three use real iGEM BioBrick parts with verified sequences.
