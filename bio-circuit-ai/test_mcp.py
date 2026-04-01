"""Quick smoke test of all MCP tool functions."""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from mcp_server import (
    search_parts,
    get_part,
    list_part_types,
    list_circuit_templates,
    build_from_template,
    design_circuit,
    get_circuit_sequence,
)

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# 1. Search
section("search_parts('arsenic sensor')")
result = json.loads(search_parts("arsenic sensor", limit=3))
print(f"Found {result['count']} parts:")
for p in result["parts"]:
    print(f"  {p['part_id']:20s} {p['type']:10s} {p['name'][:50]}")

# 2. Get specific part
section("get_part('BBa_E0040')")
result = json.loads(get_part("BBa_E0040"))
part = result.get("part", result)
print(f"Name: {part.get('name', '')}")
print(f"Type: {part.get('type', '')}")
print(f"Seq length: {part.get('sequence_length', 0)} bp")
print(f"Seq preview: {part.get('sequence', part.get('sequence_preview', ''))[:60]}...")

# 3. List types
section("list_part_types()")
result = json.loads(list_part_types())
print(f"Total: {result['total_parts']} parts")
for t, c in result["types"].items():
    print(f"  {t:15s} {c}")

# 4. Templates
section("list_circuit_templates()")
result = json.loads(list_circuit_templates())
for name, info in result["templates"].items():
    print(f"  {name:20s} {info['description'][:60]}")

# 5. Build from template
section("build_from_template('biosensor', target='arsenic', output='GFP')")
result = json.loads(build_from_template("biosensor", {"target": "arsenic", "output": "GFP"}))
print(f"Circuit: {result.get('circuit_name', '')}")
print(f"Pattern: {result.get('pattern', '')}")
print(f"Sequence length: {result.get('total_sequence_length', 0)} bp")
for tu in result.get("transcription_units", []):
    parts_str = " -> ".join(p.get("part", "") for p in tu.get("parts", []))
    print(f"  TU {tu['unit_id']}: {parts_str}")

# 6. Natural language design
section("design_circuit('Design a biosensor that detects mercury and glows green')")
result = json.loads(design_circuit("Design a biosensor that detects mercury and glows green"))
print(f"Circuit: {result.get('circuit_name', '')}")
print(f"Sequence length: {result.get('total_sequence_length', 0)} bp")
for tu in result.get("transcription_units", []):
    parts_str = " -> ".join(p.get("part", "") for p in tu.get("parts", []))
    print(f"  TU {tu['unit_id']}: {parts_str}")

# 7. Get sequence
section("get_circuit_sequence('kill switch activated by arabinose')")
result = json.loads(get_circuit_sequence("kill switch activated by arabinose"))
print(f"Circuit: {result.get('circuit_name', '')}")
print(f"Total length: {result.get('total_length_bp', 0)} bp")
seq = result.get("sequence", "")
if seq:
    print(f"Sequence (first 100bp): {seq[:100]}...")
else:
    print("(no sequence assembled)")

print(f"\n{'='*60}")
print("  ALL TESTS PASSED")
print(f"{'='*60}")
