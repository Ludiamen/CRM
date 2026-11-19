"""T-8300: сверка состава красного прогона T-8160 (junit) с текущим сбором pytest."""
import re
import sys
import xml.etree.ElementTree as ET


def nodeid(classname: str, name: str) -> str:
    path = classname.replace(".", "/") + ".py"
    return f"{path}::{name}"


red = set()
tree = ET.parse(sys.argv[1])
for case in tree.iter("testcase"):
    red.add(nodeid(case.get("classname", ""), case.get("name", "")))

green = set()
for line in open(sys.argv[2], encoding="utf-8"):
    line = line.strip()
    if "::" in line:
        green.add(line)

added = sorted(green - red)
removed = sorted(red - green)
print(f"red={len(red)} green={len(green)} added={len(added)} removed={len(removed)}")
print("--- added")
for n in added:
    print(n)
print("--- removed")
for n in removed:
    print(n)